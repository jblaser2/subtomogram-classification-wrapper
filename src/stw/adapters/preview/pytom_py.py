"""
Preview-mode approximation of PyTom's "auto-focus" classifier: iterative
reference-pair difference-map + masked-NCC voting. Source-verified line-for-
line against PyTom's compiled C++ (FreqWeight/volume_fcn). Pure numpy/mrcfile
— no SWIG C++ extension, no CUDA, no MPI.

Fidelity (measured in the STA benchmark project on real T4P/FM_easy data):
the highest-fidelity of the three preview ports — ARI 0.50-0.65 on FM_easy,
closely matching real PyTom's own canonical 0.652. On T4P it is explicitly
BIMODAL: most seeds agree well with real PyTom (ARI 0.78-0.91), but roughly
2 in 5 seeds collapse to a near-50/50 split with near-zero agreement — a real,
unresolved failure mode, not a rare fluke. Only validated at k=2; the generic
k>2 voting/tie-breaking logic in this port is untested.
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

_SCRIPT = "pytom_classify_py.py"


class PyTomPreviewAdapter(Adapter):
    name = "pytom-preview"
    display_name = "PyTom (preview approximation)"
    tier = InstallTier.A_VENDORED
    requirements = ()
    steps = ("classify",)
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE, WedgeKind.UNIFORM}),
        deterministic=False,  # real PyTom is unseeded by default; this port's --seed is a port-only addition
        seed_semantics="true_seed",
        gpu="unused",
        emits_native_class_averages=False,
        variable_k=True,
        k_range=(2, 2),  # only k=2 has been validated; k>2 voting logic is real but untested
        min_particles=8,
    )
    NOTE: ClassVar[str] = (
        "approximation, not real PyTom — high fidelity at k=2 (ARI 0.50-0.65 on FM_easy, "
        "matching real PyTom's 0.652) but explicitly bimodal on T4P-like data: roughly 2 in 5 "
        "seeds collapse to near-chance; see module docstring. k>2 is untested."
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
        argv = ["--seed", str(job.seed)]
        opts = job.options
        for key, flag in (("frequency", "--frequency"), ("niter", "--niter"), ("threshold", "--threshold")):
            if key in opts:
                argv += [flag, str(opts[key])]
        if job.wedge.kind == WedgeKind.UNIFORM and job.wedge.tilt_min is not None:
            half_angle = (abs(job.wedge.tilt_min) + abs(job.wedge.tilt_max)) / 2
            argv += ["--wedge-angle", str(half_angle)]
        return argv
