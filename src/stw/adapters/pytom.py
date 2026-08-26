"""
PyTom adapter — real PyTom (`auto_focus_classify_nofrm.py`, run via `mpirun`
inside a conda env named `pytom_env`). An iterative reference-pair
difference-map + masked-NCC classifier — not a PCA-embed-once method. Never
reimplements the algorithm; only builds PyTom's own ParticleList XML/`.em`
mask and parses its own output XML. One small compatibility shim is applied
to the vendored script (see `resources/pytom/README.md`) for a real
cross-version break in `pytom.basic.structures.ParticleList.pickle()`.

`-a` (noalign) is always passed: `stw` assumes pre-aligned input project-wide
(see docs/limitations.md), and separately, PyTom's FRM alignment search
needs a compiled `_swig_frm` extension that many PyTom builds (including the
one this adapter was validated against) don't have.

PyTom's own classifier has no `--seed`/`np.random.seed` — each run differs
via the global RNG, so "seed" here is a run index, matching the same
seed_semantics as `pytom-preview` and EMAN2.

Prep (particle-list XML + `.em` mask, cached once per particle set + mask
under `job.cache_dir`, shared across every k/seed): unlike EMAN2 there's no
consensus-average step — PyTom's classifier builds its own initial
per-cluster references internally.

Wedge is a REAL pass-through here (unlike every other adapter in this
project so far): PyTom's `SingleTiltWedge` model is baked into the
particle-list XML at prep time from `job.wedge` when `wedge.kind: uniform`
is set. Supplying no wedge info (the default) means PyTom assumes full
(0-degree missing-wedge) coverage — a deliberate choice not to guess a tilt
geometry the user never specified, rather than reusing PyTom's own script
default of a generic 30-degree wedge.
"""
from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import ClassVar

from stw.adapters.base import Adapter, PlannedStep
from stw.averaging import class_averages
from stw.capabilities import Capabilities
from stw.io.mrc import save_mrc
from stw.io.predictions import write_predictions
from stw.masks.stats import safe_worker_count
from stw.process import conda_run_argv, run_streaming
from stw.progress import NullSink, ProgressSink
from stw.requirements import InstallTier, ReqKind, Requirement
from stw.results import PackageResult
from stw.spec import Job, MaskKind, WedgeKind

_ENV = "pytom_env"
_RESOURCES = Path(__file__).resolve().parent / "resources" / "pytom"
_DEFAULTS = {"frequency": 20, "niter": 15, "threshold": 0.4, "binning": 1}


def parse_classified_xml(xml_path: str | Path) -> dict[str, int]:
    """Parses a PyTom `classified_pl_iterN.xml` ParticleList into
    {basename: class_int}. PyTom writes each particle's `<Class Name="K"/>`
    as the string form of an integer cluster id."""
    tree = ET.parse(str(xml_path))
    particles = tree.findall(".//Particle")
    labels: dict[str, int] = {}
    for p in particles:
        fname = os.path.basename(p.attrib.get("Filename", ""))
        class_el = p.find("Class")
        if fname and class_el is not None:
            labels[fname] = int(class_el.attrib["Name"])
    return labels


def latest_classified_xml(outdir: str | Path) -> Path | None:
    xmls = sorted(
        Path(outdir).glob("classified_pl_iter*.xml"),
        key=lambda p: int(p.stem.replace("classified_pl_iter", "")),
    )
    return xmls[-1] if xmls else None


def _mpirun_prefix(np_ranks: str) -> list[str]:
    """OpenMPI's `prterun`/`mpirun` refuses to run as root at all without this
    flag -- a no-op for any non-root user, but the default (and only) way a
    container image runs a process unless it sets up a dedicated user, so
    this must always be included rather than only conditionally."""
    argv = ["mpirun", "-np", np_ranks]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        argv.append("--allow-run-as-root")
    return argv


def _wedge_angle(job: Job) -> float:
    """Missing-wedge half-angle PyTom's SingleTiltWedge expects (degrees from
    90, i.e. 90 - max_tilt). No wedge info supplied -> 0 (full coverage) —
    NOT PyTom's own script default of 30, since assuming a specific tilt
    geometry the user never stated would be a silent, unverifiable guess."""
    if job.wedge.kind == WedgeKind.UNIFORM and job.wedge.tilt_min is not None:
        max_tilt = (abs(job.wedge.tilt_min) + abs(job.wedge.tilt_max)) / 2
        return max(0.0, 90.0 - max_tilt)
    return 0.0


