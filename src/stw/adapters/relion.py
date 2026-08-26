"""
RELION adapter — real `relion_refine` Class3D (regularized ML-EM in Fourier
space; NOT a PCA/embedding method). Classification only: `--skip_align`
throughout, since `stw` assumes pre-aligned input project-wide (see
docs/limitations.md).

Unlike EMAN2/PyTom, prep needs no package-specific library bindings at all
(no relion Python API is used) — building RELION's own input formats (a 3D
CTF/wedge cube, a two-block STAR file) and parsing its own `_data.star`
output are pure numpy/text-format work, done in-process. The only actual
subprocess call is `relion_refine` itself.

RELION's `relion_refine` binary is commonly a from-source build with no
fixed install location (no conda/pip path at all on many machines) — see
docs/install/relion.md. `check_installed()` searches PATH first, then a
`package_options.relion.relion_bin` override, then a few common install
dirs.

Wedge is a REAL pass-through here, same idea as PyTom: `wedge.kind: uniform`
bakes a real single-axis missing-wedge 3D CTF cube (RELION's own expected
`rlnCtfImage` format) from `tilt_min`/`tilt_max`. No wedge info supplied
means an all-ones (no wedge weighting) CTF cube, not a silently guessed
tilt range.

`--random_seed` is a REAL seed here (unlike EMAN2/PyTom/most preview
adapters, which expose no seed control at all) — `seed_semantics="true_seed"`.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import ClassVar

import numpy as np

from stw.adapters.base import Adapter, PlannedStep
from stw.averaging import class_averages, global_average
from stw.capabilities import Capabilities
from stw.io.mrc import save_mrc
from stw.io.predictions import write_predictions
from stw.process import run_streaming
from stw.progress import NullSink, ProgressSink
from stw.requirements import InstallTier, ReqKind, Requirement
from stw.results import PackageResult
from stw.spec import Job, MaskKind, WedgeKind

_BINARY = "relion_refine"
_COMMON_DIRS = os.pathsep.join(
    [str(Path.home() / "relion-install" / "bin"), "/usr/local/relion/bin", "/opt/relion/bin"]
)
_DEFAULTS = {"iter": 25, "tau2_fudge": 4, "ini_high": 60.0, "threads": None}


def build_wedge_ctf(box: int, tilt_deg: float) -> np.ndarray:
    """A centered, single-axis (Y) missing-wedge 3D CTF cube: 1.0 where a
    Fourier voxel's angle from the kx-axis (within the kx-kz plane) is within
    the measured tilt range, 0.0 in the missing wedge. tilt_deg=90 -> all-ones
    (no wedge). Matches RELION's expected `rlnCtfImage` format: a real cube,
    XSIZE==YSIZE==ZSIZE, DC term centered at box//2."""
    c = box // 2
    ax = np.arange(box) - c
    kz, ky, kx = np.meshgrid(ax, ax, ax, indexing="ij")
    phi = np.degrees(np.arctan2(np.abs(kz), np.abs(kx)))
    mask = (phi <= tilt_deg).astype(np.float32)
    mask[c, c, c] = 1.0
    return mask


def _max_tilt(job: Job) -> float:
    """90 (=no missing wedge / all-ones CTF) unless a real uniform wedge was
    supplied — mirrors PyTom's honesty stance: no silently-assumed tilt range."""
    if job.wedge.kind == WedgeKind.UNIFORM and job.wedge.tilt_min is not None:
        return (abs(job.wedge.tilt_min) + abs(job.wedge.tilt_max)) / 2
    return 90.0


def build_star(particle_dir: Path, files: list[str], ctf_image: Path, pixel_size: float, box: int) -> str:
    """RELION 3.1+-style two-block STAR (data_optics + data_particles) for a
    classic 3D-subtomogram Class3D run on already-aligned, already-centered
    subtomograms (angles/origins all zero). Every particle points at the
    same shared 3D CTF/wedge cube -- these are reconstructed subtomograms,
    not a tilt series, so there is no real per-particle CTF."""
    lines = [
        "",
        "# stw-generated RELION input -- classification-only (--skip_align), no per-particle CTF",
        "data_optics",
        "",
        "loop_",
        "_rlnOpticsGroup #1",
        "_rlnOpticsGroupName #2",
        "_rlnImagePixelSize #3",
        "_rlnImageSize #4",
        "_rlnImageDimensionality #5",
        "_rlnVoltage #6",
        "_rlnSphericalAberration #7",
        "_rlnAmplitudeContrast #8",
        f"1 opticsGroup1 {pixel_size:.4f} {box} 3 300.0 2.7 0.1",
        "",
        "data_particles",
        "",
        "loop_",
        "_rlnImageName #1",
        "_rlnCtfImage #2",
        "_rlnOpticsGroup #3",
        "_rlnAngleRot #4",
        "_rlnAngleTilt #5",
        "_rlnAnglePsi #6",
        "_rlnOriginXAngst #7",
        "_rlnOriginYAngst #8",
        "_rlnOriginZAngst #9",
    ]
    for fname in files:
        img = str(particle_dir / fname)
        lines.append(f"{img} {ctf_image} 1 0.0 0.0 0.0 0.0 0.0 0.0")
    return "\n".join(lines) + "\n"


