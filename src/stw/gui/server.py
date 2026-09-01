"""
The FastAPI app behind `stw gui`. Runs entirely on localhost, driving the
same `RunConfig`/`registry()`/`run_config()` core the CLI uses — this is a
thin transport layer, not a second implementation of anything.

Each run executes in a background thread (`run_config` is a blocking,
synchronous call that mostly waits on subprocesses — the GIL releases fine
during that, and this is a single-user local tool, so a plain in-memory
`RUNS` dict + `threading.Thread` is all the concurrency story needed; no
database, no auth, nothing that would matter for a multi-user deployment
because this is never meant to be deployed anywhere).

Progress reaches the browser via Server-Sent Events: `QueueProgressSink`
mirrors `JsonlProgressSink`'s event shape (see `stw.progress`) but pushes
into an in-memory `queue.Queue` instead of writing lines to a file, and
`/api/runs/{id}/events` streams that queue out as `text/event-stream`.
"""
from __future__ import annotations

import json
import queue
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from stw.adapters import registry
from stw.align import AlignConfig, run_pytom_alignment
from stw.align import check_installed as check_align_installed
from stw.averaging import global_average
from stw.capabilities import Capabilities
from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.spec import ParticleSet, ParticleSetError


class QueueProgressSink:
    def __init__(self, q: queue.Queue) -> None:
        self._q = q

    def _emit(self, event: str, package: str, **payload: Any) -> None:
        self._q.put({"event": event, "package": package, "payload": payload})

    def start_job(self, package: str, steps: list[str]) -> None:
        self._emit("start_job", package, steps=steps)

    def step(self, package: str, name: str, index: int, total: int) -> None:
        self._emit("step", package, name=name, index=index, total=total)

    def substep(self, package: str, text: str) -> None:
        self._emit("substep", package, text=text)

    def log_line(self, package: str, line: str) -> None:
        self._emit("log_line", package, line=line)

    def finish_job(self, package: str, ok: bool, message: str = "") -> None:
        self._emit("finish_job", package, ok=ok, message=message)


@dataclass
class RunState:
    run_id: str
    status: str = "running"  # running | done | error
    error: str | None = None
    report: dict | None = None
    out_dir: str | None = None
    events: queue.Queue = field(default_factory=queue.Queue)
    # One Event per requested package, created at submit time (see start_run()) --
    # lets /api/runs/{id}/cancel/{package} signal a live run_config() call without
    # any other coupling between the HTTP layer and the background run thread.
    cancel_flags: dict[str, threading.Event] = field(default_factory=dict)


RUNS: dict[str, RunState] = {}


@dataclass
class AlignState:
    align_id: str
    status: str = "running"  # running | done | error
    error: str | None = None
    report: dict | None = None
    events: queue.Queue = field(default_factory=queue.Queue)


ALIGNS: dict[str, AlignState] = {}


@dataclass
class PreviewState:
    preview_id: str
    status: str = "running"  # running | done | error
    error: str | None = None
    result: dict | None = None
    events: queue.Queue = field(default_factory=queue.Queue)


PREVIEWS: dict[str, PreviewState] = {}

# The global average is the expensive part of both the dataset preview and the
# mask preview (streaming every particle volume off disk, tens of minutes at
# ATPase-EMPIAR scale -- 83k particles). Keyed by ParticleSet.fingerprint() so
# "preview mask" right after "preview dataset" reuses the same array instead of
# recomputing it, and vice versa. Small FIFO cap since this is an in-memory,
# single-user, no-persistence process (same story as RUNS/ALIGNS).
_GLOBAL_AVG_CACHE: dict[str, np.ndarray] = {}
_GLOBAL_AVG_CACHE_ORDER: list[str] = []
_GLOBAL_AVG_CACHE_MAX = 4


