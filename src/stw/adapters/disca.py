"""
DISCA adapter — real DISCA (Deep Iterative Subtomogram Clustering Approach:
a YOPO CNN feature extractor + Gaussian-mixture E-step, iterated), driving
the vendored `torch_disca_run.py` (from the `aitom` toolkit, Xu Lab) inside a
`disca` conda env. Never reimplements the algorithm; input packaging (mask
application + Fourier-crop to DISCA's own 32^3 working regime) is pure
numpy/mrcfile logic done in-process (no conda env needed for that part, the
same "prep needs zero package bindings" pattern already used for RELION/PEET)
— only the actual CNN+EM training/classification runs as a subprocess.

**Always passes `DISCA_FIX_CHANNELS=1`, not left as an opt-in.** The vendored
script's *original* behavior (`np.expand_dims(v, -1)`, channel axis last)
silently treats the spatial box-size axis as the channel count, since
`Conv3d` always reads dim 1 as channels — this only avoided crashing by
coincidence at box=32 (`YOPOFeatureModel`'s first conv layer hardcodes
`in_channels=32` unless the fix is set, in which case it correctly switches
to `in_channels=1`). Since `stw` builds input at whatever box size the
particle set + `--box` cap resolve to (not necessarily exactly 32), the
correct NCDHW shape is required for correctness at all, not just an
improvement — this is the same class of "apply the real fix, don't leave a
known bug as the default" decision already made for EMAN2's `np.int` patch.

**Genuinely unseeded** — DISCA's own training loop never seeds
torch/numpy/CUDA RNGs, so `seed` here is a run index in name only: even two
runs with the *same* `job.seed` value produce different weight
initialization and results, unlike EMAN2/PEET's run-index convention (a
deterministic algorithm, index only for provenance bookkeeping). Every
`(k, seed)` job is therefore an independent training run — there is no
caching benefit to share across seeds; only the mask-dependent input
packaging (Fourier-crop + mask, not seed- or k-dependent) is cached.

**A real, honestly-documented finding, not a plumbing bug**: on `stw`'s own
easy synthetic test fixture (32 particles), DISCA lands at consistently
near-chance ARI across independent runs (verified directly across three
separate unseeded runs) despite each run completing correctly (non-degenerate
cluster sizes, real training loss decreasing). This matches DISCA's own
documented scope: it is designed for large-scale *de novo* structural
discovery across thousands of particles, not fine-grained classification of
a single pre-aligned complex from a handful of particles — a heavily
overparameterized CNN (~1360-channel bottleneck) trained on 32 samples is
expected to struggle, and the source benchmark project's own extensive
results (T4P, T3SS_conf) show DISCA frequently locking onto a contrast/
intensity axis rather than the true structural one even at hundreds of
particles. `stw` does not hide this behind a rosier default; see
`docs/install/disca.md`.

Real runtime observed while validating this adapter: ~65-70s end to end for
the 32-particle, 24^3-box test fixture on a single consumer GPU (well within
this test suite's normal budget) — but the source benchmark project reports
2.5-4.7 **hours** per seed at real dataset scale (500-800 particles, box
80-96). `stw` does not change DISCA's own iteration count (`Config.M = 80`)
to make this faster; a real production run through this adapter should be
expected to take as long as it would take running DISCA directly, and this
is the one adapter in `stw` that should never be part of a default/`--all`
package set given that cost.
"""
from __future__ import annotations

import pickle
import time
from pathlib import Path
from typing import ClassVar

import numpy as np

from stw.adapters.base import Adapter, PlannedStep
from stw.averaging import class_averages
from stw.capabilities import Capabilities
from stw.io.mrc import load_mrc, save_mrc
from stw.io.predictions import write_predictions
from stw.process import conda_run_argv, run_streaming
from stw.progress import NullSink, ProgressSink
from stw.requirements import InstallTier, ReqKind, Requirement
from stw.results import PackageResult
from stw.spec import Job, MaskKind, WedgeKind

_ENV = "disca"
_RESOURCES = Path(__file__).resolve().parent / "resources" / "disca"
_RUNNER = _RESOURCES / "torch_disca_run.py"
_MAX_BOX = 32  # DISCA's own designed working regime (YOPO feature model)
_DEFAULTS = {"batch_size": 64}


