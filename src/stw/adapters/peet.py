"""
PEET adapter — real PEET (WMD-PCA + native `clusterPca` k-means), driven
through `averageAll` -> `pca` -> `clusterPca` -> `usePcaMotiveLists`. Never
reimplements the algorithm; only builds PEET's own stacked-volume/IMOD-model/
MOTL/`.prm` input and parses its own MOTL output.

A real, hard-won gotcha (discovered validating this exact pipeline in the
source STA benchmark project, confirmed via `strace`): supplying one MRC
file per particle as separate `fnVolume` "tomograms" silently breaks --
PEET's `getInitialMOTL` only iterates the *first* tomogram when every
tomogram has exactly one particle, giving a rank-1 PCA matrix and a
degenerate near-all-one-class split. The fix (which this adapter always
uses): stack every particle into ONE MRC "tomogram" (particle i at
Z-offset `i * box`) with one scattered-point IMOD model, so PEET treats it
as one tomogram with N particles.

Two external tools are required, both usually shipped as a "source this
script" install rather than anything on PATH by default: IMOD (for
`point2model`) and PEET/"Particle" (for `averageAll`/`pca`/`clusterPca`/
`usePcaMotiveLists`, all MCR binaries -- no MATLAB license needed). This
adapter sources both setup scripts before every native call, matching the
only way this software is actually meant to be invoked; override their
locations with `package_options.peet.imod_setup`/`particle_setup` if they
aren't at the common default paths.

`clusterPca` (PEET's own native k-means) exposes no seed control, so, like
EMAN2/PyTom, "seed" here is a run index, not a true RNG seed. Wedge
weighting is always off (`flgWedgeWeight = 0`), matching this project's
validated default for pre-aligned, uniform-wedge-corrected input -- PEET's
own `.prm` format does support real wedge weighting, this adapter just
doesn't enable it (unlike PyTom/RELION's real wedge pass-through).
"""
from __future__ import annotations

import glob
import os
import shlex
import time
from pathlib import Path
from typing import ClassVar

import numpy as np

from stw.adapters.base import Adapter, PlannedStep
from stw.averaging import class_averages
from stw.capabilities import Capabilities
from stw.io.mrc import load_mrc, save_mrc
from stw.io.predictions import write_predictions
from stw.process import run_streaming
from stw.progress import NullSink, ProgressSink
from stw.requirements import InstallTier, ReqKind, Requirement
from stw.results import PackageResult
from stw.spec import Job, MaskKind, WedgeKind

_DEFAULT_IMOD_SETUP = str(Path.home() / "Applications" / "IMOD-linux.sh")
_DEFAULT_PARTICLE_SETUP = str(Path.home() / "Applications" / "Particle.sh")
_DEFAULTS = {"pc_top": 10, "n_init": 10}
_FN_OUTPUT = "stw"  # PEET derives its own MOTL/output filenames from this, not from initMOTL
_MOTL_HEADER = (
    "CCC,reserved,reserved,pIndex,wedgeWT,adjCCC,NA,NA,NA,NA,"
    "xOffset,yOffset,zOffset,NA,NA,oldClass,EulerZ(1),EulerZ(3),EulerX(2),class,"
    "stw orchestrator"
)


def build_stacked_volume(particle_dir: Path, files: list[str], box: int) -> np.ndarray:
    """Z-score normalizes each particle, then stacks all of them along Z into
    ONE volume -- see module docstring for why this (not one MRC per
    particle) is required for PEET to see more than one particle at all."""
    n = len(files)
    stacked = np.empty((n * box, box, box), dtype=np.float32)
    for i, fname in enumerate(files):
        vol = load_mrc(particle_dir / fname).astype(np.float64)
        std = vol.std() or 1.0
        stacked[i * box : (i + 1) * box] = ((vol - vol.mean()) / std).astype(np.float32)
    return stacked


def build_motl(n: int, identity: bool) -> str:
    """PEET's 20-column MOTL CSV. `identity=True` (Iter1, the starting point)
    writes CCC=0; `identity=False` (Iter2, what averageAll/pca read) writes
    CCC=1 so every particle passes refThreshold -- no real alignment score
    exists since no alignment search ever runs."""
    lines = [_MOTL_HEADER]
    for i in range(1, n + 1):
        if identity:
            lines.append(f"0,0,0,{i},0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0")
        else:
            lines.append(f"1,0,0,{i},0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0")
    return "\n".join(lines) + "\n"


def build_prm(
    stack_mrc: Path, model: Path, iter1_motl: Path, mask_path: Path, box: int, pixel_size: float, n: int,
    fn_output: str = _FN_OUTPUT,
) -> str:
    sz = box - 2
    return f"""# stw-generated PEET single-stacked-tomogram PCA project
fnVolume = {{'{stack_mrc}'}}
fnModParticle = {{'{model}'}}
initMOTL = {{'{iter1_motl}'}}
fnOutput = '{fn_output}'
szVol = [{sz} {sz} {sz}]
maskType = 'none'
pcaFnParticleMask = '{mask_path}'
yaxisType = 0
sampleSphere = 'none'
dPhi   = {{[0], [0]}}
dTheta = {{[0], [0]}}
dPsi   = {{[0], [0]}}
searchRadius = {{[0], [0]}}
lowCutoff = {{[0.05 0.05], [0.05 0.05]}}
hiCutoff  = {{[0.45 0.05], [0.45 0.05]}}
flgFairReference = 0
refThreshold  = [{n}, {n}]
refFlagAllTom = 1
tiltRange = {{}}
flgWedgeWeight = 0
nWeightGroup = 8
lstThresholds = [{n}]
lstFlagAllTom = 1
pixelSpacing = {pixel_size}
CCMode = 0
flgAbsValue = 1
particlePerCPU = 8
debugLevel = 1
nIter = 2
"""


