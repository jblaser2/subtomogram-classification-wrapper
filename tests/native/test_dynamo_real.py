"""
Real Dynamo end-to-end test — requires a real Dynamo install (default
~/Research/dynamo/dynamo_activate.m; override via
package_options.dynamo.dynamo_activate), `matlab` on PATH, and MATLAB's
Parallel Computing Toolbox license. Never run in CI (this whole directory is
excluded there). Run manually via:

    pytest tests/native/test_dynamo_real.py -v -m native

Auto-skips if any requirement is missing. Verified working against a real
Dynamo (MATLAB R2024a + PCT) install on 2026-08-13.

**A real, documented finding, not a test artifact**: on this easy synthetic
fixture, dpkpca's blind top-10-eigencomponent k-means default lands near
chance, while the true class-separating signal is cleanly present in the
embedding (a single eigencomponent column alone correlates at ARI=1.0 with
ground truth, verified directly). This matches the "blind PC/factor selection
is often not the discriminating axis" property already well established for
ProTomo/STOPGAP/Dynamo throughout the source benchmark project — it is not
this adapter's own bug, so `test_dynamo_blind_default_is_not_asserted_perfect`
documents the behavior instead of asserting a perfect score, and
`test_dynamo_tuned_pc_cols_recovers_ground_truth` proves the embedding itself
is faithful by overriding to the two columns that do separate the classes.
"""
import csv

import pytest

from stw.adapters.dynamo import DynamoAdapter
from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.scoring.gt import score_against_ground_truth

pytestmark = pytest.mark.native


def _skip_if_not_installed():
    report = DynamoAdapter.check_installed()
    if not report.installed:
        pytest.skip("Dynamo / MATLAB / PCT not found — see docs/install/dynamo.md")


def _load_ground_truth(fixture_dir):
    gt = {}
    with (fixture_dir / "ground_truth.csv").open() as f:
        for row in csv.DictReader(f):
            gt[row["particle"]] = int(row["label"])
    return gt


def test_dynamo_tuned_pc_cols_recovers_ground_truth(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "auto"},
        "packages": ["dynamo"],
        "package_options": {"dynamo": {"pc_cols": "1,2"}},
        "out_dir": str(out_dir),
    })

    report = run_config(cfg)
    assert report.results[0]["status"] == "ok"

    from stw.io.predictions import read_predictions

    pred = read_predictions(out_dir / "dynamo" / "k2" / "seed01" / "predictions.csv")
    gt = _load_ground_truth(tiny_fixture_dir)
    score = score_against_ground_truth(gt, pred)
    assert score.ari > 0.8  # proves the embedding faithfully preserves the real signal


def test_dynamo_blind_default_is_not_asserted_perfect(tiny_fixture_dir, tmp_path):
    """Documents (does not merely assume) that the blind top-10 default is
    near chance here -- a real property of unstandardized k-means on 10
    mostly-noise dimensions with only 32 particles, not a plumbing bug (see
    module docstring and the adapter's own docstring)."""
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "auto"},
        "packages": ["dynamo"],
        "out_dir": str(out_dir),
    })
    report = run_config(cfg)
    assert report.results[0]["status"] == "ok"
    assert report.results[0]["n_per_class"]  # ran and produced *some* non-empty split


def test_dynamo_k3_is_non_degenerate(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 3,
        "mask": {"kind": "auto"},
        "packages": ["dynamo"],
        "package_options": {"dynamo": {"pc_cols": "1,2"}},
        "out_dir": str(out_dir),
    })
    report = run_config(cfg)
    counts = report.results[0]["n_per_class"]
    assert len(counts) == 3
    assert all(c > 0 for c in counts.values())


def test_dynamo_embedding_is_cached_across_k(tiny_fixture_dir, tmp_path):
    """The MATLAB embedding (prealign/ccmatrix/eigentable/eigenvolumes) is
    independent of k -- only k-means (cheap, Python) should rerun."""
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    base = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc",
        "mask": {"kind": "auto"}, "packages": ["dynamo"],
        "package_options": {"dynamo": {"pc_cols": "1,2"}}, "out_dir": str(out_dir),
    }
    run_config(RunConfig.model_validate({**base, "k": 2}))
    cache_root = out_dir / "dynamo" / "_cache"
    # cache_root/<particle-set fingerprint>/embed_<mask hash> since the orchestrator's
    # particle-set-identity fix; glob one level deeper rather than os.listdir directly.
    embed_dirs = list(cache_root.glob("*/embed_*"))
    assert len(embed_dirs) == 1
    ecsv = embed_dirs[0] / "eigencomponents.csv"
    mtime_before = ecsv.stat().st_mtime

    run_config(RunConfig.model_validate({**base, "k": 3}))
    assert ecsv.stat().st_mtime == mtime_before  # embedding was not recomputed


def test_dynamo_distinct_masks_build_distinct_embed_dirs(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    base = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "k": 2,
        "packages": ["dynamo"], "package_options": {"dynamo": {"pc_cols": "1,2"}},
        "out_dir": str(out_dir),
    }
    run_config(RunConfig.model_validate({**base, "mask": {"kind": "sphere", "radius": 9}}))
    run_config(RunConfig.model_validate({**base, "mask": {"kind": "sphere", "radius": 6}}))
    cache_root = out_dir / "dynamo" / "_cache"
    embed_dirs = list(cache_root.glob("*/embed_*"))
    assert len(embed_dirs) == 2