def _cached_global_average(
    particles: ParticleSet, progress_cb: Any = None
) -> np.ndarray:
    key = particles.fingerprint()
    cached = _GLOBAL_AVG_CACHE.get(key)
    if cached is not None:
        return cached
    avg = global_average(particles.particle_dir, list(particles.files), progress_cb=progress_cb)
    _GLOBAL_AVG_CACHE[key] = avg
    _GLOBAL_AVG_CACHE_ORDER.append(key)
    if len(_GLOBAL_AVG_CACHE_ORDER) > _GLOBAL_AVG_CACHE_MAX:
        _GLOBAL_AVG_CACHE.pop(_GLOBAL_AVG_CACHE_ORDER.pop(0), None)
    return avg


def _throttled_progress(q: queue.Queue, total: int):
    """~200 SSE events for the whole run regardless of particle count, so an
    83k-particle dataset doesn't flood the queue with one put() per particle."""
    step = max(1, total // 200)

    def cb(done: int, total_: int) -> None:
        if done == total_ or done % step == 0:
            q.put({"event": "progress", "payload": {"done": done, "total": total_}})

    return cb


def _execute_preview(preview_id: str, particles: ParticleSet, mask_body: dict[str, Any] | None) -> None:
    from fastapi import HTTPException

    state = PREVIEWS[preview_id]
    q = state.events
    total = len(particles.files)
    progress_cb = _throttled_progress(q, total)
    try:
        avg = _cached_global_average(particles, progress_cb=progress_cb)
        if mask_body is not None:
            from stw.gui.render import render_mask_overlay_png

            mask = _build_preview_mask(mask_body, particles, avg=avg)
            png_bytes = render_mask_overlay_png(avg, mask, title=f"mask preview, n={total}")
        else:
            from stw.gui.render import render_volume_slice_png

            png_bytes = render_volume_slice_png(avg, title=f"global average, n={total}")
        import base64

        state.result = {
            "n_particles": total,
            "box": particles.box,
            "pixel_size": particles.pixel_size,
            "preview_png_base64": base64.b64encode(png_bytes).decode("ascii"),
        }
        state.status = "done"
    except HTTPException as e:
        state.status = "error"
        state.error = str(e.detail)
    except Exception as e:  # noqa: BLE001 - surfaced to the UI, not swallowed
        state.status = "error"
        state.error = str(e)
    finally:
        q.put(None)


def _caps_to_dict(caps: Capabilities) -> dict:
    return {
        "mask_kinds": sorted(str(k) for k in caps.mask_kinds),
        "wedge": sorted(str(w) for w in caps.wedge),
        "alignment_states": sorted(str(a) for a in caps.alignment_states),
        "variable_k": caps.variable_k,
        "k_range": list(caps.k_range),
        "deterministic": caps.deterministic,
        "seed_semantics": caps.seed_semantics,
        "gpu": caps.gpu,
        "emits_native_class_averages": caps.emits_native_class_averages,
        "parallelism": caps.parallelism,
        "min_particles": caps.min_particles,
    }


def _discover_particles(body: dict[str, Any]) -> ParticleSet:
    from fastapi import HTTPException

    particles_dir = body.get("particles", "")
    pattern = body.get("pattern") or "*.mrc"
    pixel_size = body.get("pixel_size")
    try:
        return ParticleSet.discover(particles_dir, pattern, pixel_size)
    except ParticleSetError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _validate_mask_body(mask_body: dict[str, Any]) -> None:
    """Fails fast (422, before any background work starts) on mask configs missing
    fields no amount of particle loading could ever fill in -- called synchronously
    from the endpoint so a bad mask form doesn't need a background job + SSE round
    trip just to report a typo."""
    from fastapi import HTTPException

    kind = mask_body.get("kind", "auto")
    if kind == "sphere" and mask_body.get("radius") is None:
        raise HTTPException(status_code=422, detail="mask kind=sphere requires radius")
    if kind == "cylinder" and (mask_body.get("radius") is None or mask_body.get("half_height") is None):
        raise HTTPException(status_code=422, detail="mask kind=cylinder requires radius and half_height")
    if kind == "file" and not mask_body.get("path"):
        raise HTTPException(status_code=422, detail="mask kind=file requires path")
    if kind == "none":
        raise HTTPException(status_code=422, detail="mask kind=none has no mask to preview")


def _build_preview_mask(
    mask_body: dict[str, Any], particles: ParticleSet, *, avg: np.ndarray | None = None
) -> np.ndarray:
    """Builds a mask straight from the mask primitives (build_sphere/build_cylinder/
    auto_sphere_mask/load_mrc), not resolve_mask() -- this is a throwaway preview with
    no run/cache_dir to key a cached mask file under, and shouldn't write one.
    Assumes _validate_mask_body() already passed.

    `avg`: an already-computed global average, forwarded to auto_sphere_mask() for
    kind="auto" so it doesn't stream every particle off disk a second time."""
    from fastapi import HTTPException

    from stw.io.mrc import load_mrc
    from stw.masks.auto import auto_sphere_mask
    from stw.masks.primitives import box_center, build_cylinder, build_sphere

    kind = mask_body.get("kind", "auto")
    box = particles.box
    shape = (box, box, box)
    center = tuple(mask_body["center"]) if mask_body.get("center") else box_center(shape)
    edge = float(mask_body.get("edge", 3.0))

    if kind == "sphere":
        return build_sphere(shape, center, float(mask_body["radius"]), edge)
    if kind == "cylinder":
        axis = mask_body.get("axis", "z")
        return build_cylinder(shape, center, float(mask_body["radius"]), float(mask_body["half_height"]), axis, edge)
    if kind == "auto":
        mask, _center, _radius = auto_sphere_mask(particles, avg=avg)
        return mask
    if kind == "file":
        try:
            mask = load_mrc(mask_body["path"])
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"could not load mask file: {e}") from e
        if mask.shape != shape:
            raise HTTPException(
                status_code=422, detail=f"mask file shape {mask.shape} != particle box {shape}"
            )
        return mask
    raise HTTPException(status_code=422, detail=f"unknown mask kind: {kind}")


