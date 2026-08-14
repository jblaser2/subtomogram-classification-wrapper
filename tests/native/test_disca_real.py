"""
Real DISCA end-to-end test — requires a real `disca` conda env (see
docs/install/disca.md); a GPU is optional (DISCA falls back to CPU
automatically) but real training is impractically slow without one. Never
run in CI (this whole directory is excluded there). Run manually via:

    pytest tests/native/test_disca_real.py -v -m native

Auto-skips if the conda env isn't found. Verified working against a real
`disca` conda env (torch 2.11+cu128) on a single consumer GPU on 2026-08-13:
each real training run on the 32-particle, 24^3-box test fixture completes
in ~65-70s (not the hours/seed the source project reports at real dataset
scale — see the adapter's own docstring for that comparison).

**A real, documented finding, not a test artifact**: DISCA is genuinely
unseeded (torch/numpy/CUDA RNGs are never seeded), and across three separate
verification runs on this fixture it landed at consistently near-chance ARI
(0.033, -0.031, -0.012) despite each run completing correctly (non-degenerate
splits, real decreasing training loss). This matches DISCA's own documented
scope — designed for large-scale de novo discovery across thousands of
particles, not fine classification of a handful of pre-aligned ones — and the
source benchmark project's own extensive results showing DISCA frequently
locking onto a contrast axis rather than the true structural one even at
hundreds of real particles. `test_disca_end_to_end_runs_and_is_non_degenerate`
therefore checks the run completes and produces a real, non-degenerate split
rather than asserting a particular ARI.
"""
import pytest

from stw.adapters.disca import DISCAAdapter
from stw.config import RunConfig
from stw.orchestrator import run_config

pytestmark = pytest.mark.native


def _skip_if_not_installed():
    report = DISCAAdapter.check_installed()
    if not report.installed:
        pytest.skip("disca conda env not found — see docs/install/disca.md")


def test_disca_end_to_end_runs_and_is_non_degenerate(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 2,
        "mask": {"kind": "auto"},
        "packages": ["disca"],
        "out_dir": str(out_dir),
    })

    report = run_config(cfg)

    assert report.results[0]["status"] == "ok"
    counts = report.results[0]["n_per_class"]
    assert len(counts) == 2
    assert all(c > 0 for c in counts.values())
    assert sum(counts.values()) == 32


def test_disca_k3_is_non_degenerate(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    out_dir = tmp_path / "out"
    cfg = RunConfig.model_validate({
        "particles": str(tiny_fixture_dir),
        "pattern": "particle_*.mrc",
        "k": 3,
        "mask": {"kind": "auto"},
        "packages": ["disca"],
        "out_dir": str(out_dir),
    })
    report = run_config(cfg)
    counts = report.results[0]["n_per_class"]
    assert len(counts) == 3
    assert all(c > 0 for c in counts.values())


def test_disca_distinct_masks_build_distinct_input_pickles(tiny_fixture_dir, tmp_path):
    """The input-packaging step (mask + Fourier crop) is pure Python -- exercise
    it directly rather than through two full ~65s training runs."""
    _skip_if_not_installed()
    import os

    from stw.masks.resolve import resolve_mask
    from stw.spec import AlignmentState, Job, MaskKind, MaskSpec, ParticleSet, WedgeSpec

    out_dir = tmp_path / "out"
    particles = ParticleSet.discover(tiny_fixture_dir, "particle_*.mrc")
    cache_root = out_dir / "_cache"
    adapter = DISCAAdapter()

    for radius in (9, 6):
        mask_spec = MaskSpec(kind=MaskKind.SPHERE, radius=radius)
        mask_path = resolve_mask(mask_spec, particles, cache_root, render_qc=False)
        job = Job(
            package="disca", particles=particles, mask_path=mask_path, mask_spec=mask_spec,
            wedge=WedgeSpec(), alignment_state=AlignmentState.FINE,
            k=2, seed=1, workdir=out_dir / "disca" / "k2" / "seed01", cache_dir=out_dir / "disca" / "_cache",
        )
        adapter._ensure_prep(job, adapter._null_sink())

    prep_dirs = [d for d in os.listdir(out_dir / "disca" / "_cache") if d.startswith("prep_")]
    assert len(prep_dirs) == 2