class PyTomAdapter(Adapter):
    name = "pytom"
    display_name = "PyTom"
    tier = InstallTier.B_CONDA
    algorithm = (
        "auto_focus_classify_nofrm.py: iterative reference-pair difference-map "
        "classification — starts from k random references, alternates masked-NCC "
        "particle assignment with recomputing per-cluster averages and the mask "
        "region that best discriminates each reference pair."
    )
    requirements = (
        Requirement(
            ReqKind.CONDA_ENV, _ENV,
            install_hint="see docs/install/pytom.md -- not a one-liner (PyTom needs a "
            "gcc=12-pinned env + a legacy `setup.py install`, not a plain `pip`/`conda install`)",
            docs_page="docs/install/pytom.md", auto_installable=True, override_key="pytom.conda_env",
        ),
    )
    steps = ("prep_particle_list", "prep_mask", "classify", "collect")
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE, WedgeKind.UNIFORM}),
        deterministic=False,
        seed_semantics="run_index",
        gpu="optional",
        emits_native_class_averages=False,
        parallelism="mpi",
        min_particles=8,
    )
    NOTE: ClassVar[str] = (
        "real PyTom, but classification-only: identity poses (no alignment search — this "
        "machine's PyTom build also has no compiled _swig_frm extension). 'seed' is a run "
        "index, not a true RNG seed — PyTom's own CLI exposes no random_state/seed."
    )

    @classmethod
    def check_installed(cls, *, deep: bool = False):
        report = super().check_installed(deep=deep)
        report.notes.append(cls.NOTE)
        if deep and report.installed:
            from pathlib import Path as _Path

            mpirun_paths = [
                _Path.home() / "conda-envs" / _ENV / "bin" / "mpirun",
                _Path.home() / "miniforge3" / "envs" / _ENV / "bin" / "mpirun",
            ]
            if not any(p.exists() for p in mpirun_paths):
                report.degraded.append(
                    f"conda env {_ENV!r} found but no mpirun in its bin/ — MPI dispatch may fail"
                )
        return report

    def plan(self, job: Job) -> list[PlannedStep]:
        prep_dir = job.cache_dir
        opts = {**_DEFAULTS, **job.options}
        np_ranks = str(safe_worker_count(job.mask_path, tiers=(4, 8, 16)) if job.mask_path else 4)
        wedge_angle = _wedge_angle(job)
        plist_name = f"particle_list_w{wedge_angle:g}.xml"
        mask_name = f"mask_{job.mask_spec.cache_key()}.em"
        return [
            PlannedStep(
                "prep_particle_list", conda_run_argv(_ENV, "python", str(_RESOURCES / "generate_particle_list.py")),
                cached=(prep_dir / plist_name).exists(),
            ),
            PlannedStep(
                "prep_mask", conda_run_argv(_ENV, "python", str(_RESOURCES / "convert_mask.py")),
                cached=(prep_dir / mask_name).exists(),
            ),
            PlannedStep(
                "classify",
                conda_run_argv(
                    _ENV, *_mpirun_prefix(np_ranks), "python",
                    str(_RESOURCES / "auto_focus_classify_nofrm.py"),
                    "-p", plist_name, "-k", str(job.k), "-f", str(opts["frequency"]),
                    "-m", mask_name, "-c", mask_name, "-b", str(opts["binning"]),
                    "-i", str(opts["niter"]), "-a", "-o", str(job.workdir),
                ),
            ),
        ]

    def run(self, job: Job, progress: ProgressSink | None = None) -> PackageResult:
        sink = progress or NullSink()
        sink.start_job(self.name, list(self.steps))
        start = time.time()
        try:
            if job.mask_path is None:
                raise ValueError(f"{self.name} requires a mask — got mask.kind=none")

            opts = {**_DEFAULTS, **job.options}
            plist, mask_em = self._ensure_prep(job, sink)
            labels = self._classify(job, sink, plist, mask_em, opts)
            write_predictions(job.predictions_csv, labels)

            sink.step(self.name, "collect", 4, len(self.steps))
            averages, counts = class_averages(job.particles.particle_dir, labels)
            avg_dir = job.workdir / "class_averages"
            avg_paths = {}
            for cls, vol in averages.items():
                path = avg_dir / f"class_{cls:02d}.mrc"
                save_mrc(path, vol, pixel_size=job.particles.pixel_size)
                avg_paths[cls] = path

            elapsed = time.time() - start
            sink.finish_job(self.name, ok=True, message=f"{elapsed:.1f}s")
            warnings = [self.NOTE]
            if job.wedge.kind == WedgeKind.NONE:
                warnings.append("no wedge info supplied — PyTom ran assuming full (0-degree) coverage")
            return PackageResult(
                package=self.name, k=job.k, seed=job.seed, status="ok",
                predictions=job.predictions_csv, labels=labels, class_averages=avg_paths,
                n_per_class=counts, elapsed_sec=elapsed, warnings=warnings,
            )
        except Exception as e:
            sink.finish_job(self.name, ok=False, message=str(e))
            return PackageResult(package=self.name, k=job.k, seed=job.seed, status="failed", error=str(e))

    # --- prep, cached once per particle set + mask -------------------------

    def _ensure_prep(self, job: Job, sink: ProgressSink) -> tuple[Path, Path]:
        prep_dir = job.cache_dir
        prep_dir.mkdir(parents=True, exist_ok=True)
        logs = prep_dir / "prep_logs"
        logs.mkdir(exist_ok=True)

        sink.step(self.name, "prep_particle_list", 1, len(self.steps))
        # Keyed on wedge angle, not just particle-set+mask: the wedge geometry is baked
        # directly into this XML, so a stale cache hit here would silently keep using an
        # old wedge config after the user changed it (caught during real-adapter testing).
        wedge_angle = _wedge_angle(job)
        plist = prep_dir / f"particle_list_w{wedge_angle:g}.xml"
        if not plist.exists():
            self._conda(
                ["python", str(_RESOURCES / "generate_particle_list.py"),
                 "--input_dir", str(job.particles.particle_dir), "--pattern", job.particles.pattern,
                 "--output", str(plist), "--wedge_angle", str(wedge_angle)],
                prep_dir, logs / "particle_list.log", sink,
            )

        sink.step(self.name, "prep_mask", 2, len(self.steps))
        # Keyed on the mask's own content hash, same reasoning as the particle-list
        # wedge-keying above: a stale mask.em would otherwise survive a mask change
        # across separate `stw run` invocations sharing the same out_dir.
        mask_em = prep_dir / f"mask_{job.mask_spec.cache_key()}.em"
        if not mask_em.exists():
            assert job.mask_path is not None
            self._conda(
                ["python", str(_RESOURCES / "convert_mask.py"), str(job.mask_path), str(mask_em)],
                prep_dir, logs / "mask_convert.log", sink,
            )

        if not plist.exists() or not mask_em.exists():
            raise RuntimeError(f"PyTom prep failed; see {logs}")
        return plist, mask_em

    def _classify(self, job: Job, sink: ProgressSink, plist: Path, mask_em: Path, opts: dict) -> dict[str, int]:
        np_ranks = str(safe_worker_count(job.mask_path, tiers=(4, 8, 16)))
        job.workdir.mkdir(parents=True, exist_ok=True)
        argv = [
            *_mpirun_prefix(np_ranks), "python", str(_RESOURCES / "auto_focus_classify_nofrm.py"),
            "-p", str(plist), "-k", str(job.k), "-f", str(opts["frequency"]),
            "-m", str(mask_em), "-c", str(mask_em), "-b", str(opts["binning"]),
            "-i", str(opts["niter"]), "-a", "-o", str(job.workdir),
        ]
        if "threshold" in job.options:
            argv += ["-t", str(job.options["threshold"])]

        sink.step(self.name, "classify", 3, len(self.steps))
        self._conda(argv, job.workdir, job.log_path, sink)

        xml_path = latest_classified_xml(job.workdir)
        if xml_path is None:
            raise RuntimeError(f"no classified_pl_iter*.xml written to {job.workdir}; see {job.log_path}")
        labels = parse_classified_xml(xml_path)
        if not labels:
            raise RuntimeError(f"no particles parsed from {xml_path}")
        return labels

    @staticmethod
    def _conda(cmd: list[str], cwd: Path, log_path: Path, sink: ProgressSink) -> None:
        argv = conda_run_argv(_ENV, *cmd)
        returncode, _timing = run_streaming(argv, package="pytom", cwd=cwd, log_path=log_path, sink=sink)
        if returncode != 0:
            raise RuntimeError(f"PyTom step failed (rc={returncode}): {' '.join(cmd)} — see {log_path}")