def parse_star_particles(path: str | Path) -> list[dict[str, str]]:
    """Parses the `data_particles` loop of a RELION STAR file into a list of
    {column_name: value} dicts. Pure text-format parsing, no RELION library
    needed -- used both to read our own generated input STAR (for original
    particle order) and RELION's own `_data.star` output (for class labels)."""
    rows: list[dict[str, str]] = []
    in_block = in_loop = False
    headers: list[str] = []
    with open(path) as f:
        for raw in f:
            line = raw.rstrip()
            stripped = line.strip()
            if stripped.startswith("data_"):
                in_block = stripped == "data_particles"
                in_loop = False
                headers = []
                continue
            if not in_block:
                continue
            if stripped == "loop_":
                in_loop = True
                continue
            if not in_loop:
                continue
            if stripped.startswith("_"):
                headers.append(stripped.split()[0])
                continue
            if not stripped:
                in_loop = False
                continue
            values = stripped.split()
            if len(values) == len(headers):
                rows.append(dict(zip(headers, values, strict=True)))
    return rows


def parse_relion_classes(data_star: str | Path, input_star: str | Path) -> dict[str, int]:
    """Maps each input particle's basename to its final `_rlnClassNumber`
    from a `run_it0NN_data.star` output, using the input STAR for the
    canonical particle list (RELION's output preserves image names but not
    necessarily useful for basename recovery without the original mapping)."""
    input_rows = parse_star_particles(input_star)
    output_rows = parse_star_particles(data_star)
    if not output_rows:
        raise RuntimeError(f"no data_particles rows found in {data_star}")
    class_by_image = {r["_rlnImageName"]: int(r["_rlnClassNumber"]) for r in output_rows}

    labels: dict[str, int] = {}
    for row in input_rows:
        image = row["_rlnImageName"]
        cls = class_by_image.get(image)
        if cls is not None:
            labels[os.path.basename(image)] = cls
    return labels