def fourier_crop(vol: np.ndarray, out_size: int) -> np.ndarray:
    """Downsample a cubic volume to `out_size`^3 by cropping the centered FFT
    (anti-aliased, no spatial-interpolation artifacts) -- ported verbatim
    (same math, source-verified against the vendored `build_disca_input.py`
    this replaces) since it only needs numpy, not DISCA's own conda env."""
    n = vol.shape[0]
    if out_size == n:
        return vol.astype(np.float32)
    if out_size > n:
        raise ValueError("fourier_crop only downsamples")
    F = np.fft.fftshift(np.fft.fftn(vol))
    c = n // 2
    h = out_size // 2
    Fc = F[c - h : c - h + out_size, c - h : c - h + out_size, c - h : c - h + out_size]
    out = np.fft.ifftn(np.fft.ifftshift(Fc)).real
    out *= (out_size**3) / (n**3)
    return out.astype(np.float32)


def build_disca_input(
    particle_dir: Path, files: list[str], mask: np.ndarray | None, box: int,
) -> dict:
    """Builds the `{'vs': {key: {'v': array, 'm': None, 'id': key}}}` container
    `torch_disca_run.py` expects: mask applied in the particle's native box
    (before cropping, matching the source project's own ordering), Fourier-
    cropped to `box`, per-particle zero-mean/unit-std standardized."""
    vs = {}
    for f in files:
        d = load_mrc(particle_dir / f).astype(np.float32)
        if mask is not None:
            d = d * mask
        v = fourier_crop(d, box)
        v = (v - v.mean()) / (v.std() + 1e-8)
        vs[f] = {"v": v, "m": None, "id": f}
    return {"vs": vs}


