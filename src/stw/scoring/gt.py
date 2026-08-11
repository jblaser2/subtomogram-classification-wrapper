"""
Optional ground-truth scoring (ARI/AMI/V-measure/Hungarian-matched accuracy),
ported from STA's `synthetic_metrics.py`. Real biologist data won't usually
have ground truth — this exists for the tool's own self-tests on synthetic
fixtures, and for power users validating against a known answer.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import (
    adjusted_mutual_info_score,
    adjusted_rand_score,
    confusion_matrix,
    v_measure_score,
)


@dataclass
class GroundTruthScore:
    ari: float
    ami: float
    v_measure: float
    accuracy: float
    n_particles: int
    confusion: np.ndarray


def hungarian_accuracy(gt_labels: list, pred_labels: list) -> tuple[float, np.ndarray]:
    gt_u = sorted(set(gt_labels))
    pr_u = sorted(set(pred_labels))
    gt_idx = np.array([gt_u.index(g) for g in gt_labels])
    pr_idx = np.array([pr_u.index(p) for p in pred_labels])
    cm = confusion_matrix(gt_idx, pr_idx, labels=range(len(gt_u)))
    n = max(len(gt_u), len(pr_u))
    padded = np.zeros((n, n), dtype=cm.dtype)
    padded[: cm.shape[0], : cm.shape[1]] = cm
    row_ind, col_ind = linear_sum_assignment(-padded)
    acc = padded[row_ind, col_ind].sum() / len(gt_labels)
    return float(acc), cm


def score_against_ground_truth(gt: dict[str, int], pred: dict[str, int]) -> GroundTruthScore:
    """Both args map {particle: label}; scored over their shared keys."""
    keys = sorted(set(gt) & set(pred))
    if not keys:
        raise ValueError("no shared particles between ground truth and predictions")
    gt_labels = [gt[k] for k in keys]
    pred_labels = [pred[k] for k in keys]
    acc, cm = hungarian_accuracy(gt_labels, pred_labels)
    return GroundTruthScore(
        ari=float(adjusted_rand_score(gt_labels, pred_labels)),
        ami=float(adjusted_mutual_info_score(gt_labels, pred_labels)),
        v_measure=float(v_measure_score(gt_labels, pred_labels)),
        accuracy=acc,
        n_particles=len(keys),
        confusion=cm,
    )
