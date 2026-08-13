"""
Dynamo adapter — real Dynamo `dpkpca` (CC-matrix eigendecomposition/MSA on the
top eigencomponents), driven through Dynamo's own `dpkpca.new`/`.unfold()`/
`prealign`->`ccmatrix`->`eigentable`->`eigenvolumes` MATLAB pipeline. Never
reimplements the algorithm; only builds Dynamo's own identity-pose `.tbl` and
particle-symlink layout and reads back its own `eigencomponents.csv`.

The embedding (prealign -> ccmatrix -> eigentable -> eigenvolumes -> the
eigencomponents matrix) is deterministic and seed-independent -- cached once
per particle set + mask, shared across every k/seed, matching every other
multi-step adapter's caching convention. Only the final clustering depends on
`(k, seed)`: a plain `sklearn.cluster.KMeans` on the top eigencomponent
columns, done in Python (not MATLAB) -- `seed` is a **genuine reproducible
seed** here (`random_state=seed`), unlike EMAN2/PEET's run-index pseudo-seed.

**A real, honestly-documented finding from validating this adapter, not
assumed from the source project's docs**: on `stw`'s own easy synthetic test
fixture, k-means on the blind top-10-eigencomponent default (`N_TOP`, matching
the source project's own long-validated production setting) lands at
near-chance ARI, while the true class-separating signal is cleanly present
(verified directly: a single eigencomponent column correlates at ARI=1.0 with
ground truth, and k-means on just the top 2-5 columns also recovers it
exactly) -- ten mostly-noise dimensions are enough to make unstandardized
k-means converge somewhere else on a small sample. This is not a plumbing bug
in this adapter (the embedding demonstrably preserves the real signal
faithfully); it's the same "blind PC/factor selection is often not the
discriminating axis" property already extensively documented for
ProTomo/STOPGAP/Dynamo throughout the source benchmark project (e.g. Dynamo's
own T3SS_conf Pass-2 needed "PC1 alone", not the top-5). `stw` keeps the real
default (`N_TOP=10`) rather than quietly picking whichever columns look best
on the test fixture, and exposes `package_options.dynamo.pc_cols` (a
comma-separated, 1-indexed column list, e.g. `"1,2"`) as the same tuning knob
the source project used.

**A second real, machine-specific finding**: `matlab -nodisplay -batch`
occasionally (observed roughly 1 in 8 invocations while validating this
adapter) segfaults during an unrelated internal telemetry/entitlement module
(`libmwddux.so`) on process exit -- *after* the actual computation completes
and its output is already flushed to disk/stdout. This adapter never trusts
the embedding subprocess's return code alone; it treats `eigencomponents.csv`
existing as the real success signal (the same "ignore a flaky non-zero exit,
check the actual artifact" pattern already used for PEET's
`usePcaMotiveLists`).

Missing-wedge weighting is not modeled (identity-pose `.tbl` rows carry no
wedge/CTF info). MATLAB's Parallel Computing Toolbox is a hard requirement
(`dpkpca` cannot run without it); worker count is capped based on the mask's
active-voxel fraction (2/4/8 workers), a real fix for a machine-crashing OOM
bug found in the source project (an unmasked/wide-open mask with the naive
default worker count drove system RAM from 11GB to 58GB in under a minute).
"""
from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import ClassVar

import numpy as np
from sklearn.cluster import KMeans

from stw.adapters.base import Adapter, PlannedStep
from stw.averaging import class_averages
from stw.capabilities import Capabilities
from stw.io.mrc import save_mrc
from stw.io.predictions import write_predictions
from stw.process import run_streaming
from stw.progress import NullSink, ProgressSink
from stw.requirements import InstallTier, ReqKind, Requirement
from stw.results import PackageResult
from stw.spec import Job, MaskKind, WedgeKind