class RELIONAdapter(Adapter):
    name = "relion"
    display_name = "RELION"
    tier = InstallTier.C_GUIDED  # no reliable conda-forge/bioconda package exists; a CMake source build
    algorithm = (
        "relion_refine's real 3D classification (Class3D): regularized maximum-likelihood "
        "expectation-maximization in Fourier space over k 3D references, orientation "
        "search disabled (assumes pre-aligned input)."
    )
    requirements = (
        Requirement(
            ReqKind.EXECUTABLE, _BINARY, detail=_COMMON_DIRS,
            install_hint="see docs/install/relion.md -- commonly a from-source build; "
            "override the exact path with package_options.relion.relion_bin",
            docs_page="docs/install/relion.md", auto_installable=False, override_key="relion.relion_bin",
        ),
    )
    steps = ("prep_ctf", "prep_star", "prep_ref", "classify", "collect")
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE, WedgeKind.UNIFORM}),
        deterministic=True,
        seed_semantics="true_seed",
        gpu="unused",
        emits_native_class_averages=False,
        min_particles=8,
    )
    NOTE: ClassVar[str] = (
        "real RELION Class3D, but classification-only: identity poses (--skip_align, no "
        "orientation search), CPU only (no --gpu/--blush support in this adapter). RELION's "
        "regularized ML-EM is documented to collapse to one dominant class on some low-SNR "
        "real data -- a real algorithm-level finding, not a bug in this adapter."
    )

    @classmethod
    def check_installed(cls, *, deep: bool = False):
        report = super().check_installed(deep=deep)
        report.notes.append(cls.NOTE)
        return report

    def _binary_path(self, job: Job) -> str:
        override = job.options.get("relion_bin")
        if override:
            return str(override)
        import shutil

        found = shutil.which(_BINARY)
        if found:
            return found
        for extra_dir in _COMMON_DIRS.split(os.pathsep):
            candidate = Path(extra_dir).expanduser() / _BINARY
            if candidate.is_file():
                return str(candidate)
        return _BINARY  # let it fail loudly at exec time with a clear "not found"

    def plan(self, job: Job) -> list[PlannedStep]:
        prep_dir = job.cache_dir
        opts = {**_DEFAULTS, **job.options}
        max_tilt = _max_tilt(job)
        ctf_name = f"ctf_t{max_tilt:g}.mrc"
        star_name = f"particles_t{max_tilt:g}.star"
        return [
            PlannedStep("prep_ctf", ["<in-process>", "build_wedge_ctf"], cached=(prep_dir / ctf_name).exists()),
            PlannedStep("prep_star", ["<in-process>", "build_star"], cached=(prep_dir / star_name).exists()),
            PlannedStep(
                "prep_ref", ["<in-process>", "global_average"],
                cached=(prep_dir / "initial_ref.mrc").exists(),
            ),
            PlannedStep(
                "classify",
                [
                    self._binary_path(job), "--i", str(prep_dir / star_name),
                    "--ref", str(prep_dir / "initial_ref.mrc"), "--K", str(job.k),
                    "--iter", str(opts["iter"]), "--skip_align", "--solvent_mask", str(job.mask_path),
                    "--random_seed", str(job.seed),
                ],
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
            ctf_path, star_path, ref_path = self._ensure_prep(job, sink, opts)
            labels = self._classify(job, sink, star_path, ref_path, opts)
            write_predictions(job.predictions_csv, labels)

            sink.step(self.name, "collect", 5, len(self.steps))
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
                warnings.append("no wedge info supplied — RELION ran with an all-ones (no-wedge) CTF cube")
            return PackageResult(
                package=self.name, k=job.k, seed=job.seed, status="ok",
                predictions=job.predictions_csv, labels=labels, class_averages=avg_paths,
                n_per_class=counts, elapsed_sec=elapsed, warnings=warnings,
            )
        except Exception as e:
            sink.finish_job(self.name, ok=False, message=str(e))
            return PackageResult(package=self.name, k=job.k, seed=job.seed, status="failed", error=str(e))

    # --- prep, cached once per particle set + wedge config ------------------

    def _ensure_prep(self, job: Job, sink: ProgressSink, opts: dict) -> tuple[Path, Path, Path]:
        prep_dir = job.cache_dir
        prep_dir.mkdir(parents=True, exist_ok=True)
        box, pixel_size = job.particles.box, job.particles.pixel_size

        sink.step(self.name, "prep_ctf", 1, len(self.steps))
        max_tilt = _max_tilt(job)
        ctf_path = prep_dir / f"ctf_t{max_tilt:g}.mrc"
        if not ctf_path.exists():
            save_mrc(ctf_path, build_wedge_ctf(box, max_tilt), pixel_size=pixel_size)

        sink.step(self.name, "prep_star", 2, len(self.steps))
        star_path = prep_dir / f"particles_t{max_tilt:g}.star"
        if not star_path.exists():
            content = build_star(job.particles.particle_dir, list(job.particles.files), ctf_path, pixel_size, box)
            star_path.write_text(content)

        sink.step(self.name, "prep_ref", 3, len(self.steps))
        ref_path = prep_dir / "initial_ref.mrc"
        if not ref_path.exists():
            avg = global_average(job.particles.particle_dir, list(job.particles.files))
            std = avg.std()
            avg = (avg - avg.mean()) / std if std > 0 else avg - avg.mean()
            save_mrc(ref_path, avg.astype(np.float32), pixel_size=pixel_size)

        return ctf_path, star_path, ref_path

    def _classify(self, job: Job, sink: ProgressSink, star_path: Path, ref_path: Path, opts: dict) -> dict[str, int]:
        diam = int(job.particles.box * job.particles.pixel_size * 0.9)
        job.workdir.mkdir(parents=True, exist_ok=True)
        out_prefix = job.workdir / "Class3D" / "run"
        out_prefix.parent.mkdir(parents=True, exist_ok=True)

        # RELION's own --i/--ref/--o/--solvent_mask argument parsing breaks (misidentifies
        # a valid .star path as "not a STAR file") if the path string contains an "@"
        # anywhere -- found via a real machine whose username is "user@domain", which a
        # tmp/output directory can easily inherit. Always pass paths relative to a fixed
        # cwd instead of raw absolute strings, the same pattern already used for EMAN2 --
        # this sidesteps the whole class of "some character in an absolute path confuses
        # the native launcher's own arg parsing" problem rather than chasing this one case.
        cwd = job.cache_dir.parent  # out_dir/relion -- a common ancestor of workdir, cache_dir
        cwd.mkdir(parents=True, exist_ok=True)

        def rel(p: Path) -> str:
            return os.path.relpath(str(p), start=str(cwd))

        threads = str(opts.get("threads") or min(os.cpu_count() or 4, 8))
        argv = [
            self._binary_path(job),
            "--i", rel(star_path), "--ref", rel(ref_path), "--o", rel(out_prefix),
            "--K", str(job.k), "--iter", str(opts["iter"]),
            "--tau2_fudge", str(opts["tau2_fudge"]), "--ini_high", str(opts["ini_high"]),
            "--particle_diameter", str(diam), "--skip_align", "--sym", "C1", "--ctf",
            "--skip_subtomo_multi", "--zero_mask", "--pad", "2", "--norm", "--scale",
            "--solvent_mask", rel(Path(job.mask_path)), "--flatten_solvent",
            "--random_seed", str(job.seed), "--dont_combine_weights_via_disc", "--j", threads,
        ]

        sink.step(self.name, "classify", 4, len(self.steps))
        returncode, _timing = run_streaming(argv, package=self.name, cwd=cwd, log_path=job.log_path, sink=sink)
        if returncode != 0:
            raise RuntimeError(f"relion_refine failed (rc={returncode}) — see {job.log_path}")

        n_iter = int(opts["iter"])
        data_star = out_prefix.parent / f"run_it{n_iter:03d}_data.star"
        if not data_star.exists():
            raise RuntimeError(f"expected output {data_star} not found — see {job.log_path}")

        labels = parse_relion_classes(data_star, star_path)
        if not labels:
            raise RuntimeError(f"no particles parsed from {data_star}")
        return labels
