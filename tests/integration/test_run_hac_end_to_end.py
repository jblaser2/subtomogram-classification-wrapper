"""
M1's locking test: a full `stw run` with HAC Baseline only, against the tiny
committed fixture. HAC has zero external dependencies, so this runs in plain
CI with nothing installed — it's the contract every future adapter's own
end-to-end test should match.
"""
import csv

from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.scoring.gt import score_against_ground_truth


def _load_ground_truth(fixture_dir):
    gt = {}
    with (fixture_dir / "ground_truth.csv").open() as f:
        for row in csv.DictReader(f):
            gt[row["particle"]] = int(row["label"])
    return gt


def test_end_to_end_hac_run(tiny_fixture_dir, tmp_path):
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate(
        {
            "particles": str(tiny_fixture_dir),
            "pattern": "particle_*.mrc",
            "k": 2,
            "mask": {"kind": "auto"},
            "packages": ["hac"],
            "out_dir": str(out_dir),
        }
    )

    report = run_config(cfg)

    assert len(report.results) == 1
    result = report.results[0]
    assert result["status"] == "ok"
    assert result["n_per_class"]  # non-degenerate: every class got particles

    predictions_path = out_dir / "hac" / "k2" / "seed01" / "predictions.csv"
    assert predictions_path.exists()

    class_avg_dir = out_dir / "hac" / "k2" / "seed01" / "class_averages"
    avg_files = list(class_avg_dir.glob("*.mrc"))
    assert len(avg_files) == 2

    import mrcfile

    for f in avg_files:
        with mrcfile.open(f, permissive=True) as m:
            assert m.data.std() > 0  # non-degenerate average, not all-zero

    assert (out_dir / "run_report.json").exists()
    assert (out_dir / "summary.md").exists()

    from stw.io.predictions import read_predictions

    pred = read_predictions(predictions_path)
    gt = _load_ground_truth(tiny_fixture_dir)
    score = score_against_ground_truth(gt, pred)
    assert score.ari > 0.8  # the fixture's structural difference should be easy


def test_dry_run_does_not_write_outputs(tiny_fixture_dir, tmp_path):
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate(
        {
            "particles": str(tiny_fixture_dir),
            "pattern": "particle_*.mrc",
            "packages": ["hac"],
            "out_dir": str(out_dir),
        }
    )
    report = run_config(cfg, dry_run=True)
    assert not out_dir.exists()
    assert report.results[0]["status"] == "skipped"
    assert "load" in report.results[0]["provenance"]["planned_steps"]


def test_incompatible_alignment_state_is_recorded_not_fatal(tiny_fixture_dir, tmp_path):
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate(
        {
            "particles": str(tiny_fixture_dir),
            "pattern": "particle_*.mrc",
            "packages": ["hac"],
            "alignment_state": "unaligned",
            "out_dir": str(out_dir),
        }
    )
    report = run_config(cfg)  # must not raise
    assert report.results[0]["status"] == "incompatible"


def test_resume_reuses_cached_mask_and_distance_matrix(tiny_fixture_dir, tmp_path):
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate(
        {
            "particles": str(tiny_fixture_dir),
            "pattern": "particle_*.mrc",
            "packages": ["hac"],
            "out_dir": str(out_dir),
        }
    )
    run_config(cfg)
    cache_files_after_first = sorted((out_dir / "hac" / "_cache").glob("*.npy"))
    assert cache_files_after_first

    mtime_before = cache_files_after_first[0].stat().st_mtime
    run_config(cfg)  # second run should hit the cache, not recompute
    mtime_after = cache_files_after_first[0].stat().st_mtime
    assert mtime_before == mtime_after
