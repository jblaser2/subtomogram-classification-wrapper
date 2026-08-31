"""
`stw align`'s only aligner: PyTom's real FRM (Fast Rotational Matching) —
a genuine global SO(3) rotational search (spherical-harmonic correlation,
top-N seeded candidates) plus a joint translational refinement, run to
convergence via PyTom's own real `pytom/bin/FRMAlignment.py` gold-standard
(even/odd, FSC-driven adaptive lowpass) protocol under `mpirun`. Never
reimplements the algorithm — every numerically real step (the SO(3) search
itself, the translational `flcf` search, the FSC/resolution determination,
and the final per-particle pose application via `getTransformedVolume()`)
runs inside real, unmodified PyTom code.

This was chosen over two alternatives after directly reading and testing
both (see ROADMAP.md): STA's own hand-rolled NumPy aligner is local-
refinement-only (61 random candidate rotations within the CURRENT pose's
neighborhood, no global search) and was never validated on genuinely
unaligned data; Dynamo's `dalign` is a real global search too, but every
real attempt at it in the source project crashed on an unresolved bug
inside Dynamo's own compiled table-serialization binary, data-shape-
triggered (unpredictable per dataset), and its one working result never
transferred its poses to any other package.

**A real, hard-won finding about the mask, worth repeating here since it
directly contradicts the intuitive assumption**: the alignment mask must
NOT be the same mask used later for classification. The source benchmark
project tried this once (T3SS_conf) and it silently destroyed the very
signal being classified — the translation search registers every particle
onto whatever's inside the mask, so if that region IS the classification
target, alignment erases the difference between classes rather than just
removing pose jitter. `stw align`'s own mask should be a broader "where is
there real density at all" envelope, not the tight region a downstream
classification step will focus on.

FRM needs a compiled `_swig_frm` extension that most PyTom builds don't
ship with (see `scripts/compile_pytom_frm.sh` — a real compile, not a
config flag) — this is why alignment has its own requirement, checked
separately from the classification adapter's (which never needs it, since
that adapter always runs `-a`/noalign).

A real, machine-specific gotcha found while building this: PyTom's own
`pytom/bin/FRMAlignment.py` does `import pytom_mpi` and (deep inside
`retrieve_res_vols`/`create_average`) `from pytom_volume import ...` —
pre-refactor flat module names that only resolve today via
`pytom.lib.pytom_mpi`/`pytom.lib.pytom_volume`/etc. Worked around in
`resources/pytom/frm_align_runner.py` by aliasing them into `sys.modules`
before running `FRMAlignment`'s own `__main__`, rather than patching
PyTom's own source (the same kind of real cross-version-break shim already
needed for the classification adapter's `Score` issue).

Bandwidth/frequency parameters are box-size sensitive: FRM's spherical-
harmonic transform needs `bw`/`freq` well under the box's own Nyquist
radius or it raises "Inputs' dimensions are wrong!" outright (found by
direct testing at box=24 and box=32) — defaults here scale with box size,
overridable via `options` if a real dataset's box needs different values.

Verified end-to-end on a real, deliberately roughly-misaligned copy of the
tiny test fixture (small random rotation + shift applied per particle, box
24): 4 real iterations, real FSC-based resolution tracking, and the
realigned average's sharpness (voxel std) recovered from 0.136 (rough) to
0.165 — close to the truly-pre-aligned fixture's own 0.168.
"""
from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from pathlib import Path

from stw.adapters.pytom import _mpirun_prefix
from stw.align.config import AlignConfig
from stw.averaging import global_average
from stw.io.mrc import save_mrc
from stw.masks.resolve import resolve_mask
from stw.masks.stats import safe_worker_count
from stw.process import conda_run_argv, run_streaming
from stw.progress import NullSink, ProgressSink
from stw.requirements import CheckResult, ReqKind, Requirement, run_checks
from stw.spec import MaskSpec, ParticleSet, WedgeKind, WedgeSpec

_ENV = "pytom_env"
_RESOURCES = Path(__file__).resolve().parent.parent / "adapters" / "resources" / "pytom"
_STEPS = ("bootstrap_reference", "prep_particle_list", "prep_mask", "align", "apply_poses")

REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        ReqKind.CONDA_ENV, _ENV,
        install_hint="see docs/install/pytom.md -- stw align needs the same pytom_env "
        "PyTom classification already uses",
        docs_page="docs/install/pytom.md",
    ),
    Requirement(
        ReqKind.CONDA_PYTHON_IMPORT, "pytom.lib._swig_frm", detail=_ENV,
        install_hint="run scripts/compile_pytom_frm.sh -- FRM alignment needs a compiled "
        "extension most PyTom builds don't ship with; classification never needs this",
        docs_page="docs/install/pytom.md",
    ),
)


def check_installed() -> list[CheckResult]:
    """Same never-launch-the-package philosophy as Adapter.check_installed() --
    the real preflight check to run before `stw align`, powering `stw check-env`."""
    return run_checks(REQUIREMENTS)


@dataclass
class AlignReport:
    status: str  # "ok" | "failed"
    aligned_particle_dir: Path | None = None
    n_particles: int = 0
    elapsed_sec: float | None = None
    poses_csv: Path | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "aligned_particle_dir": str(self.aligned_particle_dir) if self.aligned_particle_dir else None,
            "n_particles": self.n_particles,
            "elapsed_sec": self.elapsed_sec,
            "poses_csv": str(self.poses_csv) if self.poses_csv else None,
            "warnings": self.warnings,
            "error": self.error,
        }


