"""
STOPGAP adapter — real STOPGAP PCA-family classification: rigid-body
pre-rotation (`rot_vol`) -> pairwise CC-matrix (`calc_ccmat`) -> eigendecomposition
(`calc_pca_ccmat`), all three dispatched as compiled MCR binaries via `mpiexec`,
followed by k-means on the per-particle eigen-projections in Python. Never
reimplements the algorithm; only builds STOPGAP's own motivelist/wedgelist/mask
inputs and reads back its own `pca/eigenval_1.csv`.

STOPGAP also ships a multi-reference-alignment (MRA) classifier and a native
HAC clustering mode. Neither is ported here: the source benchmark project
tested both extensively and found MRA suffers an unresolved "attractor"
problem (particles essentially never leave their starting class) plus a
separate registration/banding artifact, and native HAC never beat the
CC-matrix-PCA+k-means baseline — CC-matrix PCA is STOPGAP's sole canonical
method there, and the only one ported here.

Distribution note: unlike EMAN2/PyTom/RELION/PEET, STOPGAP has no confirmed
public download URL — it's obtained via a private archive from its
developers. `stw` cannot auto-install it; `check_installed()` just locates an
existing install (see docs/install/stopgap.md for the expected layout,
honestly, without inventing a source URL).

None of `build_inputs_generic.m`/`build_wedgelist.m`/`build_pca_aux.m`
(vendored in `resources/stopgap/`, see that dir's README for provenance) are
official STOPGAP source — they are thin glue calling real `sg_toolbox`
functions, needed because STOPGAP itself ships no "arbitrary particle
directory in, PCA-ready dataset out" driver.

The embedding (build_inputs -> build_wedgelist -> mask copy -> global-average
ref -> build_pca_aux -> rot_vol -> calc_ccmat -> calc_pca_ccmat) is
deterministic and seed-independent — cached once per particle set + mask,
shared across every k/seed. Only the final clustering depends on `(k, seed)`:
a plain `sklearn.cluster.KMeans` on the top eigen-projection columns, done in
Python (not MATLAB) — `seed` is a **genuine reproducible seed** here, unlike
EMAN2/PEET's run-index pseudo-seed. Default `PC_TOP=10`: the source project's
own STOPGAP adapter promotes this from STOPGAP's native default (just the
first 3 eigen-projection columns) after finding 3-alone missed a real class
split on real data that all-10 recovered — override with
`package_options.stopgap.pc_cols` (comma-separated, 1-indexed, same
convention as Dynamo's `pc_cols`) if a run looks chance-level; the same
"blind PC selection isn't always the discriminating axis" caveat documented
for ProTomo/Dynamo/STOPGAP throughout the source project applies here too.

Unlike Dynamo, STOPGAP's tilt geometry is a real pass-through:
`wedge.kind: uniform` builds an actual per-tilt wedgelist
(`build_wedgelist.m`) from `tilt_min`/`tilt_max`; `wedge.kind: none` (the
default) assumes a full +-90 degree tilt range, i.e. no missing-wedge
weighting — CTF and exposure weighting are always off
(`calc_ctf=0`/`calc_exp=0` in `pca_settings.txt`; this dataset-agnostic
pipeline has no per-tomogram defocus/dose metadata to weight with).
`package_options.stopgap.tilt_step` (default 3.0 degrees) controls the
wedgelist's tilt sampling density.

Parallelism is OS-level MPI (`mpiexec`/`mpirun`), not MATLAB's Parallel
Computing Toolbox — confirmed by reading every `.m` script STOPGAP's PCA
path touches: none call `parpool`/`parfor`. Worker count is capped by the
mask's active-voxel fraction (4/8/16 workers), the same OOM-prevention fix
already applied to Dynamo/PyTom's worker counts (a wide-open mask makes each
MPI rank's per-particle working set much larger).

MATLAB is still needed — not for parallelism, just to run the three plain
sequential `.m` glue scripts above, whose runtime (`matlab -batch`) has the
same rare (~1/8 invocations, observed while building the Dynamo adapter)
segfault-on-exit risk in an unrelated telemetry module (`libmwddux.so`),
always *after* the real computation completes. This adapter checks for each
step's expected output file rather than trusting that subprocess's return
code, the same defensive pattern used throughout every MATLAB-touching
adapter in this project. (The three MCR-compiled binaries dispatched via
`mpiexec` — `rot_vol`/`calc_ccmat`/`calc_pca_ccmat` — are standalone
executables, not `matlab -batch`; no equivalent flakiness has been observed
for them, so their exit codes are trusted directly, with `pca/eigenval_1.csv`
existing checked as the final overall gate regardless.)

A real, machine-specific gotcha found while validating this adapter: the
vendored install's `exec/lib/stopgap_config*.sh` hardcode a MATLAB-runtime
`LD_LIBRARY_PATH` for whatever machine originally compiled/configured it —
if that path doesn't exist on the machine actually running `stw`, those
scripts silently prepend a dead directory (harmless — the dynamic linker
just skips it) rather than failing outright. This adapter always exports its
own correct `LD_LIBRARY_PATH` (from `package_options.stopgap.matlab_root`,
default `~/Applications/matlab`) *before* invoking any STOPGAP binary; the
vendored scripts' own `export LD_LIBRARY_PATH=...:$LD_LIBRARY_PATH` form
appends onto that rather than replacing it, so both coexist and the correct
one is still found.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import ClassVar

import numpy as np
from sklearn.cluster import KMeans

from stw.adapters.base import Adapter, PlannedStep
from stw.averaging import class_averages, global_average
from stw.capabilities import Capabilities
from stw.io.mrc import save_mrc
from stw.io.predictions import write_predictions
from stw.masks.stats import safe_worker_count
from stw.process import run_streaming
from stw.progress import NullSink, ProgressSink
from stw.requirements import InstallTier, ReqKind, Requirement, resolve_mpi_bin
from stw.results import PackageResult
from stw.spec import Job, MaskKind, WedgeKind

_DEFAULT_STOPGAP_HOME = str(Path.home() / "Research" / "STA" / "packages" / "STOPGAP")
_DEFAULT_MATLAB_ROOT = str(Path.home() / "Applications" / "matlab")
_RESOURCES = Path(__file__).resolve().parent / "resources" / "stopgap"

_N_INIT = 20              # matches native kmeans 'Replicates', 20
_N_TOP = 10               # promoted from STOPGAP's native 3-column default
_DEFAULT_TILT_STEP = 3.0  # degrees


def resolve_pc_cols(pc_cols_opt: str | None, ncols: int) -> list[int]:
    """`pc_cols_opt` is a comma-separated 1-indexed column list (e.g. "1,2");
    `None` -> the blind default, the first `min(N_TOP, ncols)` columns."""
    if pc_cols_opt:
        return [int(x) - 1 for x in pc_cols_opt.split(",")]
    return list(range(min(_N_TOP, ncols)))


def cluster_embedding(E: np.ndarray, k: int, seed: int, pc_cols: list[int]) -> np.ndarray:
    X = E[:, pc_cols]
    km = KMeans(n_clusters=k, n_init=_N_INIT, random_state=int(seed), max_iter=500).fit(X)
    return km.labels_.astype(int) + 1


def resolve_tilt_range(job: Job) -> tuple[float, float]:
    """STOPGAP needs an actual tilt range for its wedgelist. `wedge.kind:
    uniform` passes it through for real; `wedge.kind: none` (the default)
    assumes a full +-90 degree range -- i.e. no missing-wedge weighting --
    since CTF/exposure weighting is already off project-wide (no per-tomogram
    defocus/dose metadata for this dataset-agnostic pipeline to use)."""
    if job.wedge.kind == WedgeKind.UNIFORM:
        return float(job.wedge.tilt_min), float(job.wedge.tilt_max)
    return -90.0, 90.0


def _mlbatch_argv(matlab: str, script: str) -> list[str]:
    return [matlab, "-nodisplay", "-nosplash", "-batch", script]


def _pca_parser_argv(parser_sh: Path, task: str, rootdir: Path, mask_name: str, n_eigs: int) -> list[str]:
    return [
        str(parser_sh),
        "param_name", "params/pca_param.star", "pca_task", task, "rootdir", f"{rootdir}/",
        "tempdir", "none", "commdir", "none", "rawdir", "none", "refdir", "none",
        "maskdir", "none", "listdir", "none", "subtomodir", "none", "rvoldir", "none",
        "pcadir", "none", "metadir", "none", "iteration", "1",
        "motl_name", "allmotl", "wedgelist_name", "wedgelist.star", "binning", "1",
        "ref_name", "ref", "mask_name", mask_name, "subtomo_name", "subtomo",
        "rvol_name", "rvol", "rwei_name", "rwei", "filtlist_name", "filter_list.star",
        "data_type", "awpd", "ccmat_name", "ccmatrix", "covar_name", "covar",
        "n_eigs", str(n_eigs), "eigenvol_name", "eigenvol", "eigenfac_name", "eigenfac",
        "eigenval_name", "eigenval", "apply_laplacian", "0", "symmetry", "c1", "fthresh", "200",
    ]


class STOPGAPAdapter(Adapter):
    name = "stopgap"
    display_name = "STOPGAP"
    tier = InstallTier.D_LICENSED
    algorithm = (
        "STOPGAP's real CC-matrix PCA: rigid-body pre-rotation (rot_vol) -> pairwise "
        "correlation matrix (calc_ccmat) -> eigendecomposition (calc_pca_ccmat), then "
        "k-means on the top eigen-projections."
    )
    requirements = (
        Requirement(
            ReqKind.PATH_EXISTS, str(Path(_DEFAULT_STOPGAP_HOME) / "sg_toolbox"),
            install_hint="see docs/install/stopgap.md -- STOPGAP's own sg_toolbox/ MATLAB library",
            docs_page="docs/install/stopgap.md", override_key="stopgap.stopgap_home",
        ),
        Requirement(
            ReqKind.PATH_EXISTS, str(Path(_DEFAULT_STOPGAP_HOME) / "exec" / "lib" / "stopgap"),
            install_hint="see docs/install/stopgap.md -- STOPGAP's compiled exec/lib/stopgap binary",
            docs_page="docs/install/stopgap.md", override_key="stopgap.stopgap_home",
        ),
        Requirement(
            ReqKind.MATLAB, "matlab",
            install_hint="a MATLAB install with `matlab` on PATH; see docs/install/stopgap.md",
            docs_page="docs/install/stopgap.md",
        ),
        Requirement(
            ReqKind.MPI, "mpirun",
            install_hint="OpenMPI's mpirun/mpiexec -- often installed but NOT on PATH by default "
            "(e.g. RHEL/Fedora's openmpi RPM); see docs/install/stopgap.md",
            docs_page="docs/install/stopgap.md",
        ),
    )
    steps = ("build_inputs", "wedgelist", "mask_and_ref", "pca_aux", "embed", "classify", "collect")
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE, WedgeKind.UNIFORM}),
        deterministic=False,
        seed_semantics="true_seed",
        gpu="unused",
        emits_native_class_averages=False,
        parallelism="mpi",
        min_particles=8,
    )
    NOTE: ClassVar[str] = (
        "real STOPGAP CC-matrix PCA (rot_vol/calc_ccmat/calc_pca_ccmat, compiled MCR binaries "
        "via mpiexec) + k-means, classification-only: STOPGAP's own MRA and native-HAC "
        "classifiers were tested and rejected by the source project, not ported. The embedding "
        "is cached once per particle set + mask; only k-means (a real, reproducible seed) runs "
        "per (k, seed). Blind top-10-eigen-projection k-means is not guaranteed to isolate the "
        "true class-separating axis -- override with package_options.stopgap.pc_cols if a run "
        "looks chance-level."
    )

    @classmethod
    def check_installed(cls, *, deep: bool = False):
        report = super().check_installed(deep=deep)
        report.notes.append(cls.NOTE)
        return report

    def _stopgap_home(self, job: Job) -> Path:
        return Path(job.options.get("stopgap_home", _DEFAULT_STOPGAP_HOME))

    def _matlab_root(self, job: Job) -> Path:
        return Path(job.options.get("matlab_root", _DEFAULT_MATLAB_ROOT))

    def _matlab_bin(self, job: Job) -> str:
        return str(job.options.get("matlab_bin", "matlab"))

    def _embed_dir(self, job: Job) -> Path:
        return job.cache_dir / f"embed_{job.mask_spec.cache_key()}"

    def _ld_library_path_extra(self, job: Job) -> str:
        root = self._matlab_root(job)
        dirs = [
            root / "runtime" / "glnxa64", root / "bin" / "glnxa64",
            root / "sys" / "os" / "glnxa64", root / "sys" / "opengl" / "lib" / "glnxa64",
        ]
        return ":".join(str(d) for d in dirs)

    def plan(self, job: Job) -> list[PlannedStep]:
        edir = self._embed_dir(job)
        return [
            PlannedStep(
                "build_inputs", [self._matlab_bin(job), "-batch", "build_inputs_generic(...)"],
                cached=(edir / "lists" / "allmotl_1.star").exists(),
            ),
            PlannedStep(
                "wedgelist", [self._matlab_bin(job), "-batch", "build_wedgelist(...)"],
                cached=(edir / "lists" / "wedgelist.star").exists(),
            ),
            PlannedStep(
                "mask_and_ref", ["<in-process>", "copy mask + global_average"],
                cached=(edir / "ref" / "ref_1.mrc").exists(),
            ),
            PlannedStep(
                "pca_aux", [self._matlab_bin(job), "-batch", "build_pca_aux(...)"],
                cached=(edir / "lists" / "filter_list.star").exists(),
            ),
            PlannedStep(
                "embed", ["mpiexec", "-np", "N", "stopgap_mpi_slurm.sh", "rot_vol/calc_ccmat/calc_pca_ccmat"],
                cached=(edir / "pca" / "eigenval_1.csv").exists(),
            ),
            PlannedStep("classify", ["<in-process>", "sklearn.cluster.KMeans"]),
            PlannedStep("collect", ["<in-process>", "write_predictions"]),
        ]

    def run(self, job: Job, progress: ProgressSink | None = None) -> PackageResult:
        sink = progress or NullSink()
        sink.start_job(self.name, list(self.steps))
        start = time.time()
        try:
            if job.mask_path is None:
                raise ValueError(f"{self.name} requires a mask — got mask.kind=none")

            edir = self._ensure_embedding(job, sink)
            labels = self._classify(job, sink, edir)
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

    # --- embedding, cached once per particle set + mask (independent of k/seed) ---

    def _ensure_embedding(self, job: Job, sink: ProgressSink) -> Path:
        edir = self._embed_dir(job)
        eig = edir / "pca" / "eigenval_1.csv"
        if eig.exists():
            return edir

        for sub in ("params", "pca", "logs", "mask", "masks", "ref", "lists", "rvol", "comm", "temp"):
            (edir / sub).mkdir(parents=True, exist_ok=True)

        home = self._stopgap_home(job)
        sg_toolbox = home / "sg_toolbox"
        stopgaphome = home / "exec"
        matlab = self._matlab_bin(job)
        base_env = {"STOPGAPHOME": str(stopgaphome), "LD_LIBRARY_PATH": self._ld_library_path_extra(job)}
        files = list(job.particles.files)

        motl = edir / "lists" / "allmotl_1.star"
        if not motl.exists():
            sink.step(self.name, "build_inputs", 1, len(self.steps))
            # .resolve(): a relative `particles:` config path is otherwise resolved
            # against the matlab subprocess's own cwd (`edir`, set below), not the
            # invoking cwd -- the exact bug class found and fixed for ProTomo's
            # particle symlinks and reused proactively for Dynamo's.
            particle_dir = Path(job.particles.particle_dir).resolve()
            script = (
                f"addpath(genpath('{sg_toolbox}')); addpath('{_RESOURCES}'); "
                f"build_inputs_generic('{particle_dir}', '{edir}', "
                f"'{job.particles.pattern}'); exit;"
            )
            rc, _ = run_streaming(
                _mlbatch_argv(matlab, script), package=self.name, cwd=edir,
                log_path=edir / "logs" / "build_inputs.log", sink=sink, env_extra=base_env,
            )
            if not motl.exists():
                raise RuntimeError(
                    f"STOPGAP build_inputs produced no lists/allmotl_1.star (rc={rc}); "
                    f"see {edir / 'logs' / 'build_inputs.log'}"
                )

        wedgelist = edir / "lists" / "wedgelist.star"
        if not wedgelist.exists():
            sink.step(self.name, "wedgelist", 2, len(self.steps))
            tilt_min, tilt_max = resolve_tilt_range(job)
            tilt_step = float(job.options.get("tilt_step", _DEFAULT_TILT_STEP))
            script = (
                f"addpath(genpath('{sg_toolbox}')); addpath('{_RESOURCES}'); "
                f"build_wedgelist('{edir}', {tilt_min}, {tilt_max}, {tilt_step}); exit;"
            )
            rc, _ = run_streaming(
                _mlbatch_argv(matlab, script), package=self.name, cwd=edir,
                log_path=edir / "logs" / "build_wedgelist.log", sink=sink, env_extra=base_env,
            )
            if not wedgelist.exists():
                raise RuntimeError(
                    f"STOPGAP build_wedgelist produced no lists/wedgelist.star (rc={rc}); "
                    f"see {edir / 'logs' / 'build_wedgelist.log'}"
                )

        mask_name = Path(job.mask_path).name
        ref_path = edir / "ref" / "ref_1.mrc"
        if not ref_path.exists():
            sink.step(self.name, "mask_and_ref", 3, len(self.steps))
            shutil.copyfile(job.mask_path, edir / "mask" / mask_name)
            shutil.copyfile(job.mask_path, edir / "masks" / mask_name)
            avg = global_average(job.particles.particle_dir, files)
            save_mrc(ref_path, avg, pixel_size=job.particles.pixel_size)

        filtlist = edir / "lists" / "filter_list.star"
        if not filtlist.exists():
            sink.step(self.name, "pca_aux", 4, len(self.steps))
            lp_rad = max(4, round(0.42 * job.particles.box / 2))
            script = (
                f"addpath(genpath('{sg_toolbox}')); addpath('{_RESOURCES}'); "
                f"build_pca_aux('{edir}', {lp_rad}, 2, 1, 2); exit;"
            )
            rc, _ = run_streaming(
                _mlbatch_argv(matlab, script), package=self.name, cwd=edir,
                log_path=edir / "logs" / "build_pca_aux.log", sink=sink, env_extra=base_env,
            )
            if not filtlist.exists():
                raise RuntimeError(
                    f"STOPGAP build_pca_aux produced no lists/filter_list.star (rc={rc}); "
                    f"see {edir / 'logs' / 'build_pca_aux.log'}"
                )

        sink.step(self.name, "embed", 5, len(self.steps))
        n_cores = safe_worker_count(job.mask_path, tiers=(4, 8, 16))
        n_eigs = max(1, min(_N_TOP, len(files) - 1))
        mpi_bin = resolve_mpi_bin() or "mpiexec"
        parser_sh = stopgaphome / "bin" / "stopgap_pca_parser.sh"
        mpi_slurm_sh = stopgaphome / "bin" / "stopgap_mpi_slurm.sh"
        for task in ("rot_vol", "calc_ccmat", "calc_pca_ccmat"):
            rc, _ = run_streaming(
                _pca_parser_argv(parser_sh, task, edir, mask_name, n_eigs),
                package=self.name, cwd=edir, log_path=edir / "logs" / f"parse_{task}.log",
                sink=sink, env_extra=base_env,
            )
            if rc != 0:
                raise RuntimeError(
                    f"STOPGAP {task} parser failed (rc={rc}); see {edir / 'logs' / f'parse_{task}.log'}"
                )
            rc, _ = run_streaming(
                [mpi_bin, "-np", str(n_cores), str(mpi_slurm_sh), str(edir),
                 "params/pca_param.star", str(n_cores), "0", "local"],
                package=self.name, cwd=edir, log_path=edir / "logs" / f"run_{task}.log",
                sink=sink, env_extra=base_env,
            )
            if rc != 0:
                raise RuntimeError(
                    f"STOPGAP {task} run failed (rc={rc}); see {edir / 'logs' / f'run_{task}.log'}"
                )

        if not eig.exists():
            raise RuntimeError(f"STOPGAP embedding produced no pca/eigenval_1.csv; see {edir / 'logs'}")
        return edir

    def _classify(self, job: Job, sink: ProgressSink, edir: Path) -> dict[str, int]:
        job.workdir.mkdir(parents=True, exist_ok=True)
        sink.step(self.name, "classify", 6, len(self.steps))

        E = np.loadtxt(edir / "pca" / "eigenval_1.csv", delimiter=",", ndmin=2)
        row_files = list(job.particles.files)
        if E.shape[0] != len(row_files):
            raise RuntimeError(f"eigenval rows {E.shape[0]} != particle count {len(row_files)}")

        pc_cols = resolve_pc_cols(job.options.get("pc_cols"), E.shape[1])
        raw_labels = cluster_embedding(E, job.k, job.seed, pc_cols)
        labels = dict(zip(row_files, (int(lab) for lab in raw_labels)))
        if not labels:
            raise RuntimeError(f"no class labels produced from {edir / 'pca' / 'eigenval_1.csv'}")
        return labels
