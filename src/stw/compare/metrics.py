"""Pairwise agreement math, ported from STA's `gen_cross_pkg_correlation.py`
(`align_to_ref`, its inline ARI calls) — package-agnostic, works on plain
{particle: class_int} dicts."""
from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import adjusted_rand_score


def _shared(a: dict[str, int], b: dict[str, int]) -> list[str]:
    return sorted(set(a) & set(b))


def pairwise_ari(a: dict[str, int], b: dict[str, int]) -> tuple[float, int]:
    """Adjusted Rand Index between two packages' assignments, restricted to
    particles both packages actually classified. Returns (ari, n_shared)."""
    keys = _shared(a, b)
    if not keys:
        return float("nan"), 0
    va = [a[k] for k in keys]
    vb = [b[k] for k in keys]
    return float(adjusted_rand_score(va, vb)), len(keys)


def align_to_ref(ref: dict[str, int], other: dict[str, int]) -> dict[str, int]:
    """Relabel `other` to maximize agreement with `ref` (Hungarian assignment on
    the co-occurrence matrix). Used before computing per-particle consensus,
    since two packages can find the "same" partition with swapped class numbers."""
    keys = _shared(ref, other)
    if not keys:
        return {}
    v_ref = [ref[k] for k in keys]
    v_other = [other[k] for k in keys]

    cls_ref = sorted(set(v_ref))
    cls_other = sorted(set(v_other))
    cm = np.zeros((len(cls_ref), len(cls_other)), dtype=int)
    for r, o in zip(v_ref, v_other):
        cm[cls_ref.index(r), cls_other.index(o)] += 1

    row_ind, col_ind = linear_sum_assignment(-cm)
    mapping = {cls_other[col_ind[i]]: cls_ref[row_ind[i]] for i in range(len(row_ind))}
    # classes the Hungarian assignment didn't map (more "other" classes than "ref"
    # classes) keep their original label rather than being dropped.
    return {k: mapping.get(other[k], other[k]) for k in other}