_DEFAULT_DYNAMO_ACTIVATE = str(Path.home() / "Research" / "dynamo" / "dynamo_activate.m")
_EMBED_M = Path(__file__).resolve().parent / "resources" / "dynamo" / "dpkpca_embed.m"
_N_INIT = 20  # matches native kmeans 'Replicates', 20
_N_TOP = 10   # matches nc = min(10, ncols)


def build_identity_tbl(n: int) -> str:
    """Dynamo's 35-column table format, one identity-pose row per particle:
    tag (col 1), a nonzero "malign"/aligned flag (col 2) and cpu flag (col 6)
    -- everything else (including orientation) zero, matching the source
    project's own validated identity-pose convention for pre-aligned input."""
    lines = []
    for tag in range(1, n + 1):
        row = [0] * 35
        row[0], row[1], row[5] = tag, 1, 1
        lines.append(" ".join(str(v) for v in row))
    return "\n".join(lines) + "\n"


def resolve_pc_cols(pc_cols_opt: str | None, ncols: int) -> list[int]:
    """`pc_cols_opt` is a comma-separated 1-indexed column list (e.g. "1,2"),
    matching the source project's `pc_cols_sweep` override; `None` -> the
    blind default, the first `min(N_TOP, ncols)` columns."""
    if pc_cols_opt:
        return [int(x) - 1 for x in pc_cols_opt.split(",")]
    return list(range(min(_N_TOP, ncols)))


def cluster_embedding(E: np.ndarray, k: int, seed: int, pc_cols: list[int]) -> np.ndarray:
    X = E[:, pc_cols]
    km = KMeans(n_clusters=k, n_init=_N_INIT, random_state=int(seed), max_iter=500).fit(X)
    return km.labels_.astype(int) + 1


