"""
Shared machinery for `mode: preview` adapters: each one shells out to a
vendored, dependency-free script (see `adapters/resources/`) with the current
Python interpreter — the same one running `stw` itself, since these scripts
need nothing beyond stw's own numpy/scipy/scikit-learn/mrcfile — rather than
importing their internals, so a preview adapter genuinely wraps an existing
script the same way a native adapter wraps a package's own launcher.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from stw.adapters.base import PlannedStep
from stw.averaging import class_averages
from stw.io.mrc import save_mrc
from stw.io.predictions import read_legacy_predictions, write_predictions
from stw.process import run_streaming
from stw.progress import NullSink, ProgressSink
from stw.results import PackageResult
from stw.spec import Job

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"


def script_path(filename: str) -> Path:
    return RESOURCES_DIR / filename


def plan_script_run(package: str, script: str, job: Job, extra_argv: list[str]) -> list[PlannedStep]:
    argv = _base_argv(script, job) + extra_argv
    return [PlannedStep(name="classify", argv=argv, cached=False)]


def _base_argv(script: str, job: Job) -> list[str]:
    argv = [
        sys.executable, str(script_path(script)),
        "--data", str(job.particles.particle_dir),
        "--glob", job.particles.pattern,
        "--mask", str(job.mask_path),
        "--k", str(job.k),
        "--apix", str(job.particles.pixel_size),
        "--out", str(job.workdir / "legacy_predictions.csv"),
    ]
    return argv


def run_script_job(
    package: str, script: str, job: Job, extra_argv: list[str], progress: ProgressSink | None = None
) -> PackageResult:
    sink = progress or NullSink()
    sink.start_job(package, ["classify"])
    start = time.time()
    try:
        if job.mask_path is None:
            raise ValueError(f"{package} (preview mode) requires a mask — got mask.kind=none")

        argv = _base_argv(script, job) + extra_argv
        job.workdir.mkdir(parents=True, exist_ok=True)
        returncode, timing = run_streaming(
            argv, package=package, log_path=job.log_path, sink=sink,
        )
        if returncode != 0:
            raise RuntimeError(f"{script} exited with code {returncode} — see {job.log_path}")

        legacy_csv = job.workdir / "legacy_predictions.csv"
        labels = read_legacy_predictions(legacy_csv)
        write_predictions(job.predictions_csv, labels)

        averages, counts = class_averages(job.particles.particle_dir, labels)
        avg_dir = job.workdir / "class_averages"
        avg_paths = {}
        for cls, vol in averages.items():
            path = avg_dir / f"class_{cls:02d}.mrc"
            save_mrc(path, vol, pixel_size=job.particles.pixel_size)
            avg_paths[cls] = path

        elapsed = time.time() - start
        sink.finish_job(package, ok=True, message=f"{elapsed:.1f}s")
        return PackageResult(
            package=package, k=job.k, seed=job.seed, status="ok",
            predictions=job.predictions_csv, labels=labels, class_averages=avg_paths,
            n_per_class=counts, elapsed_sec=elapsed, log=job.log_path,
        )
    except Exception as e:
        sink.finish_job(package, ok=False, message=str(e))
        return PackageResult(package=package, k=job.k, seed=job.seed, status="failed", error=str(e))