class DISCAAdapter(Adapter):
    name = "disca"
    display_name = "DISCA"
    tier = InstallTier.B_CONDA
    algorithm = (
        "A YOPO convolutional feature extractor + Gaussian-mixture-model EM, trained "
        "end to end per run (from the aitom toolkit) — a real deep-learning de novo "
        "discovery method, not a classical distance/PCA approach like the others here."
    )
    requirements = (
        Requirement(
            ReqKind.CONDA_ENV, _ENV,
            install_hint="conda env create -f envs/disca.yml -n disca",
            docs_page="docs/install/disca.md", auto_installable=True, override_key="disca.conda_env",
        ),
        Requirement(
            ReqKind.GPU, "nvidia-smi", optional=True,
            install_hint="an NVIDIA GPU -- DISCA falls back to CPU automatically but real "
            "training is impractically slow on CPU beyond a tiny fixture",
            docs_page="docs/install/disca.md",
        ),
    )
    steps = ("build_input", "train_classify", "collect")
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE}),
        deterministic=False,
        seed_semantics="run_index",
        gpu="optional",
        emits_native_class_averages=False,
        min_particles=8,
    )
    NOTE: ClassVar[str] = (
        "real DISCA (YOPO CNN + Gaussian-mixture EM, aitom toolkit), genuinely unseeded: "
        "torch/numpy/CUDA RNGs are never seeded, so 'seed' is a run index in name only -- "
        "even the same seed value produces a different training run. Designed for large-scale "
        "de novo structural discovery across thousands of particles, not fine classification of "
        "a handful of pre-aligned ones -- expect it to struggle (and sometimes lock onto a "
        "contrast/intensity axis instead of the true structural one) on small datasets. Real "
        "production runs take as long as DISCA itself takes (hours/seed at real dataset scale) "
        "-- never include this in a default/--all package set."
    )

    @classmethod
    def check_installed(cls, *, deep: bool = False):
        report = super().check_installed(deep=deep)
        report.notes.append(cls.NOTE)
        return report

    def _prep_dir(self, job: Job) -> Path:
        return job.cache_dir / f"prep_{job.mask_spec.cache_key()}"

    def plan(self, job: Job) -> list[PlannedStep]:
        prep_dir = self._prep_dir(job)
        return [
            PlannedStep(
                "build_input", ["<in-process>", "build_disca_input"],
                cached=(prep_dir / "disca_input.pickle").exists(),
            ),
            PlannedStep(
                "train_classify", conda_run_argv(_ENV, "python", str(_RUNNER)),
            ),
            PlannedStep("collect", ["<in-process>", "write_predictions"]),
        ]

    def run(self, job: Job, progress: ProgressSink | None = None) -> PackageResult:
        sink = progress or NullSink()
        sink.start_job(self.name, list(self.steps))
        start = time.time()
        try:
            if job.mask_path is None:
                raise ValueError(f"{self.name} requires a mask — got mask.kind=none")

            pkl_path, files = self._ensure_prep(job, sink)
            labels = self._classify(job, sink, pkl_path, files)
            write_predictions(job.predictions_csv, labels)

            sink.step(self.name, "collect", len(self.steps), len(self.steps))
            averages, counts = class_averages(job.particles.particle_dir, labels)
            avg_dir = job.workdir / "class_averages"
            avg_paths = {}
            for cls, vol in averages.items():
                path = avg_dir / f"class_{cls:02d}.mrc"
                save_mrc(path, vol, pixel_size=job.particles.pixel_size)
                avg_paths[cls] = path

            elapsed = time.time() - start
            sink.finish_job(self.name, ok=True, message=f"{elapsed:.1f}s")
            return PackageResult(
                package=self.name, k=job.k, seed=job.seed, status="ok",
                predictions=job.predictions_csv, labels=labels, class_averages=avg_paths,
                n_per_class=counts, elapsed_sec=elapsed, warnings=[self.NOTE],
            )
        except Exception as e:
            sink.finish_job(self.name, ok=False, message=str(e))
            return PackageResult(package=self.name, k=job.k, seed=job.seed, status="failed", error=str(e))

    # --- prep, cached once per particle set + mask (independent of k/seed) ---

    def _ensure_prep(self, job: Job, sink: ProgressSink) -> tuple[Path, list[str]]:
        prep_dir = self._prep_dir(job)
        prep_dir.mkdir(parents=True, exist_ok=True)
        pkl_path = prep_dir / "disca_input.pickle"
        files = list(job.particles.files)

        sink.step(self.name, "build_input", 1, len(self.steps))
        if not pkl_path.exists():
            mask = load_mrc(job.mask_path) if job.mask_path else None
            box = min(_MAX_BOX, job.particles.box)
            data = build_disca_input(job.particles.particle_dir, files, mask, box)
            with pkl_path.open("wb") as f:
                pickle.dump(data, f, protocol=2)
        return pkl_path, files

    def _classify(self, job: Job, sink: ProgressSink, pkl_path: Path, files: list[str]) -> dict[str, int]:
        job.workdir.mkdir(parents=True, exist_ok=True)
        opts = {**_DEFAULTS, **job.options}

        sink.step(self.name, "train_classify", 2, len(self.steps))
        tag = f"seed{job.seed:02d}"
        env = {
            "DISCA_INPUT": str(pkl_path),
            "DISCA_K": str(job.k),
            "DISCA_TAG": tag,
            "DISCA_OUTDIR": str(job.workdir),
            "DISCA_FIX_CHANNELS": "1",
            "DISCA_BATCH_SIZE": str(opts["batch_size"]),
        }
        argv = conda_run_argv(_ENV, "python", str(_RUNNER))
        returncode, _timing = run_streaming(
            argv, package=self.name, cwd=_RESOURCES, log_path=job.log_path, sink=sink, env_extra=env,
        )
        labels_pkl = job.workdir / f"labels_{tag}.pickle"
        if returncode != 0 or not labels_pkl.exists():
            raise RuntimeError(f"DISCA training/classification failed (rc={returncode}); see {job.log_path}")

        with labels_pkl.open("rb") as f:
            raw_labels = list(pickle.load(f))
        if len(raw_labels) != len(files):
            raise RuntimeError(f"DISCA labels {len(raw_labels)} != particle count {len(files)}")
        # DISCA's own labels are 0-indexed; keep consistent with every other adapter's 1-indexed
        # convention.
        return {f: int(lab) + 1 for f, lab in zip(files, raw_labels)}
