"""
ProTomo adapter — real ProTomo/I3 3.1.0 (SVD-based multivariate statistical
analysis + Ward-linkage hierarchical clustering), driven through its own
`tomoprepare` -> `subvolinitial.sh` -> `subvolsvd.sh` -> `subvolhac.sh`
pipeline. Never reimplements the algorithm; only builds ProTomo's own
particle-series (`.i3i`) and mask formats and parses `tomoinfo -cls`'s own
per-particle class output.

Two real, machine-verified gotchas, both confirmed by direct probing before
writing this adapter (not assumed from the source project's own docs):

1. **`subvolsvd.sh`'s LAPACK call (SGESDD) crashes against this system's own
   BLAS/LAPACK (OpenBLAS, via conda) but works when MATLAB's bundled MKL is
   `LD_PRELOAD`ed instead** — verified directly: the same call fails with a
   `SGESDD error code ...` without the preload and succeeds with it. This
   never launches MATLAB itself (unlike Dynamo/STOPGAP), but it does mean a
   MATLAB install is a real runtime dependency of ProTomo's classification
   step on this kind of system, not just documentation noise.
2. **`subvolhac.sh`'s `CLASSES`/`CLSMIN`/`CLSMAX`/`CLSFACT` come from
   `cycle-000/param.sh`, a snapshot written once by `subvolinitial.sh` — NOT
   from `process/param-template.sh`, even when the latter is explicitly
   `source`d again before every call.** Verified directly: editing
   `param-template.sh`'s `CLASSES` and re-sourcing it before `subvolhac.sh`
   silently had no effect; only editing `cycle-000/param.sh` itself changed
   the result. This adapter always rewrites `cycle-000/param.sh` (never just
   `param-template.sh`) before every classify call.

That second finding also revealed a genuine caching opportunity ProTomo's own
docs never spell out: `subvolsvd.sh` (the expensive step, computing per-
particle SVD/MSA coordinates) does not depend on `CLASSES` at all, and
`subvolhac.sh` (cheap — Ward-HAC on already-computed coordinates) runs fine
without re-`LD_PRELOAD`ing MKL. So prep (series build, mask convert,
`subvolinitial.sh`, the raw->mra alignment-bypass copy, `subvolsvd.sh`) is
cached once per particle set + mask, shared across every k/seed; only
`cycle-000/param.sh` + `subvolhac.sh` are redone per (k, seed) job, directly
in the cached workspace (safe because `stw`'s orchestrator dispatches jobs
strictly sequentially, never concurrently, within one `stw run`).

This adapter deliberately never runs ProTomo's own `subvolclassaverage.sh`/
`subvolclassalign.sh` (which the source project used to build its own
class-average visualizations): `subvolhac.sh` alone already writes
`<prefix>-class.i3i`, the one file `tomoinfo -cls` needs to recover
per-particle labels, and `stw` builds its own generic class averages (like
every other adapter) rather than relying on any package's native ones.
Skipping them also sidesteps a documented ProTomo quirk (a benign but
confusing native error when a HAC class is nearly empty) entirely.

Real gotcha carried over from the source project, not rediscovered here but
worth restating: `subvolsvd.sh` bandpass-filters every particle before SVD
(`MSALOWPASS`/`MSAHIGHPASS`, defaults ~0.06-0.40 cycles/px of Nyquist) — this
is baked into every run, not an optional toggle.

Deterministic (Ward-HAC on a fixed SVD has no RNG at all) — `seed` here truly
means nothing, unlike EMAN2/PEET's "seed is a run index" and PyTom's
documented nondeterminism. `alignment_state` is always treated as pre-aligned
(`fine`): ProTomo's own aligner (`subvolreference.sh`/`subvolalign.sh`) is
never invoked — this adapter always copies the raw series straight to
`-mra.i3i`, the same bypass the source project needed after finding that
ProTomo's own zero-translation-search option (`MRAPKR="0 0 0"`) actually means
*unbounded* search, not "no search," and corrupts edge-padded particles.
"""
from __future__ import annotations

import re
import shlex
import time
from pathlib import Path
from typing import ClassVar

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

