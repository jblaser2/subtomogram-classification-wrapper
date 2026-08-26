"""On-demand PNG rendering for the GUI: class-average MRCs aren't browser-
displayable, so each result's `class_averages` dict is rendered to one panel
PNG per request (cheap — a handful of small central-slice images). Requires
the `viz` extra (matplotlib); the `gui` extra already pulls it in."""
from __future__ import annotations

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