def _execute_align(align_id: str, cfg: AlignConfig) -> None:
    state = ALIGNS[align_id]
    sink = QueueProgressSink(state.events)
    try:
        report = run_pytom_alignment(cfg, progress=sink)
        state.report = report.to_dict()
        state.status = "done" if report.status == "ok" else "error"
        state.error = report.error
    except Exception as e:  # noqa: BLE001 - surfaced to the UI, not swallowed
        state.status = "error"
        state.error = str(e)
    finally:
        state.events.put(None)


def _execute(run_id: str, cfg: RunConfig) -> None:
    state = RUNS[run_id]
    sink = QueueProgressSink(state.events)
    try:
        report = run_config(cfg, progress=sink, cancel_flags=state.cancel_flags)
        state.report = asdict(report)
        state.out_dir = str(cfg.out_dir)
        state.status = "done"
    except Exception as e:  # noqa: BLE001 - surfaced to the UI, not swallowed
        state.status = "error"
        state.error = str(e)
    finally:
        state.events.put(None)  # sentinel: tells the SSE generator the run is over


def create_app():
    from fastapi import FastAPI, HTTPException, Response
    from fastapi.responses import FileResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="stw", docs_url="/api/docs")

    @app.get("/api/packages")
    def list_packages() -> list[dict]:
        out = []
        for name, adapter_cls in sorted(registry().items()):
            report = adapter_cls.check_installed()
            out.append({
                **report.to_dict(),
                "name": name,
                "algorithm": adapter_cls.algorithm,
                "capabilities": _caps_to_dict(adapter_cls.capabilities),
            })
        return out

    @app.get("/api/schema")
    def schema() -> dict:
        return RunConfig.model_json_schema()

    @app.post("/api/preview")
    def preview_dataset(body: dict[str, Any]) -> dict:
        """Loads the particle set (no run started) and kicks off, in a background
        thread, the unweighted global average that a central-slice preview PNG
        needs -- streaming every particle off disk is the slow part at real-dataset
        scale (tens of minutes for tens of thousands of particles), so this returns
        a preview_id immediately; poll progress via /api/preview/{id}/events and
        fetch the finished PNG via /api/preview/{id}/result."""
        particles = _discover_particles(body)
        preview_id = uuid.uuid4().hex[:12]
        PREVIEWS[preview_id] = PreviewState(preview_id=preview_id)
        thread = threading.Thread(target=_execute_preview, args=(preview_id, particles, None), daemon=True)
        thread.start()
        return {"preview_id": preview_id, "n_particles": len(particles.files)}

    @app.post("/api/preview-mask")
    def preview_mask(body: dict[str, Any]) -> dict:
        """Same particle-set load and background-job shape as /api/preview, plus
        builds the mask straight from the current form's mask.* fields (never
        resolve_mask() -- there's no run/cache_dir here) to overlay as a
        semi-transparent color fill on the central-slice global average. The
        global average itself is shared with /api/preview via
        _cached_global_average() keyed on the particle set's fingerprint, so
        previewing the mask right after previewing the dataset (or vice versa)
        does not re-stream the whole particle set off disk a second time."""
        particles = _discover_particles(body)
        mask_body = body.get("mask") or {}
        _validate_mask_body(mask_body)
        preview_id = uuid.uuid4().hex[:12]
        PREVIEWS[preview_id] = PreviewState(preview_id=preview_id)
        thread = threading.Thread(
            target=_execute_preview, args=(preview_id, particles, mask_body), daemon=True
        )
        thread.start()
        return {"preview_id": preview_id, "n_particles": len(particles.files)}

    @app.get("/api/preview/{preview_id}/events")
    def preview_events(preview_id: str):
        state = PREVIEWS.get(preview_id)
        if state is None:
            raise HTTPException(status_code=404, detail="unknown preview_id")

        def gen():
            while True:
                item = state.events.get()
                if item is None:
                    final = {
                        "event": "preview_complete",
                        "payload": {"status": state.status, "error": state.error},
                    }
                    yield f"data: {json.dumps(final)}\n\n"
                    break
                yield f"data: {json.dumps(item)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/preview/{preview_id}/result")
    def preview_result(preview_id: str) -> dict:
        state = PREVIEWS.get(preview_id)
        if state is None:
            raise HTTPException(status_code=404, detail="unknown preview_id")
        if state.status == "running":
            raise HTTPException(status_code=409, detail="preview still in progress")
        if state.status == "error":
            raise HTTPException(status_code=500, detail=state.error)
        return state.result

    @app.get("/api/align/check")
    def align_check() -> dict:
        """Whether `stw align` (PyTom's compiled FRM extension) is actually
        available on this machine -- separate from classification's own PyTom
        check, since FRM needs scripts/compile_pytom_frm.sh, which most PyTom
        installs never run."""
        checks = check_align_installed()
        return {
            "available": all(c.ok for c in checks),
            "checks": [
                {"kind": str(c.requirement.kind), "name": c.requirement.name, "ok": c.ok,
                 "message": c.message, "install_hint": c.requirement.install_hint}
                for c in checks
            ],
        }

    @app.post("/api/align")
    def start_align(body: dict[str, Any]) -> dict:
        try:
            cfg = AlignConfig.model_validate(body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        align_id = uuid.uuid4().hex[:12]
        ALIGNS[align_id] = AlignState(align_id=align_id)
        thread = threading.Thread(target=_execute_align, args=(align_id, cfg), daemon=True)
        thread.start()
        return {"align_id": align_id}

    @app.get("/api/align/{align_id}/events")
    def align_events(align_id: str):
        state = ALIGNS.get(align_id)
        if state is None:
            raise HTTPException(status_code=404, detail="unknown align_id")

        def gen():
            while True:
                item = state.events.get()
                if item is None:
                    final = {
                        "event": "run_complete", "package": "_align",
                        "payload": {"status": state.status, "error": state.error},
                    }
                    yield f"data: {json.dumps(final)}\n\n"
                    break
                yield f"data: {json.dumps(item)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/align/{align_id}/report")
    def align_report(align_id: str) -> dict:
        state = ALIGNS.get(align_id)
        if state is None:
            raise HTTPException(status_code=404, detail="unknown align_id")
        if state.status == "running":
            raise HTTPException(status_code=409, detail="alignment still in progress")
        if state.status == "error":
            raise HTTPException(status_code=500, detail=state.error)
        return state.report

    @app.get("/api/align/{align_id}/preview")
    def align_preview(align_id: str) -> dict:
        """Central-slice global average of the ALIGNED output, same rendering
        as /api/preview -- lets the GUI show a result immediately without the
        user re-pasting the output path into the dataset preview."""
        import base64

        from stw.gui.render import render_volume_slice_png

        state = ALIGNS.get(align_id)
        if state is None or state.report is None or state.report.get("status") != "ok":
            raise HTTPException(status_code=404, detail="no completed alignment for this align_id")
        aligned_dir = state.report["aligned_particle_dir"]
        particles = ParticleSet.discover(aligned_dir, "*.mrc")
        avg = _cached_global_average(particles)
        png_bytes = render_volume_slice_png(avg, title=f"aligned average, n={len(particles.files)}")
        return {
            "n_particles": len(particles.files),
            "preview_png_base64": base64.b64encode(png_bytes).decode("ascii"),
        }

    @app.post("/api/runs")
    def start_run(body: dict[str, Any]) -> dict:
        try:
            cfg = RunConfig.model_validate(body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        run_id = uuid.uuid4().hex[:12]
        # One Event per requested package, created up front -- lets the Cancel
        # button work even for a package still queued behind an earlier one
        # (jobs run strictly sequentially), not just one already mid-subprocess.
        cancel_flags = {pkg: threading.Event() for pkg in cfg.packages}
        RUNS[run_id] = RunState(run_id=run_id, cancel_flags=cancel_flags)
        thread = threading.Thread(target=_execute, args=(run_id, cfg), daemon=True)
        thread.start()
        return {"run_id": run_id, "packages": cfg.packages}

    @app.post("/api/runs/{run_id}/cancel/{package}")
    def cancel_package(run_id: str, package: str) -> dict:
        state = RUNS.get(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="unknown run_id")
        event = state.cancel_flags.get(package)
        if event is None:
            raise HTTPException(status_code=404, detail=f"{package!r} was not part of this run")
        event.set()
        return {"cancelled": package}

    @app.get("/api/runs/{run_id}/events")
    def run_events(run_id: str):
        state = RUNS.get(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="unknown run_id")

        def gen():
            while True:
                item = state.events.get()
                if item is None:
                    final = {
                        "event": "run_complete", "package": "_run",
                        "payload": {"status": state.status, "error": state.error},
                    }
                    yield f"data: {json.dumps(final)}\n\n"
                    break
                yield f"data: {json.dumps(item)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/runs/{run_id}/report")
    def run_report(run_id: str) -> dict:
        state = RUNS.get(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="unknown run_id")
        if state.status == "running":
            raise HTTPException(status_code=409, detail="run still in progress")
        if state.status == "error":
            raise HTTPException(status_code=500, detail=state.error)
        return state.report

    @app.get("/api/runs/{run_id}/comparison.png")
    def comparison_png(run_id: str):
        state = RUNS.get(run_id)
        if state is None or not state.out_dir:
            raise HTTPException(status_code=404, detail="unknown run_id")
        path = Path(state.out_dir) / "comparison" / "cross_package.png"
        if not path.exists():
            raise HTTPException(status_code=404, detail="no comparison figure for this run")
        return FileResponse(path)

    @app.get("/api/runs/{run_id}/panel/{package}/{k}/{seed}")
    def class_average_panel(run_id: str, package: str, k: int, seed: int):
        state = RUNS.get(run_id)
        if state is None or state.report is None:
            raise HTTPException(status_code=404, detail="unknown run_id")
        result = next(
            (r for r in state.report["results"]
             if r["package"] == package and r["k"] == k and r["seed"] == seed),
            None,
        )
        if result is None or not result.get("class_averages"):
            raise HTTPException(status_code=404, detail="no class averages for this job")
        from stw.gui.render import render_class_average_panel
        # Always rendered fresh, never disk-cached by path -- see render.py's module
        # docstring for the real staleness bug this used to have.
        png_bytes = render_class_average_panel(
            result["class_averages"], result["n_per_class"], title=f"{package} k={k} seed={seed}",
        )
        return Response(content=png_bytes, media_type="image/png")

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
