"""
RunConfig — what an end user actually writes (YAML/JSON), validated with pydantic
so the future GUI can render a form straight from RunConfig.model_json_schema().
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from stw.spec import AlignmentState, MaskKind, WedgeKind


class MaskConfig(BaseModel):
    kind: MaskKind = MaskKind.AUTO
    path: Path | None = None
    center: tuple[float, float, float] | None = None
    radius: float | None = None
    half_height: float | None = None
    axis: Literal["x", "y", "z"] = "z"
    edge: float = 3.0


class WedgeConfig(BaseModel):
    kind: WedgeKind = WedgeKind.NONE
    tilt_min: float | None = None
    tilt_max: float | None = None
    tilt_axis: Literal["x", "y"] = "y"
    table: Path | None = None


class RunConfig(BaseModel):
    particles: Path
    pattern: str = "*.mrc"
    pixel_size: float | None = None
    subsample: int | None = None  # cap particle count via a random draw -- see ParticleSet.subsample()
    subsample_seed: int = 0
    k: int | list[int] = 2
    mask: MaskConfig = Field(default_factory=MaskConfig)
    wedge: WedgeConfig = Field(default_factory=WedgeConfig)
    alignment_state: AlignmentState = AlignmentState.FINE
    packages: list[str]
    mode: Literal["native", "preview"] = "native"
    seeds: int | list[int] = 1
    out_dir: Path = Path("./stw_out")
    package_options: dict[str, dict[str, Any]] = Field(default_factory=dict)
    jobs: int = 1
    on_missing_requirement: Literal["skip", "fail"] = "skip"
    ground_truth: Path | None = None

    @field_validator("packages")
    @classmethod
    def _non_empty_packages(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("packages must list at least one package name")
        return v

    @field_validator("subsample")
    @classmethod
    def _valid_subsample(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError(f"subsample must be >= 1, got {v}")
        return v

    @field_validator("k")
    @classmethod
    def _valid_k(cls, v: int | list[int]) -> int | list[int]:
        values = v if isinstance(v, list) else [v]
        for k in values:
            if k < 1:
                raise ValueError(f"k must be >= 1, got {k}")
        return v

    @model_validator(mode="after")
    def _mask_requires_params(self) -> RunConfig:
        m = self.mask
        if m.kind == MaskKind.SPHERE and m.radius is None:
            raise ValueError("mask.kind=sphere requires mask.radius")
        if m.kind == MaskKind.CYLINDER and (m.radius is None or m.half_height is None):
            raise ValueError("mask.kind=cylinder requires mask.radius and mask.half_height")
        if m.kind == MaskKind.FILE and m.path is None:
            raise ValueError("mask.kind=file requires mask.path")
        if self.wedge.kind == WedgeKind.UNIFORM and (
            self.wedge.tilt_min is None or self.wedge.tilt_max is None
        ):
            raise ValueError("wedge.kind=uniform requires wedge.tilt_min and wedge.tilt_max")
        if self.wedge.kind == WedgeKind.PER_PARTICLE and self.wedge.table is None:
            raise ValueError("wedge.kind=per_particle requires wedge.table")
        return self

    @property
    def k_values(self) -> list[int]:
        return self.k if isinstance(self.k, list) else [self.k]

    @property
    def seed_values(self) -> list[int]:
        return self.seeds if isinstance(self.seeds, list) else list(range(1, self.seeds + 1))

    @classmethod
    def from_file(cls, path: str | Path) -> RunConfig:
        p = Path(path)
        text = p.read_text()
        data = yaml.safe_load(text) if p.suffix in (".yaml", ".yml") else json.loads(text)
        return cls.model_validate(data)

    def to_json_schema(self) -> dict[str, Any]:
        """Used by `stw init --schema` today and the GUI's form renderer later."""
        return self.model_json_schema()
