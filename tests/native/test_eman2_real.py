"""
Real EMAN2 end-to-end test — requires the `eman2` conda env, never run in CI
(this whole directory is excluded there). Run manually via:

    pytest tests/native/test_eman2_real.py -v

Auto-skips if the `eman2` conda env isn't found, so this is safe to leave in
the tree for contributors without EMAN2 installed. Verified working against
the real `eman2` conda env on 2026-08-12: k=2 recovers the fixture's true
16/16 split exactly (ARI=1.0), k=3 gives a non-degenerate 4/16/12 split, and
a cached second run drops from ~12s to ~5s (prep steps skipped).
"""
import csv

import pytest

from stw.adapters.eman2 import EMAN2Adapter
from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.scoring.gt import score_against_ground_truth

pytestmark = pytest.mark.native


def _skip_if_not_installed():
    report = EMAN2Adapter.check_installed()
    if not report.installed:
        pytest.skip("eman2 conda env not found — see docs/install/eman2.md")


def _load_ground_truth(fixture_dir):
    gt = {}
    with (fixture_dir / "ground_truth.csv").open() as f:
        for row in csv.DictReader(f):
            gt[row["particle"]] = int(row["label"])
    return gt


def test_eman2_end_to_end_on_fixture(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "auto"},
        "packages": ["eman2"],
        "out_dir": str(out_dir),
        "package_options": {"eman2": {"maxres": 20.0, "restarget": 15.0, "nbasis": 8}},
    })

    report = run_config(cfg)

    assert report.results[0]["status"] == "ok"
    assert report.results[0]["n_per_class"]

    from stw.io.predictions import read_predictions

    pred = read_predictions(out_dir / "eman2" / "k2" / "seed01" / "predictions.csv")
    gt = _load_ground_truth(tiny_fixture_dir)
    score = score_against_ground_truth(gt, pred)
    assert score.ari > 0.8  # matches the documented ARI=1.0 on this easy fixture


def test_eman2_prep_is_cached_across_runs(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "packages": ["eman2"],
        "out_dir": str(out_dir),
        "package_options": {"eman2": {"maxres": 20.0, "restarget": 15.0, "nbasis": 8}},
    })
    run_config(cfg)
    first_elapsed = None
    import json

    report_path = out_dir / "run_report.json"
    first_elapsed = json.loads(report_path.read_text())["results"][0]["elapsed_sec"]

    run_config(cfg)  # second run should reuse cached prep (particles.hdf, consensus average, mask)
    second_elapsed = json.loads(report_path.read_text())["results"][0]["elapsed_sec"]

    assert second_elapsed < first_elapsed


def test_eman2_relative_out_dir_regression(tiny_fixture_dir, tmp_path, monkeypatch):
    """Regression test for a real bug found via the GUI (relative out_dir, e.g. the
    GUI form's own "./stw_out" default): mask_convert's subprocess runs with cwd set
    to prep_dir (a subdirectory of out_dir), and was passed job.mask_path -- itself
    derived from the SAME relative out_dir -- as a plain string argument. A relative
    mask_path there re-resolved against prep_dir, not the invoking cwd, landing at a
    nonexistent nested path and failing outright (rc=1). Fixed in orchestrator.py by
    resolving out_dir to absolute once, at the top of run_config()."""
    _skip_if_not_installed()
    monkeypatch.chdir(tmp_path)
    import os

    rel_particles = os.path.relpath(tiny_fixture_dir, tmp_path)
    cfg = RunConfig.model_validate({
        "particles": rel_particles,
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "sphere", "radius": 9.0},
        "packages": ["eman2"],
        "out_dir": "stw_out",
    })
    report = run_config(cfg)
    assert report.results[0]["status"] == "ok"
