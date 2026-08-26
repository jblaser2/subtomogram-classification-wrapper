"""
EMAN2 adapter — real EMAN2 (`e2spt_average.py`, `e2refine_postprocess.py`,
`e2spt_pcasplit.py`), run inside a conda env named `eman2`. Never
reimplements the algorithm; only builds EMAN2's own project format and
parses its own output. `e2spt_pcasplit.py`'s classifier is PCA (Fourier-
domain, package-native) + scikit-learn KMeans; EMAN2 exposes no
`random_state` on its own CLI, so "seed" here is a run index, not a true RNG
seed.

Prep (cached once per particle set + mask under `job.cache_dir`, shared
across every k/seed in a run): patch the installed `e2spt_pcasplit.py`
(fixes a `np.int` deprecation that breaks it on modern numpy — required just
to run, applied idempotently, matches EMAN2's own upstream behavior
otherwise), ingest particles into EMAN2's HDF/LST project format, build a
no-alignment consensus average + gold-standard FSC/mask (identity poses —
`stw` assumes pre-aligned input, see docs/limitations.md), and convert the
resolved mask to `.hdf`.

Per (k, seed): one `e2spt_pcasplit.py` call, writing a new `sptcls_NN/`
directory each time; predictions are parsed from its `ptcls_clsNN.lst`
files. Class averages are computed by `stw`'s own generic averaging (not
EMAN2's own per-class gold-standard refinement) so every adapter's output is
directly comparable.

Defaults (`nbasis=12`, `maxres=60` Å, `restarget=30` Å) were validated in the
source project for ~13 Å/px, 80-voxel-box data — override via
`package_options.eman2` for very different pixel-size/box-size regimes.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import ClassVar

from stw.adapters.base import Adapter, PlannedStep
from stw.averaging import class_averages
from stw.capabilities import Capabilities
from stw.io.mrc import save_mrc
from stw.io.predictions import write_predictions
from stw.process import conda_run_argv, run_streaming
from stw.progress import NullSink, ProgressSink
from stw.requirements import InstallTier, ReqKind, Requirement
from stw.results import PackageResult
from stw.spec import Job, MaskKind, WedgeKind

_ENV = "eman2"
_RESOURCES = Path(__file__).resolve().parent / "resources" / "eman2"
_DEFAULTS = {"nbasis": 12, "maxres": 60.0, "restarget": 30.0, "sym": "c1", "clean": False}


def parse_lst(lst_path: str | Path) -> list[int]:
    """EMAN2 fast-LST format: 3 header lines (#LSX / comment / '# <linelen>'),
    then '<idx>\\t<hdf>\\t{dict}' fixed-width lines. Returns the particle
    indices (into the original ingested particles.hdf/ptcls.lst, in ingest
    order) listed in this class's .lst file."""
    idxs = []
    with open(lst_path) as f:
        lines = f.readlines()
    for line in lines[3:]:
        line = line.strip()
        if not line:
            continue
        idxs.append(int(line.split()[0]))
    return idxs


class EMAN2Adapter(Adapter):
    name = "eman2"
    display_name = "EMAN2"
    tier = InstallTier.B_CONDA
    algorithm = "Fourier-space PCA + k-means (e2spt_pcasplit.py)."
    requirements = (
        Requirement(
            ReqKind.CONDA_ENV, _ENV,
            install_hint="conda create -n eman2 -c cryoem -c conda-forge eman-dev",
            docs_page="docs/install/eman2.md", auto_installable=True, override_key="eman2.conda_env",
        ),
    )
    steps = ("patch", "ingest", "consensus_average", "postprocess", "mask_convert", "classify", "collect")
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE}),
        deterministic=False,
        seed_semantics="run_index",
        gpu="unused",
        emits_native_class_averages=False,
        min_particles=8,
    )
    NOTE: ClassVar[str] = (
        "real EMAN2, but classification-only: identity poses (no alignment search), no "
        "missing-wedge fill (matches this project's validated defaults). "
        "'seed' is a run index, not a true RNG seed — EMAN2's own CLI exposes no random_state."
    )

    @classmethod
    def check_installed(cls, *, deep: bool = False):
        report = super().check_installed(deep=deep)
        report.notes.append(cls.NOTE)
        return report

    def plan(self, job: Job) -> list[PlannedStep]:
        opts = {**_DEFAULTS, **job.options}
        prep_dir = job.cache_dir
        steps = [
            PlannedStep("patch", conda_run_argv(_ENV, "python", str(_RESOURCES / "patch_scripts.py"))),
            PlannedStep(
                "ingest", conda_run_argv(_ENV, "python", str(_RESOURCES / "make_project.py")),
                cached=(prep_dir / "particles.hdf").exists(),
            ),
            PlannedStep(
                "consensus_average",
                conda_run_argv(_ENV, "e2spt_average.py", "--path", "spt_noalign", "--iter", "1"),
                cached=(prep_dir / "spt_noalign" / "threed_01_even.hdf").exists(),
            ),
            PlannedStep(
                "postprocess",
                conda_run_argv(_ENV, "e2refine_postprocess.py", "--output", "spt_noalign/threed_01.hdf"),
                cached=(prep_dir / "spt_noalign" / "threed_01.hdf").exists(),
            ),
            PlannedStep(
                "mask_convert", conda_run_argv(_ENV, "python", str(_RESOURCES / "convert_mask.py")),
                cached=(prep_dir / self._mask_name(job)).exists(),
            ),
            PlannedStep(
                "classify",
                conda_run_argv(
                    _ENV, "e2spt_pcasplit.py", "--path", "spt_noalign", "--nclass", str(job.k),
                    "--nbasis", str(opts["nbasis"]), "--mask", self._mask_name(job),
                ),
            ),
        ]
        return steps

    @staticmethod
    def _mask_name(job: Job) -> str:
        # Keyed on the mask's own content hash: a stale standard_mask.hdf would
        # otherwise survive a mask change across separate `stw run` invocations
        # sharing the same out_dir (caught during real-adapter testing on PyTom's
        # equivalent mask.em, same underlying bug).
        return f"standard_mask_{job.mask_spec.cache_key()}.hdf"

    def run(self, job: Job, progress: ProgressSink | None = None) -> PackageResult:
        sink = progress or NullSink()
        sink.start_job(self.name, list(self.steps))
        start = time.time()
        try:
            if job.mask_path is None:
                raise ValueError(f"{self.name} requires a mask — got mask.kind=none")

            opts = {**_DEFAULTS, **job.options}
            prep_dir = self._ensure_prep(job, sink, opts)
            labels = self._classify(job, sink, prep_dir, opts)
            write_predictions(job.predictions_csv, labels)

            sink.step(self.name, "collect", 7, len(self.steps))
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

    # --- prep, cached once per particle set + mask -------------------------

    def _ensure_prep(self, job: Job, sink: ProgressSink, opts: dict) -> Path:
        prep_dir = job.cache_dir
        prep_dir.mkdir(parents=True, exist_ok=True)
        logs = prep_dir / "prep_logs"
        logs.mkdir(exist_ok=True)
        threads = str(opts.get("threads") or min(os.cpu_count() or 4, 8))
        sym = str(opts["sym"])

        sink.step(self.name, "patch", 1, len(self.steps))
        self._conda(["python", str(_RESOURCES / "patch_scripts.py")], prep_dir, logs / "patch.log", sink)

        sink.step(self.name, "ingest", 2, len(self.steps))
        if not all((prep_dir / f).exists() for f in ("particles.hdf", "ptcls.lst", "initial_ref.hdf")):
            self._conda(
                ["python", str(_RESOURCES / "make_project.py")], prep_dir, logs / "ingest.log", sink,
                env_extra={
                    "EMAN2_PARTICLES_DIR": str(job.particles.particle_dir),
                    "EMAN2_GLOB": job.particles.pattern,
                    "EMAN2_APIX": str(job.particles.pixel_size),
                },
            )

        cons = prep_dir / "spt_noalign"
        cons_map = cons / "threed_01.hdf"
        cons_mask = cons / "mask_tight.hdf"
        cons_parms = cons / "particle_parms_01.json"

        sink.step(self.name, "consensus_average", 3, len(self.steps))
        if not all(p.exists() for p in (cons_map, cons_mask, cons_parms)):
            cons.mkdir(exist_ok=True)
            self._conda(
                ["python", str(_RESOURCES / "make_identity_parms.py"), "ptcls.lst",
                 "spt_noalign/particle_parms_01.json"],
                prep_dir, logs / "identity_parms.log", sink,
            )
            self._conda(
                ["e2spt_average.py", "--path", "spt_noalign", "--iter", "1", "--sym", sym,
                 "--keep", "1.0", "--threads", threads, "--skippostp", "--verbose", "1"],
                prep_dir, logs / "average.log", sink,
            )
            sink.step(self.name, "postprocess", 4, len(self.steps))
            self._conda(
                ["e2refine_postprocess.py", "--even", "spt_noalign/threed_01_even.hdf",
                 "--odd", "spt_noalign/threed_01_odd.hdf", "--output", "spt_noalign/threed_01.hdf",
                 "--iter", "1", "--tomo", "--mass", "-1", "--threads", threads,
                 "--restarget", str(opts["restarget"]), "--sym", sym, "--align"],
                prep_dir, logs / "postprocess.log", sink,
            )
        else:
            sink.step(self.name, "postprocess", 4, len(self.steps))

        sink.step(self.name, "mask_convert", 5, len(self.steps))
        mask_hdf = prep_dir / self._mask_name(job)
        if not mask_hdf.exists():
            self._conda(
                ["python", str(_RESOURCES / "convert_mask.py"), str(job.mask_path), str(mask_hdf)],
                prep_dir, logs / "mask_convert.log", sink,
            )

        return prep_dir

    def _classify(self, job: Job, sink: ProgressSink, prep_dir: Path, opts: dict) -> dict[str, int]:
        before = {p.name for p in prep_dir.glob("sptcls_*")}
        argv = [
            "e2spt_pcasplit.py", "--path", "spt_noalign", "--iter", "1",
            "--nclass", str(job.k), "--nbasis", str(opts["nbasis"]), "--maxres", str(opts["maxres"]),
            "--sym", str(opts["sym"]), "--mask", self._mask_name(job), "--nowedgefill", "--verbose", "1",
        ]
        if opts.get("clean"):
            argv.append("--clean")
        env_extra = {"EMAN2_PERPARTICLE_NORM": "1"} if opts.get("perparticle_norm") else None

        sink.step(self.name, "classify", 6, len(self.steps))
        job.workdir.mkdir(parents=True, exist_ok=True)
        self._conda(argv, prep_dir, job.log_path, sink, env_extra=env_extra)

        after = {p.name for p in prep_dir.glob("sptcls_*")}
        new = sorted(after - before)
        if not new:
            raise RuntimeError(f"e2spt_pcasplit produced no new sptcls_XX dir; see {job.log_path}")
        sptcls = prep_dir / new[-1]

        files = job.particles.files  # sorted at ingest time via the same sorted-glob order
        labels: dict[str, int] = {}
        for lst in sorted(sptcls.glob("ptcls_cls*.lst")):
            label = int(lst.stem.replace("ptcls_cls", ""))
            for idx in parse_lst(lst):
                labels[files[idx]] = label
        if not labels:
            raise RuntimeError(f"no particles parsed from {sptcls}; see {job.log_path}")
        return labels

    @staticmethod
    def _conda(cmd: list[str], cwd: Path, log_path: Path, sink: ProgressSink, env_extra: dict | None = None) -> None:
        argv = conda_run_argv(_ENV, *cmd)
        returncode, _timing = run_streaming(
            argv, package="eman2", cwd=cwd, log_path=log_path, sink=sink, env_extra=env_extra,
        )
        if returncode != 0:
            raise RuntimeError(f"EMAN2 step failed (rc={returncode}): {' '.join(cmd)} — see {log_path}")
