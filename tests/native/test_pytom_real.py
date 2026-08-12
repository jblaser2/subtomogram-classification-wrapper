"""
Real PyTom end-to-end test — requires the `pytom_env` conda env + MPI, never
run in CI (this whole directory is excluded there). Run manually via:

    pytest tests/native/test_pytom_real.py -v -m native

Auto-skips if the `pytom_env` conda env isn't found. Verified working against
the real `pytom_env` conda env on 2026-08-12: k=2 recovers the fixture's true
16/16 split exactly (ARI=1.0). Also verified (manually, not asserted below
since it's a caching-correctness property rather than a per-run output
check): supplying two different `wedge.tilt_min/tilt_max` configs against the
same out_dir produces two distinct cached particle-list XMLs
(`particle_list_w<angle>.xml`), each with the correct SingleTiltWedge angle
baked in — confirming the wedge pass-through is real, not just accepted and
ignored, and that changing it doesn't silently reuse a stale cached XML.
"""
import csv

import pytest

from stw.adapters.pytom import PyTomAdapter
from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.scoring.gt import score_against_ground_truth

pytestmark = pytest.mark.native


def _skip_if_not_installed():
    report = PyTomAdapter.check_installed()
    if not report.installed:
        pytest.skip("pytom_env conda env not found — see docs/install/pytom.md")


def _load_ground_truth(fixture_dir):
    gt = {}
    with (fixture_dir / "ground_truth.csv").open() as f:
        for row in csv.DictReader(f):
            gt[row["particle"]] = int(row["label"])
    return gt


def test_pytom_end_to_end_on_fixture(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "auto"},
        "packages": ["pytom"],
        "out_dir": str(out_dir),
        "package_options": {"pytom": {"frequency": 8, "niter": 5}},
    })

    report = run_config(cfg)

    assert report.results[0]["status"] == "ok"
    assert report.results[0]["n_per_class"]

    from stw.io.predictions import read_predictions

    pred = read_predictions(out_dir / "pytom" / "k2" / "seed01" / "predictions.csv")
    gt = _load_ground_truth(tiny_fixture_dir)
    score = score_against_ground_truth(gt, pred)
    assert score.ari > 0.8  # matches the documented ARI=1.0 on this easy fixture


def test_pytom_wedge_config_change_produces_distinct_cached_particle_list(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    base_cfg = {
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "packages": ["pytom"],
        "out_dir": str(out_dir),
        "package_options": {"pytom": {"frequency": 8, "niter": 5}},
    }

    run_config(RunConfig.model_validate({**base_cfg, "wedge": {"kind": "uniform", "tilt_min": -50, "tilt_max": 50}}))
    run_config(RunConfig.model_validate({**base_cfg, "wedge": {"kind": "uniform", "tilt_min": -70, "tilt_max": 70}}))

    cache_dir = out_dir / "pytom" / "_cache"
    plists = sorted(p.name for p in cache_dir.glob("particle_list_w*.xml"))
    assert plists == ["particle_list_w20.xml", "particle_list_w40.xml"]