_DEFAULT_SETUP = str(Path.home() / "Applications" / "protomo-3.1.0" / "setup.sh")
# Both confirmed present on the reference machine; the first is what the
# source project's own scripts used, kept as the default search order.
_DEFAULT_MATLAB_ROOTS = (
    "/usr/local/MATLAB/R2024a",
    str(Path.home() / "Applications" / "matlab"),
)
_CYCPRFX = "stw-"
_DEFAULTS = {"msafact": 40, "clsfact": None}  # clsfact=None -> f"1-{min(10, msafact)}"


def _mkl_lib_paths(job: Job) -> str:
    """Space-separated `mkl.so libiomp5.so` paths for `LD_PRELOAD`, from the
    first candidate MATLAB root that has both files. Override the root via
    `package_options.protomo.matlab_root`."""
    roots = [job.options.get("matlab_root")] if job.options.get("matlab_root") else []
    roots += list(_DEFAULT_MATLAB_ROOTS)
    for root in roots:
        mkl = Path(root) / "bin" / "glnxa64" / "mkl.so"
        iomp = Path(root) / "sys" / "os" / "glnxa64" / "libiomp5.so"
        if mkl.is_file() and iomp.is_file():
            return f"{mkl} {iomp}"
    raise RuntimeError(
        "no MATLAB install found with bin/glnxa64/mkl.so + sys/os/glnxa64/libiomp5.so "
        f"(tried {roots}) — ProTomo's subvolsvd.sh needs MATLAB's bundled MKL LD_PRELOADed "
        "on this kind of system (its own LAPACK call crashes otherwise); "
        "override via package_options.protomo.matlab_root"
    )


def build_series_prep(files: list[str]) -> str:
    """ProTomo's own `.prep` mini-language for `tomoprepare`: `search` the
    stacks dir, `attach` each particle (order becomes the 0-based index axis
    `tomoinfo -cls` reports against), `save` the series."""
    lines = ["search stacks", ""]
    lines += [f"attach {f}" for f in files]
    lines += ["", "save dataset.i3i"]
    return "\n".join(lines) + "\n"


