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
from pathlib import Path


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
    B_CONDA = "conda_automatable"  # `conda env create -f envs/<pkg>.yml` can set it up
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
    """Checks PATH first; `req.detail`, if set, is a `os.pathsep`-joined list
    of extra directories to search (expanded with `~`) -- for binaries that
    are commonly a from-source build at a fixed-ish location rather than
    something an installer ever puts on PATH (e.g. RELION's `relion_refine`,
    frequently built straight into `~/relion-install/bin`)."""
    import os
    from pathlib import Path

    found = shutil.which(req.name)
    if found:
        return CheckResult(req, ok=True, found=found, message="found on PATH")

    if req.detail:
        for extra_dir in req.detail.split(os.pathsep):
            candidate = Path(extra_dir).expanduser() / req.name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return CheckResult(req, ok=True, found=str(candidate), message=f"found at {candidate}")

    return CheckResult(req, ok=False, found=None, message="not found on PATH or common install locations")


def _check_conda_env(req: Requirement) -> CheckResult:
    import json
    import subprocess
    from pathlib import Path

    # Ask conda directly first -- the authoritative source, and the only one
    # that's portable across install layouts the hardcoded paths below can't
    # anticipate (a Docker/Podman image's /opt/conda/envs, Anaconda's
    # ~/anaconda3/envs, a cluster module system's shared prefix, etc.).
    for exe in ("conda", "mamba"):
        if not shutil.which(exe):
            continue
        try:
            out = subprocess.run([exe, "env", "list", "--json"], capture_output=True, text=True, timeout=15)
            for env_path in json.loads(out.stdout).get("envs", []):
                if Path(env_path).name == req.name:
                    return CheckResult(req, ok=True, found=env_path, message="conda env found")
        except Exception:
            pass  # fall through to the path heuristic below

    # Fallback for machines where `conda`/`mamba` themselves aren't on PATH
    # (e.g. only a bare `conda run` wrapper script) but envs exist on disk.
    candidates = [
        Path.home() / "conda-envs" / req.name,
        Path.home() / "miniforge3" / "envs" / req.name,
        Path.home() / "miniconda3" / "envs" / req.name,
        Path.home() / "anaconda3" / "envs" / req.name,
        Path("/opt/conda/envs") / req.name,
    ]
    for candidate in candidates:
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
    real hard blocker is the Parallel Computing Toolbox license, not MATLAB itself.

    `matlab -batch` has been observed (while building the Dynamo adapter, roughly 1 in
    8 invocations) to segfault in an unrelated telemetry/entitlement module
    (`libmwddux.so`) on process exit -- *after* `disp(...)` has already printed the real
    answer. Checking the first stdout line (not requiring the whole stream to be exactly
    "1") tolerates trailing crash-dump text; retrying once tolerates a run where the
    crash pre-empted the print entirely."""
    import subprocess

    matlab = shutil.which("matlab")
    if not matlab:
        return CheckResult(req, ok=False, found=None, message="matlab not found on PATH")

    argv = ["matlab", "-nodisplay", "-batch", f"disp(license('test','{req.name}'))"]
    last_stdout = ""
    for _attempt in range(2):
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        except Exception as e:  # pragma: no cover - environment dependent
            return CheckResult(req, ok=False, found=None, message=f"could not query MATLAB license: {e}")
        last_stdout = out.stdout
        first_line = next((line.strip() for line in out.stdout.splitlines() if line.strip()), "")
        if first_line == "1":
            return CheckResult(req, ok=True, found=req.name, message="license available")
    message = f"license('test','{req.name}') returned {last_stdout.strip()!r}"
    return CheckResult(req, ok=False, found=None, message=message)


# Some distro OpenMPI packages (confirmed: RHEL/Fedora's openmpi RPM) install
# mpiexec/mpirun without ever putting them on PATH -- STOPGAP's own scripts
# hardcode this exact path rather than assuming PATH, so the checker mirrors that.
_MPI_FALLBACK_PATHS = (
    "/usr/lib64/openmpi/bin/mpiexec",
    "/usr/lib/x86_64-linux-gnu/openmpi/bin/mpiexec",
    "/usr/local/bin/mpiexec",
)


def resolve_mpi_bin() -> str | None:
    return shutil.which("mpirun") or shutil.which("mpiexec") or next(
        (p for p in _MPI_FALLBACK_PATHS if Path(p).exists()), None
    )


def _check_mpi(req: Requirement) -> CheckResult:
    found = resolve_mpi_bin()
    message = "found on PATH" if (found and shutil.which(found.split("/")[-1])) else (
        f"found at {found} (not on PATH)" if found else "not found on PATH or common install paths"
    )
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
