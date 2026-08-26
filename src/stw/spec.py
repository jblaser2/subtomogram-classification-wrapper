"""
Core value types every adapter and CLI command shares: what particles look like,
what a mask/wedge/alignment-state input means, and what one unit of work (a Job)
carries into an Adapter.run().

These are intentionally plain, hashable dataclasses/enums (no pydantic here) — they
are also constructed internally by the orchestrator, not just parsed from user YAML
(that's config.py's job).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class AlignmentState(str, Enum):
    UNALIGNED = "unaligned"
    ROUGH = "rough"
    FINE = "fine"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class MaskKind(str, Enum):
    NONE = "none"
    SPHERE = "sphere"
    CYLINDER = "cylinder"
    FILE = "file"
    AUTO = "auto"  # blind density-envelope sphere, no labels needed

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class WedgeKind(str, Enum):
    NONE = "none"
    UNIFORM = "uniform"
    PER_PARTICLE = "per_particle"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ParticleSetError(ValueError):
    """Raised when a particle directory fails validation (empty, unreadable,
    inconsistent box size, or missing/garbage pixel size)."""


@dataclass(frozen=True)
class MaskSpec:
    kind: MaskKind = MaskKind.AUTO
    path: Path | None = None  # kind=FILE
    center: tuple[float, float, float] | None = None  # voxels (z, y, x); None -> box center
    radius: float | None = None
    half_height: float | None = None  # CYLINDER only
    axis: str = "z"  # CYLINDER only: "x" | "y" | "z"
    edge: float = 3.0  # soft cosine falloff width, voxels

    def __post_init__(self) -> None:
        if self.kind == MaskKind.SPHERE and self.radius is None:
            raise ValueError("mask kind=sphere requires radius")
        if self.kind == MaskKind.CYLINDER and (self.radius is None or self.half_height is None):
            raise ValueError("mask kind=cylinder requires radius and half_height")
        if self.kind == MaskKind.FILE and self.path is None:
            raise ValueError("mask kind=file requires path")
        if self.axis not in ("x", "y", "z"):
            raise ValueError(f"mask axis must be x/y/z, got {self.axis!r}")

    def cache_key(self) -> str:
        payload = (
            f"{self.kind}|{self.path}|{self.center}|{self.radius}|"
            f"{self.half_height}|{self.axis}|{self.edge}"
        )
        return hashlib.sha1(payload.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class WedgeSpec:
    kind: WedgeKind = WedgeKind.NONE
    tilt_min: float | None = None  # degrees, UNIFORM
    tilt_max: float | None = None
    tilt_axis: str = "y"
    table: Path | None = None  # per_particle: csv (particle,tilt_min,tilt_max[,tilt_axis])

    def __post_init__(self) -> None:
        if self.kind == WedgeKind.UNIFORM and (self.tilt_min is None or self.tilt_max is None):
            raise ValueError("wedge kind=uniform requires tilt_min and tilt_max")
        if self.kind == WedgeKind.PER_PARTICLE and self.table is None:
            raise ValueError("wedge kind=per_particle requires table")


@dataclass(frozen=True)
class ParticleSet:
    particle_dir: Path
    pattern: str
    files: tuple[str, ...]  # sorted basenames — the canonical row order every adapter must honor
    box: int
    pixel_size: float
    poses: Path | None = None

    @classmethod
    def discover(
        cls, particle_dir: str | Path, pattern: str = "*.mrc", pixel_size: float | None = None
    ) -> ParticleSet:
        import mrcfile

        # .resolve(): several adapters pass job.particles.particle_dir as a subprocess
        # ARGUMENT while running that subprocess with a different cwd -- a relative path
        # here would re-resolve against the wrong directory (the same class of bug fixed
        # for out_dir in orchestrator.run_config()).
        d = Path(particle_dir).resolve()
        if not d.is_dir():
            raise ParticleSetError(f"particle directory does not exist: {d}")
        files = sorted(p.name for p in d.glob(pattern))
        if not files:
            raise ParticleSetError(f"no files matching {pattern!r} in {d}")

        boxes: set[int] = set()
        apix_values: list[float] = []
        for name in files:
            with mrcfile.open(str(d / name), permissive=True, header_only=True) as m:
                shape = m.data.shape if m.data is not None else m.header.shape
                dims = {int(m.header.nx), int(m.header.ny), int(m.header.nz)}
                if len(dims) != 1:
                    raise ParticleSetError(f"{name} is not a cubic box: {shape}")
                boxes.add(dims.pop())
                apix_values.append(float(m.voxel_size.x))

        if len(boxes) != 1:
            raise ParticleSetError(f"inconsistent box sizes across particles: {sorted(boxes)}")
        box = boxes.pop()

        resolved_apix = pixel_size
        if resolved_apix is None:
            distinct = {round(a, 4) for a in apix_values}
            distinct.discard(0.0)
            distinct.discard(1.0)  # mrcfile's default when a header never set voxel_size
            if len(distinct) == 1:
                resolved_apix = distinct.pop()
            else:
                raise ParticleSetError(
                    "could not resolve a pixel size from MRC headers (missing, inconsistent, "
                    "or left at the mrcfile default of 1.0 A/px) — pass pixel_size explicitly"
                )

        return cls(particle_dir=d, pattern=pattern, files=tuple(files), box=box, pixel_size=resolved_apix)

    def __len__(self) -> int:
        return len(self.files)

    def path_for(self, filename: str) -> Path:
        return self.particle_dir / filename


@dataclass(frozen=True)
class Job:
    """One fully-resolved unit of work: a single (package, k, seed) run."""

    package: str
    particles: ParticleSet
    mask_path: Path | None
    mask_spec: MaskSpec
    wedge: WedgeSpec
    alignment_state: AlignmentState
    k: int
    seed: int
    workdir: Path
    cache_dir: Path
    options: dict = field(default_factory=dict)
    threads: int = 1
    gpus: tuple[int, ...] = ()

    @property
    def predictions_csv(self) -> Path:
        return self.workdir / "predictions.csv"

    @property
    def log_path(self) -> Path:
        return self.workdir / "run.log"
