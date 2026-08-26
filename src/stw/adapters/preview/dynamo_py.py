"""
Preview-mode approximation of Dynamo's `dpkpca` classifier: a missing-wedge-
compensated cross-correlation (Gram) matrix eigendecomposition + k-means,
verified against Dynamo's MATLAB source. No MATLAB, no Parallel Computing
Toolbox — pure numpy/scipy/scikit-learn.

Fidelity (measured in the STA benchmark project on real T4P/FM_easy data):
mid-pack — ARI 0.22-0.30 vs. real Dynamo's 0.475 on the same pre-aligned
input; real Dynamo's own full pipeline (its own aligner + dpkpca) scores much
higher (0.985), but that's not a fair comparison since this port only
approximates the classification step, not alignment. This is a rough,
directionally-informative substitute, not a drop-in replacement for real
Dynamo's exact numbers.
"""
from __future__ import annotations

from typing import ClassVar

from stw.adapters.base import Adapter, PlannedStep
from stw.adapters.preview._common import plan_script_run, run_script_job
from stw.capabilities import Capabilities
from stw.progress import ProgressSink
from stw.requirements import InstallTier
from stw.results import PackageResult
from stw.spec import Job, MaskKind, WedgeKind

_SCRIPT = "dynamo_classify_py.py"


class DynamoPreviewAdapter(Adapter):
    name = "dynamo-preview"
    display_name = "Dynamo (preview approximation)"
    tier = InstallTier.A_VENDORED
    algorithm = "Zero-install approximation of Dynamo's kernel PCA + k-means — not real Dynamo."
    requirements = ()
    steps = ("classify",)
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE, WedgeKind.UNIFORM}),
        deterministic=True,
        seed_semantics="none",  # k-means calls in this port use a hardcoded random_state=42
        gpu="unused",
        emits_native_class_averages=False,
        min_particles=8,
    )
    NOTE: ClassVar[str] = (
        "approximation, not real Dynamo — mid-pack fidelity (ARI ~0.22-0.30 vs. real "
        "Dynamo's 0.475 on the same pre-aligned input); see module docstring"
    )

    @classmethod
    def check_installed(cls, *, deep: bool = False):
        report = super().check_installed(deep=deep)
        report.notes.append(cls.NOTE)
        return report

    def plan(self, job: Job) -> list[PlannedStep]:
        return plan_script_run(self.name, _SCRIPT, job, self._extra_argv(job))

    def run(self, job: Job, progress: ProgressSink | None = None) -> PackageResult:
        result = run_script_job(self.name, _SCRIPT, job, self._extra_argv(job), progress)
        if result.status == "ok":
            result.warnings.append(self.NOTE)
        return result

    def _extra_argv(self, job: Job) -> list[str]:
        argv: list[str] = []
        opts = job.options
        method = opts.get("method", "cc")
        argv += ["--method", method]
        if "ncomp" in opts:
            argv += ["--ncomp", str(opts["ncomp"])]
        if "neig" in opts:
            argv += ["--neig", str(opts["neig"])]
        if "nproc" in opts:
            argv += ["--nproc", str(opts["nproc"])]
        if job.wedge.kind == WedgeKind.UNIFORM and job.wedge.tilt_min is not None:
            argv += ["--tilt-range", str(job.wedge.tilt_min), str(job.wedge.tilt_max)]
        return argv
