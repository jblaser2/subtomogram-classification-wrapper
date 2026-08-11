"""
Declarative, static per-adapter requirements — the thing that makes "show
requirements before opting in" real. A Requirement never launches the package
it checks; the same check_installed() code path backs `stw check-env`, the
orchestrator's preflight table, and (later) the GUI's opt-in panel.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from enum import Enum


class ReqKind(str, Enum):
    EXECUTABLE = "executable"
    CONDA_ENV = "conda_env"
    PYTHON_IMPORT = "python_import"
    ENV_VAR = "env_var"
    PATH_EXISTS = "path_exists"
    MATLAB = "matlab"
    MATLAB_TOOLBOX = "matlab_toolbox"
    MCR = "mcr"
    MPI = "mpi"
    GPU = "gpu"
    DISK_FREE = "disk_free"
    MEMORY = "memory"
    COMPILE_STEP = "compile_step"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class InstallTier(str, Enum):
    A_VENDORED = "vendored"  # ships in the wheel, always installed
    B_CONDA = "conda_automatable"  # `stw install <pkg>` can set it up
    C_GUIDED = "detect_and_guide"  # no license needed, but no automatable path
    D_LICENSED = "licensed_or_compiled"  # MATLAB license and/or per-machine compile

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Requirement:
    kind: ReqKind
    name: str
    detail: str | None = None
    optional: bool = False
    install_hint: str = ""
    docs_page: str | None = None
    auto_installable: bool = False
    override_key: str | None = None  # package_options key or STW_<PKG>_* env var override


@dataclass(frozen=True)
class CheckResult:
    requirement: Requirement
    ok: bool
    found: str | None
    message: str


@dataclass
class PackageReport:
    package: str
    display_name: str
    tier: InstallTier
    installed: bool
    checks: list[CheckResult] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    est_runtime: str = ""
    est_disk_per_run: str = ""
    est_ram: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "package": self.package,
            "display_name": self.display_name,
            "tier": str(self.tier),
            "installed": self.installed,
            "degraded": self.degraded,
            "est_runtime": self.est_runtime,
            "est_disk_per_run": self.est_disk_per_run,
            "est_ram": self.est_ram,
            "notes": self.notes,
            "checks": [
                {
                    "kind": str(c.requirement.kind),
                    "name": c.requirement.name,
                    "optional": c.requirement.optional,
                    "ok": c.ok,
                    "found": c.found,
                    "message": c.message,
                    "install_hint": c.requirement.install_hint,
                    "docs_page": c.requirement.docs_page,
                }
                for c in self.checks
            ],
        }


# --- individual checkers -----------------------------------------------------
# Each takes a Requirement and returns a CheckResult. Pure and side-effect-free
# (no package is ever launched by a check), so these are safe to run in CI with
# nothing installed, and safe to run before every `stw run`.


def _check_executable(req: Requirement) -> CheckResult:
    found = shutil.which(req.name)
    return CheckResult(req, ok=bool(found), found=found, message="found on PATH" if found else "not found on PATH")


def _check_conda_env(req: Requirement) -> CheckResult:
    from pathlib import Path

    env_path = Path.home() / "conda-envs" / req.name
    alt = Path.home() / "miniforge3" / "envs" / req.name
    for candidate in (env_path, alt):
        if candidate.is_dir():
            return CheckResult(req, ok=True, found=str(candidate), message="conda env found")
    return CheckResult(req, ok=False, found=None, message=f"conda env {req.name!r} not found")


def _check_python_import(req: Requirement) -> CheckResult:
    import importlib

    try:
        importlib.import_module(req.name)
        return CheckResult(req, ok=True, found=req.name, message="importable")
    except ImportError as e:
        return CheckResult(req, ok=False, found=None, message=str(e))


def _check_env_var(req: Requirement) -> CheckResult:
    import os

    value = os.environ.get(req.name)
    return CheckResult(req, ok=bool(value), found=value, message="set" if value else "not set")


def _check_path_exists(req: Requirement) -> CheckResult:
    from pathlib import Path

    p = Path(req.name).expanduser()
    return CheckResult(req, ok=p.exists(), found=str(p) if p.exists() else None,
                        message="exists" if p.exists() else "does not exist")


def _check_matlab(req: Requirement) -> CheckResult:
    found = shutil.which("matlab")
    return CheckResult(req, ok=bool(found), found=found,
                        message="matlab on PATH" if found else "matlab not found on PATH")


def _check_matlab_toolbox(req: Requirement) -> CheckResult:
    """Verifies a MATLAB toolbox LICENSE, not just the matlab binary — e.g. Dynamo's
    real hard blocker is the Parallel Computing Toolbox license, not MATLAB itself."""
    import subprocess

    matlab = shutil.which("matlab")
    if not matlab:
        return CheckResult(req, ok=False, found=None, message="matlab not found on PATH")
    try:
        out = subprocess.run(
            ["matlab", "-nodisplay", "-batch", f"disp(license('test','{req.name}'))"],
            capture_output=True, text=True, timeout=60,
        )
        ok = out.stdout.strip() == "1"
        message = "license available" if ok else f"license('test','{req.name}') returned {out.stdout.strip()!r}"
        return CheckResult(req, ok=ok, found=req.name if ok else None, message=message)
    except Exception as e:  # pragma: no cover - environment dependent
        return CheckResult(req, ok=False, found=None, message=f"could not query MATLAB license: {e}")


def _check_mpi(req: Requirement) -> CheckResult:
    found = shutil.which("mpirun") or shutil.which("mpiexec")
    message = "found on PATH" if found else "not found on PATH"
    return CheckResult(req, ok=bool(found), found=found, message=message)


def _check_gpu(req: Requirement) -> CheckResult:
    found = shutil.which("nvidia-smi")
    return CheckResult(req, ok=bool(found), found=found,
                        message="nvidia-smi found" if found else "no NVIDIA GPU detected")


def _check_disk_free(req: Requirement) -> CheckResult:
    import shutil as _shutil
    from pathlib import Path

    total, used, free = _shutil.disk_usage(Path.home())
    needed_gb = float(req.detail or 0)
    free_gb = free / 1e9
    ok = free_gb >= needed_gb
    return CheckResult(req, ok=ok, found=f"{free_gb:.1f} GB free",
                        message="sufficient" if ok else f"need >= {needed_gb} GB, have {free_gb:.1f} GB")


def _check_memory(req: Requirement) -> CheckResult:
    try:
        import psutil

        avail_gb = psutil.virtual_memory().available / 1e9
    except ImportError:
        return CheckResult(req, ok=True, found=None, message="psutil not installed, skipped")
    needed_gb = float(req.detail or 0)
    ok = avail_gb >= needed_gb
    return CheckResult(req, ok=ok, found=f"{avail_gb:.1f} GB available",
                        message="sufficient" if ok else f"need >= {needed_gb} GB, have {avail_gb:.1f} GB")


def _check_compile_step(req: Requirement) -> CheckResult:
    from pathlib import Path

    p = Path(req.name).expanduser()
    message = "compiled artifact present" if p.exists() else "not yet compiled — see install_hint"
    return CheckResult(req, ok=p.exists(), found=str(p) if p.exists() else None, message=message)


CHECKERS = {
    ReqKind.EXECUTABLE: _check_executable,
    ReqKind.CONDA_ENV: _check_conda_env,
    ReqKind.PYTHON_IMPORT: _check_python_import,
    ReqKind.ENV_VAR: _check_env_var,
    ReqKind.PATH_EXISTS: _check_path_exists,
    ReqKind.MATLAB: _check_matlab,
    ReqKind.MATLAB_TOOLBOX: _check_matlab_toolbox,
    ReqKind.MCR: _check_path_exists,
    ReqKind.MPI: _check_mpi,
    ReqKind.GPU: _check_gpu,
    ReqKind.DISK_FREE: _check_disk_free,
    ReqKind.MEMORY: _check_memory,
    ReqKind.COMPILE_STEP: _check_compile_step,
}


def run_checks(requirements: tuple[Requirement, ...]) -> list[CheckResult]:
    return [CHECKERS[req.kind](req) for req in requirements]