def build_param_template(
    stacks_dir: Path, mask_i3i: Path, box: int, k: int, msafact: int, clsfact: str,
) -> str:
    elip = max(box // 2 - 3, 4)
    ellipse = f"elliptic {elip} {elip} {elip} apod 5 5 5"
    return f"""#!/bin/sh
export DATADIR="{stacks_dir}"
export DIRPRFX="cycle-"
export CYCPRFX="{_CYCPRFX}"
export MOTIFSIZE="{box} {box} {box}"
export WDGCOMP="false"
export REFIMG=
export REFSEL="0-{k - 1}"
export REFMSKOPT1="{ellipse}"
export REFMONT="true"
export MRAMSKOPT1="{ellipse}"
export MRAAREA=0.0
export LOWPASS=" 0.400 0.400 0.400 apod 0.050 0.050 0.050"
export HIGHPASS="0.060 0.060 0.060 apod 0.007 0.007 0.007"
export MRACC="xcf"
export MRAPKR="0 0 0"
export MRAAVG="true"
export MSAIMGSIZE="{box} {box} {box}"
export MSAMASK="{mask_i3i}"
export MSAMASKSUPERPOS=avg
export MSALOWPASS=" 0.400 0.400 0.400 apod 0.050 0.050 0.050"
export MSAHIGHPASS="0.060 0.060 0.060 apod 0.007 0.007 0.007"
export MSAFACT={msafact}
export MSAVAR="true"
export MSAMONT="true"
export CLASSES="{k}"
export CLSMIN="{k}"
export CLSMAX="{k}"
export CLSINC="1"
export CLSFACT="{clsfact}"
export CLSHVO=
export CLSHVM=
export CLSMONT="0.4"
export SELNR={k}
export SELAVG="0-{k - 1}"
export SELMSKOPT1="${{MRAMSKOPT1}}"
export SELAREA=${{MRAAREA}}
export SELLOWPASS="${{LOWPASS}}"
export SELHIGHPASS="${{HIGHPASS}}"
export SELCC="xcf"
export SELMONT="true"
export SELPKR="5 5 5"
export FSCMSKOPT1="{ellipse}"
export FSCCLASS="false"
export CYCLOG="true"
export GLBLAVG="false"
export YPERM="true"
export CYCDBG="false"
"""


_PARAM_LINE = re.compile(r'^export (CLASSES|CLSMIN|CLSMAX|CLSFACT)=.*$', re.MULTILINE)


def set_cycle_classes(cycle_param_sh: Path, k: int, clsfact: str) -> None:
    """Rewrites `cycle-000/param.sh`'s classification-related lines in place
    -- the one file `subvolhac.sh` actually reads them from (see module
    docstring finding #2). Rewriting `param-template.sh` alone is not enough."""
    values = {"CLASSES": str(k), "CLSMIN": str(k), "CLSMAX": str(k), "CLSFACT": clsfact}
    text = cycle_param_sh.read_text()
    text = _PARAM_LINE.sub(lambda m: f'export {m.group(1)}="{values[m.group(1)]}"', text)
    cycle_param_sh.write_text(text)


def parse_tomoinfo_cls(output: str, files: list[str]) -> dict[str, int]:
    """`tomoinfo -cls <class.i3i>` prints one `[ <n> ] <index> <class>` line
    per particle; `<index>` is 0-based, in series-attach (== sorted-files)
    order."""
    labels: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.strip().split()
        if len(parts) >= 5 and parts[0] == "[" and parts[2] == "]":
            idx, cls = int(parts[3]), int(parts[4])
            if 0 <= idx < len(files):
                labels[files[idx]] = cls
    return labels


class ProTomoAdapter(Adapter):
    name = "protomo"
    display_name = "ProTomo"
    tier = InstallTier.C_GUIDED
    requirements = (
        Requirement(
            ReqKind.PATH_EXISTS, _DEFAULT_SETUP,
            install_hint="see docs/install/protomo.md -- ProTomo/I3 3.1.0's own setup.sh",
            docs_page="docs/install/protomo.md", override_key="protomo.protomo_setup",
        ),
        Requirement(
            ReqKind.PATH_EXISTS, f"{_DEFAULT_MATLAB_ROOTS[0]}/bin/glnxa64/mkl.so",
            install_hint="a MATLAB install (its bundled MKL, not a license) -- "
            "subvolsvd.sh's own LAPACK call needs it LD_PRELOADed on this kind of system; "
            "see docs/install/protomo.md",
            docs_page="docs/install/protomo.md", override_key="protomo.matlab_root",
        ),
    )
    steps = ("build_series", "mask_convert", "initial", "svd", "classify", "collect")
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE}),
        deterministic=True,
        seed_semantics="none",
        gpu="unused",
        emits_native_class_averages=False,
        min_particles=8,
    )
    NOTE: ClassVar[str] = (
        "real ProTomo (SVD/MSA + Ward-HAC via subvolsvd.sh/subvolhac.sh), classification-only: "
        "ProTomo's own aligner is bypassed (raw copied straight to -mra.i3i), no missing-wedge "
        "weighting (WDGCOMP=false). Every particle is bandpass-filtered before SVD "
        "(~0.06-0.40 cycles/px of Nyquist, MSALOWPASS/MSAHIGHPASS) -- baked in, not optional. "
        "Fully deterministic (no RNG) -- 'seed' means nothing here, unlike EMAN2/PEET's "
        "run-index pseudo-seed. Needs a MATLAB install on the machine for its bundled MKL "
        "library (LD_PRELOADed into subvolsvd.sh) even though MATLAB itself is never launched."
    )

    @classmethod
    def check_installed(cls, *, deep: bool = False):
        report = super().check_installed(deep=deep)
        report.notes.append(cls.NOTE)
        return report

    def _setup_path(self, job: Job) -> str:
        return str(job.options.get("protomo_setup", _DEFAULT_SETUP))

    def _opts(self, job: Job, n_particles: int) -> dict:
        opts = {**_DEFAULTS, **job.options}
        msafact = min(int(opts["msafact"]), max(n_particles - 1, 1))
        clsfact = opts["clsfact"] or f"1-{min(10, msafact)}"
        return {**opts, "msafact": msafact, "clsfact": clsfact}

    def plan(self, job: Job) -> list[PlannedStep]:
        prep_dir = self._prep_dir(job)
        opts = self._opts(job, len(job.particles.files))
        return [
            PlannedStep(
                "build_series", ["tomoprepare", "dataset.prep"],
                cached=(prep_dir / "prepare" / "dataset.i3i").exists(),
            ),
            PlannedStep(
                "mask_convert", ["i3preproc"],
                cached=(prep_dir / "prepare" / "mask.i3i").exists(),
            ),
            PlannedStep(
                "initial", ["subvolinitial.sh"],
                cached=(prep_dir / "process" / "cycle-000" / f"{_CYCPRFX}000-mra.i3i").exists(),
            ),
            PlannedStep(
                "svd", ["subvolsvd.sh", "0"],
                cached=(prep_dir / "process" / "cycle-000" / f"{_CYCPRFX}000.coo").exists(),
            ),
            PlannedStep("classify", ["subvolhac.sh", "0", f"--CLASSES={job.k}", f"--CLSFACT={opts['clsfact']}"]),
            PlannedStep("collect", ["tomoinfo", "-cls"]),
        ]

    def run(self, job: Job, progress: ProgressSink | None = None) -> PackageResult:
        sink = progress or NullSink()
        sink.start_job(self.name, list(self.steps))
        start = time.time()
        try:
            if job.mask_path is None:
                raise ValueError(f"{self.name} requires a mask — got mask.kind=none")

            opts = self._opts(job, len(job.particles.files))
            process_dir = self._ensure_prep(job, sink, opts)
            labels = self._classify(job, sink, process_dir, opts)
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

    # --- prep, cached once per particle set + mask (independent of k) ------

    def _prep_dir(self, job: Job) -> Path:
        return job.cache_dir / f"prep_{job.mask_spec.cache_key()}"

    def _ensure_prep(self, job: Job, sink: ProgressSink, opts: dict) -> Path:
        prep_dir = self._prep_dir(job)
        prepare, process = prep_dir / "prepare", prep_dir / "process"
        stacks = prepare / "stacks"
        stacks.mkdir(parents=True, exist_ok=True)
        process.mkdir(parents=True, exist_ok=True)
        logs = prep_dir / "prep_logs"
        logs.mkdir(exist_ok=True)
        box = job.particles.box
        files = list(job.particles.files)

        sink.step(self.name, "build_series", 1, len(self.steps))
        dataset_i3i = prepare / "dataset.i3i"
        if not dataset_i3i.exists():
            for f in files:
                link = stacks / f
                if not link.exists():
                    # .resolve(): a relative `particles:` config path would otherwise become a
                    # symlink target relative to `stacks/` itself, not the invoking cwd -- found
                    # by hitting exactly this with a relative path during real-adapter testing.
                    link.symlink_to(job.particles.path_for(f).resolve())
            (prepare / "dataset.prep").write_text(build_series_prep(files))
            self._run_native("tomoprepare dataset.prep", job, prepare, logs / "tomoprepare.log", sink)
            if not dataset_i3i.exists():
                raise RuntimeError(f"ProTomo tomoprepare produced no dataset.i3i; see {logs / 'tomoprepare.log'}")

        sink.step(self.name, "mask_convert", 2, len(self.steps))
        mask_i3i = prepare / "mask.i3i"
        if not mask_i3i.exists():
            self._run_native(
                f"i3preproc {shlex.quote(str(job.mask_path))} {mask_i3i.name}",
                job, prepare, logs / "i3preproc.log", sink,
            )
            if not mask_i3i.exists():
                raise RuntimeError(f"ProTomo i3preproc produced no mask.i3i; see {logs / 'i3preproc.log'}")

        param_sh = process / "param-template.sh"
        cycle_dir = process / "cycle-000"
        mra_i3i = cycle_dir / f"{_CYCPRFX}000-mra.i3i"

        sink.step(self.name, "initial", 3, len(self.steps))
        if not mra_i3i.exists():
            # k/CLSFACT here are placeholders for the prep-only steps below (subvolinitial.sh/
            # subvolsvd.sh use neither) -- the real values are written into cycle-000/param.sh
            # fresh before every classify() call, see set_cycle_classes().
            param_sh.write_text(build_param_template(stacks, mask_i3i, box, job.k, opts["msafact"], opts["clsfact"]))
            self._run_native(
                f"subvolinitial.sh {shlex.quote(str(dataset_i3i))}", job, process, logs / "subvolinitial.log", sink,
                with_param=True,
            )
            raw_i3i = cycle_dir / f"{_CYCPRFX}000-raw.i3i"
            if not raw_i3i.exists():
                raise RuntimeError(f"ProTomo subvolinitial.sh produced no raw.i3i; see {logs / 'subvolinitial.log'}")
            # stw requires pre-aligned (fine) input -- bypass ProTomo's own aligner entirely,
            # matching the source project's fix for MRAPKR="0 0 0" actually meaning *unbounded*
            # translation search (not "none"), which corrupted edge-padded particles.
            self._run_native(
                f"cp -p {shlex.quote(raw_i3i.name)} {shlex.quote(mra_i3i.name)}",
                job, cycle_dir, logs / "align_bypass.log", sink,
            )
            if not mra_i3i.exists():
                raise RuntimeError(f"raw->mra bypass copy failed; see {logs / 'align_bypass.log'}")

        sink.step(self.name, "svd", 4, len(self.steps))
        coo = cycle_dir / f"{_CYCPRFX}000.coo"
        if not coo.exists():
            mkl = _mkl_lib_paths(job)
            self._run_native(
                f'LD_PRELOAD="{mkl}" subvolsvd.sh 0', job, process, logs / "subvolsvd.log", sink,
                with_param=True,
            )
            if not coo.exists():
                raise RuntimeError(f"ProTomo subvolsvd.sh produced no .coo; see {logs / 'subvolsvd.log'}")

        return process

    def _classify(self, job: Job, sink: ProgressSink, process_dir: Path, opts: dict) -> dict[str, int]:
        job.workdir.mkdir(parents=True, exist_ok=True)
        cycle_param_sh = process_dir / "cycle-000" / "param.sh"
        set_cycle_classes(cycle_param_sh, job.k, opts["clsfact"])

        sink.step(self.name, "classify", 5, len(self.steps))
        self._run_native("subvolhac.sh 0", job, process_dir, job.log_path, sink)

        class_i3i = process_dir / "cycle-000" / f"{_CYCPRFX}000-class.i3i"
        if not class_i3i.exists():
            raise RuntimeError(f"ProTomo subvolhac.sh produced no class.i3i; see {job.log_path}")

        setup = self._setup_path(job)
        import subprocess

        result = subprocess.run(
            f"source {shlex.quote(setup)} && tomoinfo -cls {shlex.quote(str(class_i3i))}",
            shell=True, executable="/bin/bash", capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"tomoinfo -cls failed (rc={result.returncode}): {result.stderr}")

        labels = parse_tomoinfo_cls(result.stdout, list(job.particles.files))
        if not labels:
            raise RuntimeError(f"no class labels parsed from tomoinfo -cls {class_i3i}")
        return labels

    def _run_native(
        self, cmd: str, job: Job, cwd: Path, log_path: Path, sink: ProgressSink, with_param: bool = False,
    ) -> None:
        # subvolinitial.sh/subvolsvd.sh read DATADIR/MOTIFSIZE/MSAMASK/... straight from the
        # invoking shell's environment -- verified directly (subvolinitial.sh fails to resolve
        # its dataset without DATADIR set). `with_param` sources `./param-template.sh` (relative
        # to `cwd`, always the process/ dir when True) right before the real command.
        # subvolhac.sh does NOT need this: its own CLASSES/CLSFACT/etc. always come from
        # cycle-000/param.sh (see set_cycle_classes + module docstring finding #2), and that
        # snapshot already carries every other var subvolinitial.sh wrote at creation time.
        setup = self._setup_path(job)
        param = "source ./param-template.sh >/dev/null 2>&1 && " if with_param else ""
        full_cmd = f"source {shlex.quote(setup)} >/dev/null 2>&1 && {param}{cmd}"
        returncode, _timing = run_streaming(
            ["bash", "-c", full_cmd], package=self.name, cwd=cwd, log_path=log_path, sink=sink,
        )
        if returncode != 0:
            raise RuntimeError(f"ProTomo step failed (rc={returncode}): {cmd} — see {log_path}")
