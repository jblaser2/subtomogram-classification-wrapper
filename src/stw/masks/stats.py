"""
Memory-safety heuristics, lifted near-verbatim from STA's
`scripts/run/adapters/_base.py`. These exist because a wide-open mask blew up
a MATLAB parpool's per-worker memory footprint in that project (see its
`ram-oom-dynamo-parpool-nomask` memory note) — any adapter that parallelizes
over full per-particle volumes (parpool/MPI ranks/thread pools) should scale
its worker count off the mask's active-voxel fraction, not just particle count.
"""
from __future__ import annotations

from pathlib import Path

import mrcfile
import numpy as np


def mask_active_frac(mask_path: str | Path) -> float:
    """Fraction of mask voxels > 0.5."""
    with mrcfile.open(str(mask_path), permissive=True) as m:
        data = np.asarray(m.data)
    return float((data > 0.5).sum()) / data.size


def safe_worker_count(mask_path: str | Path, tiers: tuple[int, int, int] = (2, 4, 8)) -> int:
    """Pick a worker/rank count from mask active-voxel fraction: wide-open mask
    (>0.5 active) -> tiers[0] (most conservative), moderate (>0.15) -> tiers[1],
    tight mask -> tiers[2] (least conservative).
    """
    frac = mask_active_frac(mask_path)
    if frac > 0.5:
        return tiers[0]
    if frac > 0.15:
        return tiers[1]
    return tiers[2]