def _default_options(box: int) -> dict:
    bw_low = 4
    bw_high = max(bw_low + 2, min(box // 3, 16))
    freq = max(4, min(box // 4, bw_high))
    return {
        "peak_offset": max(4, box // 4),
        "bw_low": bw_low,
        "bw_high": bw_high,
        "freq": freq,
        "max_iter": 4,
    }


def _wedge_angle(wedge: WedgeSpec) -> float:
    """Missing-wedge half-angle PyTom's SingleTiltWedge expects (degrees from
    90) -- same convention as the classification adapter's own _wedge_angle,
    duplicated rather than reused since that one takes a classification Job,
    not this module's own AlignJob-shaped state."""
    if wedge.kind == WedgeKind.UNIFORM and wedge.tilt_min is not None and wedge.tilt_max is not None:
        max_tilt = (abs(wedge.tilt_min) + abs(wedge.tilt_max)) / 2
        return max(0.0, 90.0 - max_tilt)
    return 0.0


def _conda(cmd: list[str], cwd: Path, log_path: Path, sink: ProgressSink, package: str = "align") -> None:
    argv = conda_run_argv(_ENV, *cmd)
    returncode, _timing = run_streaming(argv, package=package, cwd=cwd, log_path=log_path, sink=sink)
    if returncode != 0:
        raise RuntimeError(f"stw align step failed (rc={returncode}): {' '.join(cmd)} — see {log_path}")


def _latest_aligned_pl(dest: Path) -> Path | None:
    xmls = sorted(
        dest.glob("aligned_pl_iter*.xml"),
        key=lambda p: int(p.stem.replace("aligned_pl_iter", "")),
    )
    return xmls[-1] if xmls else None


def run_pytom_alignment(config: AlignConfig, progress: ProgressSink | None = None) -> AlignReport:
    sink = progress or NullSink()
    sink.start_job("align", list(_STEPS))
    start = time.time()
    out_dir = Path(config.out_dir).resolve()
    try:
        particles = ParticleSet.discover(config.particles, config.pattern, config.pixel_size)

        mask_spec = MaskSpec(
            kind=config.mask.kind, path=config.mask.path, center=config.mask.center,
            radius=config.mask.radius, half_height=config.mask.half_height, axis=config.mask.axis,
            edge=config.mask.edge,
        )
        wedge_spec = WedgeSpec(
            kind=config.wedge.kind, tilt_min=config.wedge.tilt_min, tilt_max=config.wedge.tilt_max,
            tilt_axis=config.wedge.tilt_axis, table=config.wedge.table,
        )

        cache_root = out_dir / "_cache" / particles.fingerprint()
        mask_path = resolve_mask(mask_spec, particles, cache_root)
        if mask_path is None:
            raise ValueError("stw align requires a mask (mask.kind=none is not allowed)")

        work = out_dir / "work"
        logs = work / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        opts = {**_default_options(particles.box), **config.options}

        sink.step("align", "bootstrap_reference", 1, len(_STEPS))
        ref_mrc = work / "ref_0.mrc"
        if not ref_mrc.exists():
            avg = global_average(particles.particle_dir, list(particles.files))
            save_mrc(ref_mrc, avg, pixel_size=particles.pixel_size)
        ref_em = work / "ref_0.em"
        mask_em = work / "mask.em"
        if not ref_em.exists():
            _conda(["python", str(_RESOURCES / "convert_mask.py"), str(ref_mrc), str(ref_em)],
                   work, logs / "convert_ref.log", sink)
        if not mask_em.exists():
            _conda(["python", str(_RESOURCES / "convert_mask.py"), str(mask_path), str(mask_em)],
                   work, logs / "convert_mask.log", sink)

        sink.step("align", "prep_particle_list", 2, len(_STEPS))
        wedge_angle = _wedge_angle(wedge_spec)
        plist = work / "particle_list.xml"
        if not plist.exists():
            _conda(
                ["python", str(_RESOURCES / "generate_particle_list.py"),
                 "--input_dir", str(particles.particle_dir), "--pattern", particles.pattern,
                 "--output", str(plist), "--wedge_angle", str(wedge_angle)],
                work, logs / "particle_list.log", sink,
            )

        sink.step("align", "prep_mask", 3, len(_STEPS))
        dest = work / "dest"
        dest.mkdir(exist_ok=True)
        job_xml = work / "frm_job.xml"
        _conda(
            ["python", str(_RESOURCES / "build_frm_job.py"),
             "--particle_list", str(plist), "--reference", str(ref_em), "--mask", str(mask_em),
             "--pixel_size", str(particles.pixel_size), "--peak_offset", str(opts["peak_offset"]),
             "--bw_low", str(opts["bw_low"]), "--bw_high", str(opts["bw_high"]),
             "--freq", str(opts["freq"]), "--max_iter", str(opts["max_iter"]),
             "--destination", str(dest), "--output", str(job_xml)],
            work, logs / "build_frm_job.log", sink,
        )

        sink.step("align", "align", 4, len(_STEPS))
        # By far the most expensive step (a real MPI-parallel iterative search) -- unlike
        # classification's per-(k,seed) cache_dir, a bare re-run of `stw align` on the exact
        # same config has nothing that should ever change, so skip it outright if a prior
        # run already left a completed alignment in `dest` (found via direct testing: without
        # this, a plain re-invocation silently repeated the full ~20s+ MPI search every time).
        aligned_pl = _latest_aligned_pl(dest)
        if aligned_pl is None:
            np_ranks = safe_worker_count(mask_path, tiers=(4, 8, 16)) + 1  # +1: rank 0 only coordinates
            argv = [*_mpirun_prefix(str(np_ranks)), "python", str(_RESOURCES / "frm_align_runner.py"),
                    "-j", str(job_xml), "-v"]
            _conda(argv, work, work / "align.log", sink)
            aligned_pl = _latest_aligned_pl(dest)
        if aligned_pl is None:
            raise RuntimeError(f"FRM alignment produced no aligned_pl_iter*.xml; see {work / 'align.log'}")

        sink.step("align", "apply_poses", 5, len(_STEPS))
        aligned_dir = out_dir / "aligned_particles"
        poses_csv = out_dir / "poses.csv"
        _conda(
            ["python", str(_RESOURCES / "apply_frm_poses.py"),
             "--particle_list", str(aligned_pl), "--output_dir", str(aligned_dir),
             "--poses_csv", str(poses_csv), "--pixel_size", str(particles.pixel_size)],
            work, logs / "apply_poses.log", sink,
        )

        n_particles = sum(1 for _ in csv.DictReader(poses_csv.open())) if poses_csv.exists() else 0
        elapsed = time.time() - start
        sink.finish_job("align", ok=True, message=f"{elapsed:.1f}s")
        return AlignReport(
            status="ok", aligned_particle_dir=aligned_dir, n_particles=n_particles,
            elapsed_sec=elapsed, poses_csv=poses_csv,
            warnings=["FRM alignment is a real global search but was refined here starting "
                      "from a plain unweighted average -- check the aligned class averages "
                      "visually before trusting downstream classification results"],
        )
    except Exception as e:
        sink.finish_job("align", ok=False, message=str(e))
        return AlignReport(status="failed", error=str(e))
