"""Unit tests for Dynamo's pure-Python table-building/PC-selection/clustering
logic -- no MATLAB or Dynamo install needed."""
import numpy as np

from stw.adapters.dynamo import build_identity_tbl, cluster_embedding, resolve_pc_cols


def test_build_identity_tbl_has_35_columns_per_row():
    tbl = build_identity_tbl(3)
    lines = tbl.strip().splitlines()
    assert len(lines) == 3
    for line in lines:
        assert len(line.split()) == 35


def test_build_identity_tbl_tag_and_flags():
    tbl = build_identity_tbl(2)
    lines = tbl.strip().splitlines()
    row1 = lines[0].split()
    assert row1[0] == "1"  # tag
    assert row1[1] == "1"  # aligned/malign flag
    assert row1[5] == "1"  # cpu flag
    row2 = lines[1].split()
    assert row2[0] == "2"
    # everything else stays zero
    assert all(v == "0" for i, v in enumerate(row1) if i not in (0, 1, 5))


def test_resolve_pc_cols_default_is_top_n():
    assert resolve_pc_cols(None, ncols=32) == list(range(10))
    assert resolve_pc_cols(None, ncols=5) == list(range(5))  # capped at ncols


def test_resolve_pc_cols_override_is_1_indexed():
    assert resolve_pc_cols("1,2", ncols=32) == [0, 1]
    assert resolve_pc_cols("1,2,3,4,5,6,7,8,10", ncols=32) == [0, 1, 2, 3, 4, 5, 6, 7, 9]


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
    # a signal-bearing column and a pure-noise column -- selecting only the
    # noise column should NOT recover the true split.
    rng = np.random.default_rng(2)
    signal = np.concatenate([np.full(8, -5.0), np.full(8, 5.0)])
    noise = rng.normal(size=16)
    E = np.column_stack([signal, noise])
    labels_signal = cluster_embedding(E, k=2, seed=1, pc_cols=[0])
    assert len(set(labels_signal[:8])) == 1
    assert len(set(labels_signal[8:])) == 1
