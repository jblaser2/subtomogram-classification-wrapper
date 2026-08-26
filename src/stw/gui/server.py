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


RUNS: dict[str, RunState] = {}


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


def _build_preview_mask(mask_body: dict[str, Any], particles: ParticleSet) -> np.ndarray:
    """Builds a mask straight from the mask primitives (build_sphere/build_cylinder/
    auto_sphere_mask/load_mrc), not resolve_mask() -- this is a throwaway preview with
    no run/cache_dir to key a cached mask file under, and shouldn't write one."""
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
        if mask_body.get("radius") is None:
            raise HTTPException(status_code=422, detail="mask kind=sphere requires radius")
        return build_sphere(shape, center, float(mask_body["radius"]), edge)
    if kind == "cylinder":
        if mask_body.get("radius") is None or mask_body.get("half_height") is None:
            raise HTTPException(status_code=422, detail="mask kind=cylinder requires radius and half_height")
        axis = mask_body.get("axis", "z")
        return build_cylinder(shape, center, float(mask_body["radius"]), float(mask_body["half_height"]), axis, edge)
    if kind == "auto":
        mask, _center, _radius = auto_sphere_mask(particles)
        return mask
    if kind == "file":
        if not mask_body.get("path"):
            raise HTTPException(status_code=422, detail="mask kind=file requires path")
        try:
            mask = load_mrc(mask_body["path"])
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"could not load mask file: {e}") from e
        if mask.shape != shape:
            raise HTTPException(
                status_code=422, detail=f"mask file shape {mask.shape} != particle box {shape}"
            )
        return mask
    raise HTTPException(status_code=422, detail="mask kind=none has no mask to preview")


def _execute(run_id: str, cfg: RunConfig) -> None:
    state = RUNS[run_id]
    sink = QueueProgressSink(state.events)
    try:
        report = run_config(cfg, progress=sink)
        state.report = asdict(report)
        state.out_dir = str(cfg.out_dir)
        state.status = "done"
    except Exception as e:  # noqa: BLE001 - surfaced to the UI, not swallowed
        state.status = "error"
        state.error = str(e)
    finally:
        state.events.put(None)  # sentinel: tells the SSE generator the run is over


def create_app():
    from fastapi import FastAPI, HTTPException
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
        """Loads the particle set (no run started) and returns its specs plus a
        central-slice PNG of the unweighted global average, so a config can be
        sanity-checked before committing to a full run."""
        import base64

        from stw.gui.render import render_volume_slice_png

        particles = _discover_particles(body)
        avg = global_average(particles.particle_dir, list(particles.files))
        png_bytes = render_volume_slice_png(avg, title=f"global average, n={len(particles.files)}")
        return {
            "n_particles": len(particles.files),
            "box": particles.box,
            "pixel_size": particles.pixel_size,
            "preview_png_base64": base64.b64encode(png_bytes).decode("ascii"),
        }

    @app.post("/api/preview-mask")
    def preview_mask(body: dict[str, Any]) -> dict:
        """Same particle-set load as /api/preview, plus builds the mask straight
        from the current form's mask.* fields (never resolve_mask() -- there's no
        run/cache_dir here) and overlays it as a semi-transparent color fill on the
        same central-slice global average."""
        import base64

        from stw.gui.render import render_mask_overlay_png

        particles = _discover_particles(body)
        mask = _build_preview_mask(body.get("mask") or {}, particles)
        avg = global_average(particles.particle_dir, list(particles.files))
        png_bytes = render_mask_overlay_png(avg, mask, title=f"mask preview, n={len(particles.files)}")
        return {
            "n_particles": len(particles.files),
            "box": particles.box,
            "pixel_size": particles.pixel_size,
            "preview_png_base64": base64.b64encode(png_bytes).decode("ascii"),
        }

    @app.post("/api/runs")
    def start_run(body: dict[str, Any]) -> dict:
        try:
            cfg = RunConfig.model_validate(body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        run_id = uuid.uuid4().hex[:12]
        RUNS[run_id] = RunState(run_id=run_id)
        thread = threading.Thread(target=_execute, args=(run_id, cfg), daemon=True)
        thread.start()
        return {"run_id": run_id}

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
        out_png = Path(state.out_dir) / package / f"k{k}" / f"seed{seed:02d}" / "class_average_panel.png"
        if not out_png.exists():
            from stw.gui.render import render_class_average_panel
            render_class_average_panel(
                result["class_averages"], result["n_per_class"], out_png,
                title=f"{package} k={k} seed={seed}",
            )
        return FileResponse(out_png)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
