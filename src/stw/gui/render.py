"""On-demand PNG rendering for the GUI: class-average MRCs aren't browser-
displayable, so each result's `class_averages` dict is rendered to one panel
PNG per request (cheap — a handful of small central-slice images). Requires
the `viz` extra (matplotlib); the `gui` extra already pulls it in."""
from __future__ import annotations

import io
from pathlib import Path

import mrcfile
import numpy as np


def render_class_average_panel(
    class_averages: dict[str, str], n_per_class: dict[str, int], out_png: str | Path, title: str
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    classes = sorted(class_averages, key=int)
    fig, axes = plt.subplots(1, len(classes), figsize=(3.2 * len(classes), 3.6), squeeze=False)
    for ax, cls in zip(axes[0], classes):
        with mrcfile.open(class_averages[cls], permissive=True) as m:
            vol = np.asarray(m.data)
        mid = vol.shape[0] // 2
        ax.imshow(vol[mid], cmap="gray")
        n = n_per_class.get(cls, "?")
        ax.set_title(f"class {cls} (n={n})", fontsize=10)
        ax.axis("off")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_png), dpi=130, bbox_inches="tight")
    plt.close(fig)


def render_volume_slice_png(vol: np.ndarray, title: str) -> bytes:
    """Central Z-slice of one volume, returned as in-memory PNG bytes (no
    filesystem write -- used for the dataset preview, which isn't tied to
    any run and has nothing sensible to cache it under)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mid = vol.shape[0] // 2
    fig, ax = plt.subplots(figsize=(3.6, 3.6))
    ax.imshow(vol[mid], cmap="gray")
    ax.set_title(title, fontsize=10)
    ax.axis("off")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
