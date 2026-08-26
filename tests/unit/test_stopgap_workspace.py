"""Unit tests for STOPGAP's pure-Python PC-selection/clustering/tilt-range
logic -- no MATLAB, MPI, or STOPGAP install needed."""
import numpy as np

from stw.adapters.stopgap import cluster_embedding, resolve_pc_cols, resolve_tilt_range
from stw.spec import WedgeKind, WedgeSpec


class _FakeJob:
    def __init__(self, wedge):
        self.wedge = wedge


def test_resolve_pc_cols_default_is_top_n():
    assert resolve_pc_cols(None, ncols=32) == list(range(10))
    assert resolve_pc_cols(None, ncols=5) == list(range(5))  # capped at ncols


def test_resolve_pc_cols_override_is_1_indexed():
    assert resolve_pc_cols("1,2", ncols=32) == [0, 1]
    assert resolve_pc_cols("3", ncols=32) == [2]


def test_resolve_tilt_range_none_wedge_is_full_range():
    job = _FakeJob(WedgeSpec(kind=WedgeKind.NONE))
    assert resolve_tilt_range(job) == (-90.0, 90.0)


def test_resolve_tilt_range_uniform_wedge_passes_through():
    job = _FakeJob(WedgeSpec(kind=WedgeKind.UNIFORM, tilt_min=-60.0, tilt_max=54.0))
    assert resolve_tilt_range(job) == (-60.0, 54.0)


def test_cluster_embedding_separates_two_well_separated_blobs():
    rng = np.random.default_rng(0)
    a = rng.normal(loc=-5.0, scale=0.1, size=(8, 3))
    b = rng.normal(loc=5.0, scale=0.1, size=(8, 3))
    E = np.vstack([a, b])
    labels = cluster_embedding(E, k=2, seed=1, pc_cols=[0, 1, 2])
    assert len(set(labels[:8])) == 1
    assert len(set(labels[8:])) == 1
    assert labels[0] != labels[8]


def test_cluster_embedding_is_reproducible_for_same_seed():
    rng = np.random.default_rng(1)
    E = rng.normal(size=(20, 5))
    labels_a = cluster_embedding(E, k=2, seed=42, pc_cols=[0, 1])
    labels_b = cluster_embedding(E, k=2, seed=42, pc_cols=[0, 1])
    assert (labels_a == labels_b).all()


def test_cluster_embedding_selects_only_requested_columns():
    rng = np.random.default_rng(2)
    signal = np.concatenate([np.full(8, -5.0), np.full(8, 5.0)])
    noise = rng.normal(size=16)
    E = np.column_stack([signal, noise])
    labels_signal = cluster_embedding(E, k=2, seed=1, pc_cols=[0])
    assert len(set(labels_signal[:8])) == 1
    assert len(set(labels_signal[8:])) == 1
