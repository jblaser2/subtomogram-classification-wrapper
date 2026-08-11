import pytest

from stw.compare.matrix import PackageLabels, build_combined_matrix, consensus_scores
from stw.compare.metrics import align_to_ref, pairwise_ari


def test_ari_identical_labelings_is_one():
    a = {f"p{i}": i % 2 for i in range(20)}
    ari, n = pairwise_ari(a, dict(a))
    assert ari == pytest.approx(1.0)
    assert n == 20


def test_ari_permuted_labels_is_still_one():
    a = {f"p{i}": i % 2 for i in range(20)}
    b = {k: (1 - v) for k, v in a.items()}  # swapped 0<->1, same partition
    ari, _ = pairwise_ari(a, b)
    assert ari == pytest.approx(1.0)


def test_ari_no_shared_particles():
    a = {"p1": 0, "p2": 1}
    b = {"p3": 0, "p4": 1}
    ari, n = pairwise_ari(a, b)
    assert n == 0
    assert ari != ari  # NaN


def test_align_to_ref_recovers_permutation():
    ref = {f"p{i}": i % 3 for i in range(30)}
    # relabel: 0->2, 1->0, 2->1
    remap = {0: 2, 1: 0, 2: 1}
    other = {k: remap[v] for k, v in ref.items()}
    aligned = align_to_ref(ref, other)
    assert aligned == ref


def test_combined_matrix_shape_and_block_bounds():
    pkgs = [
        PackageLabels("A", {f"p{i}": i % 2 + 1 for i in range(10)}),
        PackageLabels("B", {f"p{i}": i % 2 + 1 for i in range(10)}),
    ]
    combined = build_combined_matrix(pkgs)
    assert combined.matrix.shape == (4, 4)  # 2 classes x 2 packages
    assert combined.block_bounds == [(0, 2), (2, 4)]
    # A vs B off-diagonal block should show perfect agreement (ARI=1 case)
    ari, n = combined.ari_lookup[("A", "B")]
    assert ari == pytest.approx(1.0)
    assert n == 10


def test_consensus_scores_full_agreement():
    labels = {f"p{i}": i % 2 for i in range(10)}
    pkgs = [PackageLabels(n, dict(labels)) for n in ["A", "B", "C"]]
    result = consensus_scores(pkgs)
    assert result["n_shared"] == 10
    assert result["n_full_agreement"] == 10
    assert result["counts"][3] == 10


def test_consensus_scores_requires_two_packages():
    with pytest.raises(ValueError):
        consensus_scores([PackageLabels("A", {"p1": 0})])


def test_consensus_scores_partial_disagreement():
    a = {f"p{i}": 0 for i in range(10)}
    b = dict(a)
    b["p0"] = 1  # one disagreement after "alignment" (trivial here, same labels)
    result = consensus_scores([PackageLabels("A", a), PackageLabels("B", b)])
    assert result["n_shared"] == 10
    assert result["n_full_agreement"] == 9