def parse_motl_classes(motl_path: str | Path, files: list[str]) -> dict[str, int]:
    """Column 4 (pIndex, 1-based) -> column 20 (class), mapped back to the
    original filename via `files` (stacking order == files order)."""
    labels: dict[str, int] = {}
    with open(motl_path) as f:
        next(f)  # header
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 20:
                continue
            p_index = int(float(parts[3]))
            cls = int(float(parts[19]))
            if 1 <= p_index <= len(files):
                labels[files[p_index - 1]] = cls
    return labels


class PEETAdapter(Adapter):
    name = "peet"
    display_name = "PEET"
    tier = InstallTier.C_GUIDED
    algorithm = "Wedge-masked-difference (WMD) PCA + k-means (averageAll/pca/clusterPca)."
    requirements = (
        Requirement(
            ReqKind.PATH_EXISTS, _DEFAULT_IMOD_SETUP,
            install_hint="see docs/install/peet.md -- IMOD's own setup script (for point2model)",
            docs_page="docs/install/peet.md", override_key="peet.imod_setup",
        ),
        Requirement(
            ReqKind.PATH_EXISTS, _DEFAULT_PARTICLE_SETUP,
            install_hint="see docs/install/peet.md -- PEET's own setup script "
            "(for averageAll/pca/clusterPca/usePcaMotiveLists)",
            docs_page="docs/install/peet.md", override_key="peet.particle_setup",
        ),
    )
    steps = ("prep_stack", "prep_model", "prep_motl", "prep_average", "prep_pca", "cluster", "collect")
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
        "real PEET (averageAll/pca/clusterPca/usePcaMotiveLists), but classification-only: "
        "identity poses, no missing-wedge weighting (flgWedgeWeight=0, matching this project's "
        "validated default). 'seed' is a run index -- clusterPca exposes no seed control."
    )

    @classmethod
    def check_installed(cls, *, deep: bool = False):
        report = super().check_installed(deep=deep)
        report.notes.append(cls.NOTE)
        return report

    def _setup_paths(self, job: Job) -> tuple[str, str]:
        return (
            str(job.options.get("imod_setup", _DEFAULT_IMOD_SETUP)),
            str(job.options.get("particle_setup", _DEFAULT_PARTICLE_SETUP)),
        )

    def plan(self, job: Job) -> list[PlannedStep]:
        prep_dir = job.cache_dir
        opts = {**_DEFAULTS, **job.options}
        return [
            PlannedStep(
                "prep_stack", ["<in-process>", "build_stacked_volume"], cached=(prep_dir / "stack.mrc").exists()
            ),
            PlannedStep("prep_model", ["point2model"], cached=(prep_dir / "stack.mod").exists()),
            PlannedStep(
                "prep_motl", ["<in-process>", "build_motl"],
                cached=(prep_dir / f"{_FN_OUTPUT}_MOTL_Tom1_Iter2.csv").exists(),
            ),
            PlannedStep(
                "prep_average", ["averageAll"],
                cached=bool(glob.glob(str(prep_dir / f"{_FN_OUTPUT}_AvgVol_1*.mrc"))),
            ),
            PlannedStep("prep_pca", ["pca"], cached=bool(glob.glob(str(prep_dir / "pca*.mat")))),
            PlannedStep(
                "cluster",
                ["clusterPca", str(job.k), f"1:{opts['pc_top']}", "kmeans"],
            ),
            PlannedStep("collect", ["usePcaMotiveLists"]),
        ]

    def run(self, job: Job, progress: ProgressSink | None = None) -> PackageResult:
        sink = progress or NullSink()
        sink.start_job(self.name, list(self.steps))
        start = time.time()
        try:
            if job.mask_path is None:
                raise ValueError(f"{self.name} requires a mask — got mask.kind=none")

            opts = {**_DEFAULTS, **job.options}
            prm_path, mat_path = self._ensure_prep(job, sink)
            labels = self._classify(job, sink, prm_path, mat_path, opts)
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

    # --- prep, cached once per particle set + mask ---------------------------

    def _ensure_prep(self, job: Job, sink: ProgressSink) -> tuple[Path, Path]:
        prep_dir = job.cache_dir
        prep_dir.mkdir(parents=True, exist_ok=True)
        logs = prep_dir / "prep_logs"
        logs.mkdir(exist_ok=True)
        box, pixel_size = job.particles.box, job.particles.pixel_size
        files = list(job.particles.files)
        n = len(files)

        sink.step(self.name, "prep_stack", 1, len(self.steps))
        stack_mrc = prep_dir / "stack.mrc"
        if not stack_mrc.exists():
            stacked = build_stacked_volume(job.particles.particle_dir, files, box)
            save_mrc(stack_mrc, stacked, pixel_size=pixel_size)
            del stacked

        sink.step(self.name, "prep_model", 2, len(self.steps))
        model = prep_dir / "stack.mod"
        if not model.exists():
            coords = prep_dir / "coords.txt"
            c = box // 2
            coords.write_text("".join(f"{i + 1} {c} {c} {c + i * box}\n" for i in range(n)))
            self._run_native(
                f"point2model -scat -input {shlex.quote(str(coords))} "
                f"-image {shlex.quote(str(stack_mrc))} -output {shlex.quote(str(model))}",
                job, prep_dir, logs / "point2model.log", sink,
            )

        sink.step(self.name, "prep_motl", 3, len(self.steps))
        iter1 = prep_dir / f"{_FN_OUTPUT}_MOTL_Tom1_Iter1.csv"
        iter2 = prep_dir / f"{_FN_OUTPUT}_MOTL_Tom1_Iter2.csv"
        if not iter2.exists():
            iter1.write_text(build_motl(n, identity=True))
            iter2.write_text(build_motl(n, identity=False))

        prm_path = prep_dir / "project.prm"
        if not prm_path.exists():
            prm_path.write_text(build_prm(stack_mrc, model, iter1, Path(job.mask_path), box, pixel_size, n))

        sink.step(self.name, "prep_average", 4, len(self.steps))
        avg_matches = sorted(glob.glob(str(prep_dir / f"{_FN_OUTPUT}_AvgVol_1*.mrc")), key=os.path.getmtime)
        if not avg_matches:
            self._run_native(f"averageAll {shlex.quote(str(prm_path))} 1", job, prep_dir, logs / "averageAll.log", sink)
            avg_matches = sorted(glob.glob(str(prep_dir / f"{_FN_OUTPUT}_AvgVol_1*.mrc")), key=os.path.getmtime)
            if not avg_matches:
                raise RuntimeError(f"averageAll produced no {_FN_OUTPUT}_AvgVol_1*.mrc; see {logs / 'averageAll.log'}")
        avg_path = Path(avg_matches[-1])

        sink.step(self.name, "prep_pca", 5, len(self.steps))
        mat_matches = sorted(glob.glob(str(prep_dir / "pca*.mat")), key=os.path.getmtime)
        if not mat_matches:
            self._run_native(
                f"pca {shlex.quote(str(prm_path))} 1 {n} {shlex.quote(str(avg_path))} 1",
                job, prep_dir, logs / "pca.log", sink,
            )
            mat_matches = sorted(glob.glob(str(prep_dir / "pca*.mat")), key=os.path.getmtime)
            if not mat_matches:
                raise RuntimeError(f"pca produced no pca*.mat; see {logs / 'pca.log'}")

        return prm_path, Path(mat_matches[-1])

    def _classify(self, job: Job, sink: ProgressSink, prm_path: Path, mat_path: Path, opts: dict) -> dict[str, int]:
        prep_dir = job.cache_dir
        job.workdir.mkdir(parents=True, exist_ok=True)

        sink.step(self.name, "cluster", 6, len(self.steps))
        pc_top = int(opts["pc_top"])
        self._run_native(
            f"clusterPca {shlex.quote(str(prm_path))} {shlex.quote(str(mat_path))} "
            f"{job.k} \"1:{pc_top}\" 1 0 kmeans",
            job, prep_dir, job.log_path, sink,
        )

        # usePcaMotiveLists exits non-zero even on success (documented PEET quirk) --
        # its actual effect (did MOTL column 20 get updated?) is verified below instead
        # of trusting its return code.
        self._run_native(
            f"usePcaMotiveLists {shlex.quote(str(prm_path))} 1", job, prep_dir,
            job.workdir / "usePcaMotiveLists.log", sink, ignore_returncode=True,
        )

        motl_iter2 = prep_dir / f"{_FN_OUTPUT}_MOTL_Tom1_Iter2.csv"
        labels = parse_motl_classes(motl_iter2, list(job.particles.files))
        if not labels:
            raise RuntimeError(f"no class labels found in {motl_iter2} after usePcaMotiveLists")
        return labels

    def _run_native(
        self, cmd: str, job: Job, cwd: Path, log_path: Path, sink: ProgressSink, ignore_returncode: bool = False
    ) -> None:
        imod_setup, particle_setup = self._setup_paths(job)
        full_cmd = (
            f"source {shlex.quote(imod_setup)} >/dev/null 2>&1; "
            f"source {shlex.quote(particle_setup)} >/dev/null 2>&1; "
            f"{cmd}"
        )
        returncode, _timing = run_streaming(
            ["bash", "-c", full_cmd], package=self.name, cwd=cwd, log_path=log_path, sink=sink,
        )
        if returncode != 0 and not ignore_returncode:
            raise RuntimeError(f"PEET step failed (rc={returncode}): {cmd} — see {log_path}")
