"""QC overlay rendering — a 3-orthogonal-slice contour plot of a mask on the
global average, ported from `render_overlay` in STA's `make_diff_sphere_mask.py`.
Requires the `viz` extra (matplotlib)."""
from __future__ import annotations

from pathlib import Path

import numpy as np


def render_mask_overlay(avg: np.ndarray, mask: np.ndarray, out_png: str | Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    box = avg.shape[0]
    c = box // 2
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5))
    slices = [
        ("Z", (c, slice(None), slice(None))),
        ("Y", (slice(None), c, slice(None))),
        ("X", (slice(None), slice(None), c)),
    ]
    for ax, (plane, sl) in zip(axes, slices):
        ax.imshow(avg[sl], cmap="gray")
        ax.contour(mask[sl], levels=[0.5], colors="red", linewidths=1.5)
        ax.set_title(f"{plane}-slice @ {c}")
        ax.axis("off")
    fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_png), dpi=140, bbox_inches="tight")
    plt.close(fig)


def mask_summary(mask: np.ndarray) -> dict:
    frac = float((mask > 0.5).sum()) / mask.size
    return {"box_fraction": frac, "active_voxels": int((mask > 0.5).sum()), "shape": list(mask.shape)}
