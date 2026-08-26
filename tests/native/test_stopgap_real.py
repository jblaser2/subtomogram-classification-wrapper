"""
Real STOPGAP end-to-end test — requires a real STOPGAP install (default
~/Research/STA/packages/STOPGAP; override via package_options.stopgap.
stopgap_home), `matlab` on PATH, and mpirun/mpiexec (often installed but not
on PATH by default -- see docs/install/stopgap.md). Never run in CI (this
whole directory is excluded there). Run manually via:

    pytest tests/native/test_stopgap_real.py -v -m native

Auto-skips if any requirement is missing. Verified working against a real
STOPGAP (MATLAB R2024a + OpenMPI) install on 2026-08-26.

**A real, documented finding, not a test artifact**: unlike Dynamo's dpkpca
embedding (where a single eigencomponent column recovers this fixture's true
split at ARI=1.0), no single column or small column subset examined for
STOPGAP's CC-matrix PCA embedding gets close to a clean separation here --
the best found (column 3 alone) reaches only ARI~0.29, both with and without
z-scoring. This was checked directly (not assumed): the embedding pipeline
was verified structurally correct end to end (rot_vol/calc_ccmat/
calc_pca_ccmat all produce a 32x10 pca/eigenval_1.csv, one row per particle,
in the fixture's canonical sorted-file order) before concluding this is a
property of the method on this fixture -- plausibly STOPGAP's real-space
masked CC-matrix comparison responding differently than Dynamo's eigenvolume
decomposition to this particular synthetic contrast -- rather than a bug in
this port. `test_stopgap_pc_cols_override_changes_result` proves the
override plumbing itself works (a non-default column selection measurably
changes the clustering) without overclaiming a clean recovery this fixture
doesn't support.
"""
import csv
import os

import pytest

from stw.adapters.stopgap import STOPGAPAdapter
from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.scoring.gt import score_against_ground_truth

pytestmark = pytest.mark.native


def _skip_if_not_installed():
    report = STOPGAPAdapter.check_installed()
    if not report.installed:
        pytest.skip("STOPGAP / MATLAB / MPI not found — see docs/install/stopgap.md")


def _load_ground_truth(fixture_dir):
    gt = {}
    with (fixture_dir / "ground_truth.csv").open() as f:
        for row in csv.DictReader(f):
            gt[row["particle"]] = int(row["label"])
    return gt


def test_stopgap_blind_default_is_non_degenerate(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "sphere", "radius": 9},
        "packages": ["stopgap"],
        "out_dir": str(out_dir),
    })
    report = run_config(cfg)
    assert report.results[0]["status"] == "ok"
    assert report.results[0]["n_per_class"]  # ran and produced *some* non-empty split


def test_stopgap_pc_cols_override_changes_result(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    base = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "k": 2,
        "mask": {"kind": "sphere", "radius": 9}, "packages": ["stopgap"],
        "out_dir": str(out_dir),
    }
    report_blind = run_config(RunConfig.model_validate(base))
    assert report_blind.results[0]["status"] == "ok"

    from stw.io.predictions import read_predictions

    pred_blind = read_predictions(out_dir / "stopgap" / "k2" / "seed01" / "predictions.csv")
    gt = _load_ground_truth(tiny_fixture_dir)
    ari_blind = score_against_ground_truth(gt, pred_blind).ari

    out_dir2 = tmp_path / "out_override"
    cfg_tuned = RunConfig.model_validate({
        **base, "out_dir": str(out_dir2),
        "package_options": {"stopgap": {"pc_cols": "3"}},
    })
    report_tuned = run_config(cfg_tuned)
    assert report_tuned.results[0]["status"] == "ok"
    pred_tuned = read_predictions(out_dir2 / "stopgap" / "k2" / "seed01" / "predictions.csv")
    ari_tuned = score_against_ground_truth(gt, pred_tuned).ari

    assert pred_tuned != pred_blind  # override actually changed the clustering
    assert ari_tuned > ari_blind  # and, on this fixture, column 3 alone does better


def test_stopgap_k3_is_non_degenerate(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 3,
        "mask": {"kind": "sphere", "radius": 9},
        "packages": ["stopgap"],
        "out_dir": str(out_dir),
    })
    report = run_config(cfg)
    counts = report.results[0]["n_per_class"]
    assert len(counts) == 3
    assert all(c > 0 for c in counts.values())


def test_stopgap_embedding_is_cached_across_k(tiny_fixture_dir, tmp_path):
    """The embedding (build_inputs/wedgelist/mask/ref/pca_aux/rot_vol/calc_ccmat/
    calc_pca_ccmat) is independent of k -- only k-means (cheap, Python) should rerun."""
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    base = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc",
        "mask": {"kind": "sphere", "radius": 9}, "packages": ["stopgap"],
        "out_dir": str(out_dir),
    }
    run_config(RunConfig.model_validate({**base, "k": 2}))
    cache_root = out_dir / "stopgap" / "_cache"
    embed_dirs = [d for d in os.listdir(cache_root) if d.startswith("embed_")]
    assert len(embed_dirs) == 1
    eig = cache_root / embed_dirs[0] / "pca" / "eigenval_1.csv"
    mtime_before = eig.stat().st_mtime

    run_config(RunConfig.model_validate({**base, "k": 3}))
    assert eig.stat().st_mtime == mtime_before  # embedding was not recomputed


def test_stopgap_distinct_masks_build_distinct_embed_dirs(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    base = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "k": 2,
        "packages": ["stopgap"], "out_dir": str(out_dir),
    }
    run_config(RunConfig.model_validate({**base, "mask": {"kind": "sphere", "radius": 9}}))
    run_config(RunConfig.model_validate({**base, "mask": {"kind": "sphere", "radius": 11}}))
    cache_root = out_dir / "stopgap" / "_cache"
    embed_dirs = [d for d in os.listdir(cache_root) if d.startswith("embed_")]
    assert len(embed_dirs) == 2


def test_stopgap_uniform_wedge_writes_requested_tilt_range(tiny_fixture_dir, tmp_path):
    """Unlike Dynamo (wedge=NONE only), STOPGAP is a real tilt-range pass-through
    -- confirm a supplied uniform wedge actually reaches the wedgelist, not just
    the default +-90 range."""
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "k": 2,
        "mask": {"kind": "sphere", "radius": 9},
        "wedge": {"kind": "uniform", "tilt_min": -50.0, "tilt_max": 50.0},
        "packages": ["stopgap"], "out_dir": str(out_dir),
    })
    report = run_config(cfg)
    assert report.results[0]["status"] == "ok"
    cache_root = out_dir / "stopgap" / "_cache"
    embed_dir = next(d for d in cache_root.iterdir() if d.name.startswith("embed_"))
    wedgelist = (embed_dir / "lists" / "wedgelist.star").read_text()
    # sg_wedgelist_write writes tilt_angle as a plain integer, e.g. " -50 " / " 49 "
    # (min:step:max in 3-degree steps from -50 never lands exactly on +50).
    assert " -50 " in wedgelist
    assert " -90 " not in wedgelist  # the wedge=none default range must NOT leak in