class DynamoAdapter(Adapter):
    name = "dynamo"
    display_name = "Dynamo"
    tier = InstallTier.D_LICENSED
    requirements = (
        Requirement(
            ReqKind.PATH_EXISTS, _DEFAULT_DYNAMO_ACTIVATE,
            install_hint="see docs/install/dynamo.md -- Dynamo's own dynamo_activate.m",
            docs_page="docs/install/dynamo.md", override_key="dynamo.dynamo_activate",
        ),
        Requirement(
            ReqKind.MATLAB, "matlab",
            install_hint="a MATLAB install with `matlab` on PATH; see docs/install/dynamo.md",
            docs_page="docs/install/dynamo.md",
        ),
        Requirement(
            ReqKind.MATLAB_TOOLBOX, "Distrib_Computing_Toolbox",
            install_hint="MATLAB's Parallel Computing Toolbox license -- dpkpca cannot run "
            "without it; see docs/install/dynamo.md",
            docs_page="docs/install/dynamo.md",
        ),
    )
    steps = ("build_inputs", "embed", "classify", "collect")
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE}),
        deterministic=False,
        seed_semantics="true_seed",
        gpu="unused",
        emits_native_class_averages=False,
        min_particles=8,
    )
    NOTE: ClassVar[str] = (
        "real Dynamo dpkpca (CC-matrix eigendecomposition + k-means), classification-only: "
        "identity-pose input, no missing-wedge weighting. The embedding (prealign/ccmatrix/"
        "eigentable/eigenvolumes) is cached once per particle set + mask; only k-means (a real, "
        "reproducible seed, unlike EMAN2/PEET's run-index pseudo-seed) runs per (k, seed). Blind "
        "top-10-eigencomponent k-means is not guaranteed to isolate the true class-separating "
        "axis -- override with package_options.dynamo.pc_cols if a run looks chance-level."
    )

    @classmethod
    def check_installed(cls, *, deep: bool = False):
        report = super().check_installed(deep=deep)
        report.notes.append(cls.NOTE)
        return report

    def _dynamo_activate(self, job: Job) -> str:
        return str(job.options.get("dynamo_activate", _DEFAULT_DYNAMO_ACTIVATE))

    def _embed_dir(self, job: Job) -> Path:
        return job.cache_dir / f"embed_{job.mask_spec.cache_key()}"

    def plan(self, job: Job) -> list[PlannedStep]:
        edir = self._embed_dir(job)
        return [
            PlannedStep(
                "build_inputs", ["<in-process>", "build_identity_tbl"],
                cached=(edir / "particles.tbl").exists(),
            ),
            PlannedStep(
                "embed", ["matlab", "-nodisplay", "-batch", f"run('{_EMBED_M}')"],
                cached=(edir / "eigencomponents.csv").exists(),
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
        ecsv = edir / "eigencomponents.csv"
        if ecsv.exists():
            return edir

        edir.mkdir(parents=True, exist_ok=True)
        data = edir / "data"
        data.mkdir(exist_ok=True)
        files = list(job.particles.files)

        sink.step(self.name, "build_inputs", 1, len(self.steps))
        with (edir / "file_map.csv").open("w", newline="") as lf:
            w = csv.writer(lf)
            w.writerow(["tag", "orig_file"])
            for i, f in enumerate(files):
                tag = i + 1
                link = data / f"particle_{tag:05d}.mrc"
                if not link.exists():
                    # .resolve(): a relative `particles:` config path would otherwise become
                    # a symlink target relative to `data/` itself, not the invoking cwd --
                    # the exact bug found and fixed while building the ProTomo adapter.
                    link.symlink_to(job.particles.path_for(f).resolve())
                w.writerow([tag, f])
        (edir / "particles.tbl").write_text(build_identity_tbl(len(files)))

        sink.step(self.name, "embed", 2, len(self.steps))
        env = {
            "MW_SERVICE_HOST_DISABLE": "1",
            "DYNAMO_ACTIVATE": self._dynamo_activate(job),
            "DPKPCA_OUTDIR": str(edir),
            "DPKPCA_TBL": str(edir / "particles.tbl"),
            "DPKPCA_DATA": str(data),
            "DPKPCA_MASK": str(job.mask_path),
            "DPKPCA_WFNAME": "wf_embed",
        }
        matlab = str(job.options.get("matlab_bin", "matlab"))
        log_path = edir / "embedding.log"
        # `ignore_returncode`-equivalent: matlab -batch has been observed to segfault in an
        # unrelated telemetry module (libmwddux.so) on exit AFTER a successful computation --
        # see module docstring. The real success signal is eigencomponents.csv existing, not
        # the subprocess's exit code (the same pattern PEET's usePcaMotiveLists already needs).
        run_streaming(
            [matlab, "-nodisplay", "-nosplash", "-batch", f"run('{_EMBED_M}')"],
            package=self.name, cwd=edir, log_path=log_path, sink=sink, env_extra=env,
        )
        if not ecsv.exists():
            raise RuntimeError(f"Dynamo dpkpca embedding produced no eigencomponents.csv; see {log_path}")
        return edir

    def _classify(self, job: Job, sink: ProgressSink, edir: Path) -> dict[str, int]:
        job.workdir.mkdir(parents=True, exist_ok=True)
        sink.step(self.name, "classify", 3, len(self.steps))

        E = np.loadtxt(edir / "eigencomponents.csv", delimiter=",", ndmin=2)
        with (edir / "file_map.csv").open() as f:
            rows = sorted(csv.DictReader(f), key=lambda r: int(r["tag"]))
        row_files = [r["orig_file"] for r in rows]
        if E.shape[0] != len(row_files):
            raise RuntimeError(f"eigencomponents rows {E.shape[0]} != particle count {len(row_files)}")

        pc_cols = resolve_pc_cols(job.options.get("pc_cols"), E.shape[1])
        raw_labels = cluster_embedding(E, job.k, job.seed, pc_cols)
        labels = dict(zip(row_files, (int(lab) for lab in raw_labels)))
        if not labels:
            raise RuntimeError(f"no class labels produced from {edir / 'eigencomponents.csv'}")
        return labels
