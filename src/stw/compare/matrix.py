"""
N-way cross-package agreement matrix + per-particle consensus scoring.

Generalizes STA's `gen_cross_pkg_correlation.py`: that script's math
(`build_combined_matrix`, `plot_consensus`) was already package-count-agnostic,
but its package *registry* was a hardcoded list of (name, csv_path) tuples per
internal dataset. Here the only input is `list[PackageLabels]` — whatever the
orchestrator actually ran, nothing hardcoded.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from stw.compare.metrics import align_to_ref, pairwise_ari


@dataclass(frozen=True)
class PackageLabels:
    name: str
    labels: dict[str, int]  # {particle: class_int}


@dataclass
class CombinedMatrix:
    matrix: np.ndarray  # NaN on diagonal (self) blocks
    counts: np.ndarray
    tick_labels: list[str]
    block_bounds: list[tuple[int, int]]  # (start, end) row/col index per package
    package_names: list[str]
    ari_lookup: dict[tuple[str, str], tuple[float, int]] = field(default_factory=dict)


def build_combined_matrix(packages: list[PackageLabels]) -> CombinedMatrix:
    """One matrix covering every package pair: rows/cols = every (package,
    class) combination. Off-diagonal blocks hold row-normalized recall;
    diagonal (self) blocks are trivial and left NaN (a size reference only)."""
    class_lists = [sorted(set(p.labels.values())) for p in packages]
    sizes = [len(c) for c in class_lists]
    offsets = list(np.cumsum([0] + sizes[:-1]))
    n = sum(sizes)

    tick_labels: list[str] = []
    block_bounds: list[tuple[int, int]] = []
    for p, offset, classes in zip(packages, offsets, class_lists):
        block_bounds.append((offset, offset + len(classes)))
        tick_labels.extend(f"{p.name}\ncls {c}" for c in classes)

    mat = np.full((n, n), np.nan)
    counts = np.zeros((n, n), dtype=int)
    ari_lookup: dict[tuple[str, str], tuple[float, int]] = {}

    for i, (pa, oi, cls_a) in enumerate(zip(packages, offsets, class_lists)):
        for j, (pb, oj, cls_b) in enumerate(zip(packages, offsets, class_lists)):
            if i == j:
                for a_idx, a in enumerate(cls_a):
                    counts[oi + a_idx, oi + a_idx] = sum(1 for v in pa.labels.values() if v == a)
                continue
            shared = sorted(set(pa.labels) & set(pb.labels))
            if not shared:
                continue
            v_a = [pa.labels[k] for k in shared]
            v_b = [pb.labels[k] for k in shared]
            cm = np.zeros((len(cls_a), len(cls_b)), dtype=int)
            for a, b in zip(v_a, v_b):
                cm[cls_a.index(a), cls_b.index(b)] += 1
            row_sums = cm.sum(axis=1, keepdims=True).clip(min=1)
            mat[oi : oi + len(cls_a), oj : oj + len(cls_b)] = cm.astype(float) / row_sums
            counts[oi : oi + len(cls_a), oj : oj + len(cls_b)] = cm
            if i < j:
                score, n_shared = pairwise_ari(pa.labels, pb.labels)
                ari_lookup[(pa.name, pb.name)] = (score, n_shared)

    return CombinedMatrix(
        matrix=mat,
        counts=counts,
        tick_labels=tick_labels,
        block_bounds=block_bounds,
        package_names=[p.name for p in packages],
        ari_lookup=ari_lookup,
    )


def consensus_scores(packages: list[PackageLabels]) -> dict:
    """For each particle shared by every package, how many packages agree with
    a chosen reference (the first package), after Hungarian label alignment.

    Returns {"n_shared": int, "counts": {agreement_count: n_particles},
    "reference": name, "n_full_agreement": int}.
    """
    if len(packages) < 2:
        raise ValueError("consensus scoring needs at least 2 packages")

    ref = packages[0]
    aligned = [ref.labels] + [align_to_ref(ref.labels, p.labels) for p in packages[1:]]

    common = set(aligned[0])
    for a in aligned[1:]:
        common &= set(a)
    common_sorted = sorted(common)

    if not common_sorted:
        return {"n_shared": 0, "counts": {}, "reference": ref.name, "n_full_agreement": 0}

    agreement = []
    for particle in common_sorted:
        ref_label = aligned[0][particle]
        n_agree = sum(1 for a in aligned if a[particle] == ref_label)
        agreement.append(n_agree)

    counts: dict[int, int] = {}
    for v in range(1, len(packages) + 1):
        counts[v] = agreement.count(v)

    return {
        "n_shared": len(common_sorted),
        "counts": counts,
        "reference": ref.name,
        "n_full_agreement": counts.get(len(packages), 0),
    }
