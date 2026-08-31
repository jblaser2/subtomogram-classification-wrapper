"""
Real ProTomo end-to-end test — requires ProTomo/I3 3.1.0's own setup script
(default ~/Applications/protomo-3.1.0/setup.sh; override via
package_options.protomo.protomo_setup) and a MATLAB install for its bundled
MKL library (default search: /usr/local/MATLAB/R2024a, then
~/Applications/matlab; override via package_options.protomo.matlab_root).
Never run in CI (this whole directory is excluded there). Run manually via:

    pytest tests/native/test_protomo_real.py -v -m native

Auto-skips if either requirement isn't found. Verified working against real
ProTomo/I3 3.1.0 on 2026-08-13: k=2 recovers the fixture's true 16/16 split
exactly (ARI=1.0), k=3 gives a non-degenerate 8/8/16 split, two different
mask configs build two distinct cached prep workspaces (no stale-cache
reuse), and a cached second run at the same k is roughly 7x faster (series
build/mask-convert/subvolinitial.sh/subvolsvd.sh are all skipped; only
`cycle-000/param.sh`'s rewrite + subvolhac.sh/tomoinfo re-run).
"""
import csv

import pytest

from stw.adapters.protomo import ProTomoAdapter
from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.scoring.gt import score_against_ground_truth

pytestmark = pytest.mark.native


def _skip_if_not_installed():
    report = ProTomoAdapter.check_installed()
    if not report.installed:
        pytest.skip("ProTomo setup.sh / MATLAB MKL not found — see docs/install/protomo.md")


def _load_ground_truth(fixture_dir):
    gt = {}
    with (fixture_dir / "ground_truth.csv").open() as f:
        for row in csv.DictReader(f):
            gt[row["particle"]] = int(row["label"])
    return gt


def test_protomo_end_to_end_on_fixture(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "auto"},
        "packages": ["protomo"],
        "out_dir": str(out_dir),
    })

    report = run_config(cfg)

    assert report.results[0]["status"] == "ok"
    assert report.results[0]["n_per_class"]

    from stw.io.predictions import read_predictions

    pred = read_predictions(out_dir / "protomo" / "k2" / "seed01" / "predictions.csv")
    gt = _load_ground_truth(tiny_fixture_dir)
    score = score_against_ground_truth(gt, pred)
    assert score.ari > 0.8  # matches the documented ARI=1.0 on this easy fixture


def test_protomo_k3_is_non_degenerate(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 3,
        "mask": {"kind": "auto"},
        "packages": ["protomo"],
        "out_dir": str(out_dir),
    })
    report = run_config(cfg)
    counts = report.results[0]["n_per_class"]
    assert len(counts) == 3
    assert all(c > 0 for c in counts.values())


def test_protomo_prep_is_cached_across_k(tiny_fixture_dir, tmp_path):
    """subvolsvd.sh's expensive SVD is cached per mask, independent of k --
    only cycle-000/param.sh + subvolhac.sh are redone per (k, seed)."""
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    base = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc",
        "mask": {"kind": "auto"}, "packages": ["protomo"], "out_dir": str(out_dir),
    }
    run_config(RunConfig.model_validate({**base, "k": 2}))
    cache_root = out_dir / "protomo" / "_cache"
    prep_dirs = list(cache_root.glob("*/prep_*"))
    assert len(prep_dirs) == 1
    coo_before = (prep_dirs[0] / "process" / "cycle-000" / "stw-000.coo").stat().st_mtime

    run_config(RunConfig.model_validate({**base, "k": 3}))  # different k, same mask
    coo_after = (prep_dirs[0] / "process" / "cycle-000" / "stw-000.coo").stat().st_mtime
    assert coo_after == coo_before  # svd was not recomputed for the new k


def test_protomo_distinct_masks_build_distinct_prep_dirs(tiny_fixture_dir, tmp_path):
    out_dir = tmp_path / "out"
    _skip_if_not_installed()
    base = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc",
        "k": 2, "packages": ["protomo"], "out_dir": str(out_dir),
    }
    run_config(RunConfig.model_validate({**base, "mask": {"kind": "sphere", "radius": 9}}))
    run_config(RunConfig.model_validate({**base, "mask": {"kind": "sphere", "radius": 6}}))
    cache_root = out_dir / "protomo" / "_cache"
    prep_dirs = list(cache_root.glob("*/prep_*"))
    assert len(prep_dirs) == 2
