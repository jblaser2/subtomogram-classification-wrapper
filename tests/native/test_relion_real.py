"""
Real RELION end-to-end test — requires a real `relion_refine` binary on PATH
or a common install location, never run in CI (this whole directory is
excluded there). Run manually via:

    pytest tests/native/test_relion_real.py -v -m native

Auto-skips if relion_refine isn't found. Verified working against a real
relion_refine 5.0.1 build on 2026-08-14: k=2 recovers the fixture's true
16/16 split exactly (ARI=1.0), k=3 gives a non-degenerate 15/16/1 split, and
two different wedge.tilt_min/tilt_max configs produce two distinct
correctly-shaped cached CTF cubes/STAR files (measured_frac 1.0 for no
wedge, ~0.58 for a +/-50 degree tilt range).
"""
import csv

import pytest

from stw.adapters.relion import RELIONAdapter
from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.scoring.gt import score_against_ground_truth

pytestmark = pytest.mark.native


def _skip_if_not_installed():
    report = RELIONAdapter.check_installed()
    if not report.installed:
        pytest.skip("relion_refine not found — see docs/install/relion.md")


def _load_ground_truth(fixture_dir):
    gt = {}
    with (fixture_dir / "ground_truth.csv").open() as f:
        for row in csv.DictReader(f):
            gt[row["particle"]] = int(row["label"])
    return gt


def test_relion_end_to_end_on_fixture(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "auto"},
        "packages": ["relion"],
        "out_dir": str(out_dir),
    })

    report = run_config(cfg)

    assert report.results[0]["status"] == "ok"
    assert report.results[0]["n_per_class"]

    from stw.io.predictions import read_predictions

    pred = read_predictions(out_dir / "relion" / "k2" / "seed01" / "predictions.csv")
    gt = _load_ground_truth(tiny_fixture_dir)
    score = score_against_ground_truth(gt, pred)
    assert score.ari > 0.8  # matches the documented ARI=1.0 on this easy fixture


def test_relion_wedge_config_change_produces_distinct_cached_files(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    base_cfg = {
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "packages": ["relion"],
        "out_dir": str(out_dir),
    }

    run_config(RunConfig.model_validate({**base_cfg, "wedge": {"kind": "uniform", "tilt_min": -50, "tilt_max": 50}}))
    run_config(RunConfig.model_validate({**base_cfg}))  # no wedge -> full coverage

    cache_dir = out_dir / "relion" / "_cache"
    ctf_files = sorted(p.name for p in cache_dir.rglob("ctf_t*.mrc"))
    assert ctf_files == ["ctf_t50.mrc", "ctf_t90.mrc"]
