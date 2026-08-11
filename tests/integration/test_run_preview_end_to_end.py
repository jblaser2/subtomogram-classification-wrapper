"""
M2's locking test: all three preview-mode adapters (dependency-free Python
approximations of Dynamo/PyTom/ProTomo) plus HAC Baseline, run together
against the tiny fixture — a 4-method comparison that needs zero native
installs, so it runs in plain CI same as the HAC-only M1 test.
"""
import csv

import pytest

from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.scoring.gt import score_against_ground_truth

PREVIEW_PACKAGES = ["hac", "dynamo-preview", "pytom-preview", "protomo-preview"]


def _load_ground_truth(fixture_dir):
    gt = {}
    with (fixture_dir / "ground_truth.csv").open() as f:
        for row in csv.DictReader(f):
            gt[row["particle"]] = int(row["label"])
    return gt


def test_all_preview_adapters_run_end_to_end(tiny_fixture_dir, tmp_path):
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate(
        {
            "particles": str(tiny_fixture_dir),
            "pattern": "particle_*.mrc",
            "k": 2,
            "mask": {"kind": "auto"},
            "packages": PREVIEW_PACKAGES,
            "out_dir": str(out_dir),
        }
    )

    report = run_config(cfg)

    assert len(report.results) == 4
    for r in report.results:
        assert r["status"] == "ok", r
        assert r["n_per_class"]
        assert (out_dir / r["package"] / "k2" / "seed01" / "predictions.csv").exists()

    # every preview adapter's fidelity caveat should surface as a warning
    for r in report.results:
        if r["package"] != "hac":
            assert any("approximation" in w for w in r["warnings"])


def test_preview_adapters_score_reasonably_against_ground_truth(tiny_fixture_dir, tmp_path):
    """Not exact-value assertions (these are approximations, not the real
    packages) — just confirms nothing is degenerate on an easy fixture."""
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate(
        {
            "particles": str(tiny_fixture_dir),
            "pattern": "particle_*.mrc",
            "packages": PREVIEW_PACKAGES,
            "out_dir": str(out_dir),
        }
    )
    run_config(cfg)
    gt = _load_ground_truth(tiny_fixture_dir)

    from stw.io.predictions import read_predictions

    for pkg in PREVIEW_PACKAGES:
        pred = read_predictions(out_dir / pkg / "k2" / "seed01" / "predictions.csv")
        score = score_against_ground_truth(gt, pred)
        assert score.ari > 0.1, f"{pkg} scored suspiciously close to chance: ARI={score.ari}"


def test_comparison_report_built_across_all_four(tiny_fixture_dir, tmp_path):
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate(
        {
            "particles": str(tiny_fixture_dir),
            "pattern": "particle_*.mrc",
            "packages": PREVIEW_PACKAGES,
            "out_dir": str(out_dir),
        }
    )
    report = run_config(cfg)
    assert report.comparison is not None
    assert len(report.comparison["package_names"]) == 4
    assert len(report.comparison["pairwise_ari"]) == 6  # C(4,2)
    assert report.comparison["consensus"]["n_shared"] == 32


def test_pytom_preview_rejects_k_other_than_two(tiny_fixture_dir, tmp_path):
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate(
        {
            "particles": str(tiny_fixture_dir),
            "pattern": "particle_*.mrc",
            "k": 3,
            "packages": ["pytom-preview"],
            "out_dir": str(out_dir),
        }
    )
    report = run_config(cfg)
    assert report.results[0]["status"] == "incompatible"


def test_mode_preview_resolves_bare_package_names(tiny_fixture_dir, tmp_path):
    """packages: [dynamo] + mode: preview should resolve to dynamo-preview,
    the same way it will once a native `dynamo` adapter also exists."""
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate(
        {
            "particles": str(tiny_fixture_dir),
            "pattern": "particle_*.mrc",
            "packages": ["dynamo"],
            "mode": "preview",
            "out_dir": str(out_dir),
        }
    )
    report = run_config(cfg)
    assert report.results[0]["package"] == "dynamo-preview"
    assert report.results[0]["status"] == "ok"


def test_mode_native_does_not_resolve_to_preview(tiny_fixture_dir, tmp_path):
    """No native "dynamo" adapter is registered yet — mode=native must fail to
    resolve it rather than silently falling back to the preview variant."""
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate(
        {
            "particles": str(tiny_fixture_dir),
            "pattern": "particle_*.mrc",
            "packages": ["dynamo"],
            "mode": "native",
            "out_dir": str(out_dir),
        }
    )
    with pytest.raises(KeyError):
        run_config(cfg)
