"""
AlignConfig — what a user writes to run `stw align`. Deliberately separate
from RunConfig (not a variant of it): alignment isn't a classification
adapter (no k, no seed, no class labels), and its mask plays a genuinely
different role from a classification mask -- see the module docstring in
`pytom_frm.py` for why reusing a classification mask for alignment is a
real, previously-proven-harmful mistake, not just a style preference.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from stw.config import MaskConfig, WedgeConfig
from stw.spec import MaskKind


class AlignConfig(BaseModel):
    particles: Path
    pattern: str = "*.mrc"
    pixel_size: float | None = None
    mask: MaskConfig = Field(default_factory=lambda: MaskConfig(kind=MaskKind.AUTO))
    wedge: WedgeConfig = Field(default_factory=WedgeConfig)
    out_dir: Path = Path("./stw_align_out")
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _mask_required(self) -> AlignConfig:
        if self.mask.kind == MaskKind.NONE:
            raise ValueError("stw align requires a mask (mask.kind=none is not allowed)")
        return self

    @classmethod
    def from_file(cls, path: str | Path) -> AlignConfig:
        p = Path(path)
        text = p.read_text()
        data = yaml.safe_load(text) if p.suffix in (".yaml", ".yml") else json.loads(text)
        return cls.model_validate(data)
