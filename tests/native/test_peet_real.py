"""
Real PEET end-to-end test — requires IMOD's and PEET's setup scripts (default
paths ~/Applications/IMOD-linux.sh, ~/Applications/Particle.sh; override via
package_options.peet.imod_setup/particle_setup), never run in CI (this whole
directory is excluded there). Run manually via:

    pytest tests/native/test_peet_real.py -v -m native

Auto-skips if the setup scripts aren't found. Verified working against real
IMOD + PEET 1.18.2 (MCR binaries) on 2026-08-13: k=2 recovers the fixture's
true 16/16 split exactly (ARI=1.0), k=3 gives a non-degenerate 16/10/6
split, class averages are non-degenerate, and a cached second run is
roughly 2x faster (prep steps -- the slow stacked-volume + averageAll + pca
stages -- are skipped; only clusterPca/usePcaMotiveLists/collect re-run).
"""
import csv

import pytest

from stw.adapters.peet import PEETAdapter
from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.scoring.gt import score_against_ground_truth

pytestmark = pytest.mark.native


def _skip_if_not_installed():
    report = PEETAdapter.check_installed()
    if not report.installed:
        pytest.skip("IMOD/PEET setup scripts not found — see docs/install/peet.md")


def _load_ground_truth(fixture_dir):
    gt = {}
    with (fixture_dir / "ground_truth.csv").open() as f:
        for row in csv.DictReader(f):
            gt[row["particle"]] = int(row["label"])
    return gt


def test_peet_end_to_end_on_fixture(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "auto"},
        "packages": ["peet"],
        "out_dir": str(out_dir),
    })

    report = run_config(cfg)

    assert report.results[0]["status"] == "ok"
    assert report.results[0]["n_per_class"]

    from stw.io.predictions import read_predictions

    pred = read_predictions(out_dir / "peet" / "k2" / "seed01" / "predictions.csv")
    gt = _load_ground_truth(tiny_fixture_dir)
    score = score_against_ground_truth(gt, pred)
    assert score.ari > 0.8  # matches the documented ARI=1.0 on this easy fixture


def test_peet_prep_is_cached_across_runs(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "packages": ["peet"],
        "out_dir": str(out_dir),
    })
    run_config(cfg)
    import json

    report_path = out_dir / "run_report.json"
    first_elapsed = json.loads(report_path.read_text())["results"][0]["elapsed_sec"]

    run_config(cfg)  # second run should reuse cached stack/model/motl/average/pca
    second_elapsed = json.loads(report_path.read_text())["results"][0]["elapsed_sec"]

    assert second_elapsed < first_elapsed
