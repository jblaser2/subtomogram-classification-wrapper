"""Thin, consistent MRC read/write helpers used across masks/averaging/panels."""
from __future__ import annotations

from pathlib import Path

import mrcfile
import numpy as np


def load_mrc(path: str | Path) -> np.ndarray:
    with mrcfile.open(str(path), permissive=True) as m:
        return np.asarray(m.data).astype(np.float32).copy()


def save_mrc(path: str | Path, data: np.ndarray, pixel_size: float | None = None) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with mrcfile.new(str(p), overwrite=True) as m:
        m.set_data(data.astype(np.float32))
        if pixel_size is not None:
            m.voxel_size = pixel_size
