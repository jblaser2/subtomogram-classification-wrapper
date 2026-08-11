"""
The single generic "assignments + particle volumes -> class-average volumes"
implementation. STA had this logic duplicated near-verbatim across at least
three places (`gen_t4p_class_avg_panels.py`'s `compute_class_avg_from_particles`,
`make_diff_sphere_mask.py`'s `class_average`, `fsc_core.py`'s
`load_particles_for_class`); this is the one copy every adapter/orchestrator
path here uses instead.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from stw.io.mrc import load_mrc


class EmptyClassError(ValueError):
    """Raised when a requested class label has zero assigned particles."""


def class_averages(
    particle_dir: str | Path,
    labels: dict[str, int],
    *,
    normalize: bool = False,
) -> tuple[dict[int, np.ndarray], dict[int, int]]:
    """Stream-average particle volumes grouped by integer class label.

    Args:
        particle_dir: directory containing the particle MRC files.
        labels: {filename: class_int}. Filenames are resolved under `particle_dir`.
        normalize: if True, zero-mean/unit-std normalize each average (useful when
            comparing packages with very different intensity scales).

    Returns:
        (averages, counts) — averages maps class_int -> mean volume (float32);
        counts maps class_int -> number of particles that contributed.
    """
    d = Path(particle_dir)
    acc: dict[int, np.ndarray] = {}
    # Initialized for every class label the caller asked for, not just ones that
    # end up with a loaded file — otherwise a class whose every file is missing
    # never appears in `counts` at all and EmptyClassError never fires.
    counts: dict[int, int] = {cls: 0 for cls in set(labels.values())}

    for filename, cls in labels.items():
        path = d / filename
        if not path.exists():
            continue
        vol = load_mrc(path)
        if cls not in acc:
            acc[cls] = np.zeros_like(vol, dtype=np.float64)
        acc[cls] += vol
        counts[cls] += 1

    empty = [cls for cls, n in counts.items() if n == 0]
    if empty:
        raise EmptyClassError(f"class(es) with zero particles: {sorted(empty)}")

    averages = {cls: (acc[cls] / counts[cls]).astype(np.float32) for cls in acc}
    if normalize:
        for cls, vol in averages.items():
            std = vol.std()
            averages[cls] = ((vol - vol.mean()) / std if std > 0 else vol - vol.mean()).astype(
                np.float32
            )
    return averages, counts


def global_average(particle_dir: str | Path, files: list[str]) -> np.ndarray:
    """Unweighted average of every listed particle — used by the blind/auto mask
    builder, which needs a density envelope with no class labels at all."""
    labels = {f: 0 for f in files}
    averages, _ = class_averages(particle_dir, labels)
    return averages[0]
