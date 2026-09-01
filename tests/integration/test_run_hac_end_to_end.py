"""
M1's locking test: a full `stw run` with HAC Baseline only, against the tiny
committed fixture. HAC has zero external dependencies, so this runs in plain
CI with nothing installed — it's the contract every future adapter's own
end-to-end test should match.
"""
import csv
import os
import threading

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


def test_relative_out_dir_and_particles_resolve_to_absolute(tiny_fixture_dir, tmp_path, monkeypatch):
    """Regression test for a real bug found via the GUI: a relative out_dir (the GUI
    form's own default, "./stw_out") left job.workdir/cache_dir/mask_path relative,
    which broke any adapter that runs a multi-step subprocess with cwd set to a
    SUBDIRECTORY of out_dir (a relative path arg then re-resolves against the wrong
    cwd). HAC never subprocesses, so this only checks the resolution itself -- the
    subprocess-cwd-mismatch reproduction is a native EMAN2 test (needs a real install)."""
    monkeypatch.chdir(tmp_path)
    rel_particles = os.path.relpath(tiny_fixture_dir, tmp_path)
    cfg = RunConfig.model_validate({
        "particles": rel_particles,
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "auto"},
        "packages": ["hac"],
        "out_dir": "stw_out",  # relative, matching stw gui's form default
    })
    report = run_config(cfg)
    assert report.results[0]["status"] == "ok"
    assert (tmp_path / "stw_out" / "run_report.json").exists()
    assert (tmp_path / "stw_out" / "hac" / "k2" / "seed01" / "predictions.csv").exists()


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
    # rglob, not glob: cache_dir is now out_dir/hac/_cache/<particle-set fingerprint>/...
    cache_files_after_first = sorted((out_dir / "hac" / "_cache").rglob("*.npy"))
    assert cache_files_after_first

    mtime_before = cache_files_after_first[0].stat().st_mtime
    run_config(cfg)  # second run should hit the cache, not recompute
    mtime_after = cache_files_after_first[0].stat().st_mtime
    assert mtime_before == mtime_after


def test_different_particle_sets_sharing_out_dir_get_distinct_caches(tiny_fixture_dir, tmp_path):
    """Regression test for a real bug found via the GUI: switching to a different
    dataset while reusing the same out_dir silently (or, for adapters with a hard
    particle-existence check like PyTom's, loudly with "class(es) with zero
    particles") reused cached prep built from the OTHER dataset -- no adapter's own
    caching accounted for particle-set identity, only the shared cache_dir/cache_root
    orchestrator.run_config() computes did, after this fix."""
    import mrcfile
    import numpy as np

    out_dir = tmp_path / "out"

    # A second, smaller synthetic particle set -- deliberately a different particle
    # count than tiny_fixture_dir's 32, so a stale cache hit would surface loudly
    # (a cached CC-matrix sized for the wrong particle count) rather than silently.
    other_dir = tmp_path / "other_particles"
    other_dir.mkdir()
    rng = np.random.default_rng(0)
    for i in range(8):
        with mrcfile.new(other_dir / f"p_{i:02d}.mrc", overwrite=True) as m:
            m.set_data(rng.normal(size=(24, 24, 24)).astype("float32"))
            m.voxel_size = 5.0

    mask = {"kind": "sphere", "radius": 9}
    run_config(RunConfig.model_validate({
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "k": 2,
        "packages": ["hac"], "out_dir": str(out_dir), "mask": mask,
    }))
    report2 = run_config(RunConfig.model_validate({
        "particles": str(other_dir), "pattern": "*.mrc", "k": 2,
        "packages": ["hac"], "out_dir": str(out_dir), "mask": mask,
    }))

    assert report2.results[0]["status"] == "ok"
    assert sum(report2.results[0]["n_per_class"].values()) == 8  # the SECOND dataset's own count

    fingerprint_dirs = [d for d in (out_dir / "hac" / "_cache").iterdir() if d.is_dir()]
    assert len(fingerprint_dirs) == 2  # one per distinct particle set, not reused


def test_subsample_caps_particle_count(tiny_fixture_dir, tmp_path):
    """The tiny fixture has 32 particles; capping to 10 should classify only 10,
    keep a separate cache from the full-32 run, and record both counts on the
    report so a user can see what actually ran."""
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "k": 2,
        "mask": {"kind": "auto"}, "packages": ["hac"], "out_dir": str(out_dir),
        "subsample": 10, "subsample_seed": 3,
    })
    report = run_config(cfg)

    assert report.n_particles_total == 32
    assert report.n_particles_used == 10
    result = report.results[0]
    assert result["status"] == "ok"
    assert sum(result["n_per_class"].values()) == 10

    fingerprint_dirs = [d for d in (out_dir / "hac" / "_cache").iterdir() if d.is_dir()]
    assert len(fingerprint_dirs) == 1  # only the subsampled run happened


def test_subsample_larger_than_dataset_uses_everything(tiny_fixture_dir, tmp_path):
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "k": 2,
        "mask": {"kind": "auto"}, "packages": ["hac"], "out_dir": str(out_dir),
        "subsample": 10_000,
    })
    report = run_config(cfg)
    assert report.n_particles_total == 32
    assert report.n_particles_used == 32


def test_cancel_flag_set_before_start_skips_the_package(tiny_fixture_dir, tmp_path):
    """Regression test for the GUI's per-package Cancel button: a package whose
    cancel_event is already set before its turn comes up (e.g. cancelled while
    still queued behind an earlier package) must be skipped outright, not run
    and then discarded -- no predictions.csv should even be written."""
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "k": 2,
        "mask": {"kind": "auto"}, "packages": ["hac"], "out_dir": str(out_dir),
    })
    already_cancelled = threading.Event()
    already_cancelled.set()

    report = run_config(cfg, cancel_flags={"hac": already_cancelled})

    assert report.results[0]["status"] == "cancelled"
    assert not (out_dir / "hac" / "k2" / "seed01" / "predictions.csv").exists()


def test_cancel_flag_for_a_different_package_does_not_affect_this_one(tiny_fixture_dir, tmp_path):
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "k": 2,
        "mask": {"kind": "auto"}, "packages": ["hac"], "out_dir": str(out_dir),
    })
    unrelated = threading.Event()
    unrelated.set()

    report = run_config(cfg, cancel_flags={"some_other_package": unrelated})

    assert report.results[0]["status"] == "ok"
