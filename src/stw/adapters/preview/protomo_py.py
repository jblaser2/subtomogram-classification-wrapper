"""
Preview-mode approximation of ProTomo's SVD(MSA) + Ward-linkage HAC pipeline.
Ported by INFERENCE ONLY — ProTomo ships no source, only a closed compiled
binary, so several judgment calls (filter-combination rule, exact MSA math)
are unverified. Pure numpy/scipy/scikit-learn/mrcfile.

Fidelity (measured in the STA benchmark project on real T4P/FM_easy data):
the weakest of the three preview ports — ARI ~0.016 on FM_easy vs. real
ProTomo's 0.152 (non-degenerate, above chance, but ~10x smaller); on T4P,
agreement with real ProTomo's own predictions is near-chance (though real
ProTomo's own run-to-run reproducibility on that data is itself already
near-chance, which softens how damning that number is). Treat this port's
output as a rough, directionally-informative substitute, not a stand-in for
real ProTomo's exact numbers. No missing-wedge compensation, matching real
ProTomo's own default configuration in the source project.
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

_SCRIPT = "protomo_classify_py.py"


class ProtomoPreviewAdapter(Adapter):
    name = "protomo-preview"
    display_name = "ProTomo (preview approximation)"
    tier = InstallTier.A_VENDORED
    algorithm = "Zero-install approximation of ProTomo's SVD-MSA + Ward-HAC — not real ProTomo."
    requirements = ()
    steps = ("classify",)
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE}),  # matches real ProTomo's own no-wedge-compensation default
        deterministic=True,
        seed_semantics="none",  # Ward linkage has no RNG
        gpu="unused",
        emits_native_class_averages=False,
        min_particles=8,
    )
    NOTE: ClassVar[str] = (
        "approximation, not real ProTomo — weakest-fidelity of the three preview ports "
        "(ARI ~0.016 vs. real ProTomo's 0.152 on FM_easy; near-chance agreement on T4P); "
        "ported by inference only, no ProTomo source exists — see module docstring"
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
        if "clsfact" in opts:
            argv += ["--clsfact", str(opts["clsfact"])]
        if "nfact" in opts:
            argv += ["--nfact", str(opts["nfact"])]
        if "normalize" in opts:
            argv += ["--normalize", str(opts["normalize"])]
        return argv
