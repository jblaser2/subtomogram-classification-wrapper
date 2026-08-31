"""
Real PyTom FRM alignment end-to-end test — requires a real PyTom install
plus the compiled FRM extension (see docs/install/pytom.md,
scripts/compile_pytom_frm.sh — not needed for classification, only for
`stw align`). Never run in CI (this whole directory is excluded there). Run
manually via:

    pytest tests/native/test_align_pytom_frm_real.py -v -m native

Auto-skips if either requirement is missing. Verified working against a real
PyTom (FRM compiled via scripts/compile_pytom_frm.sh) install on 2026-08-31.

Since the tiny fixture is already pre-aligned, these tests build their own
deliberately roughly-misaligned copy of it (small random rotation + shift
per particle, real scipy transforms with a known seed) and check that real
FRM alignment measurably recovers coherence — not just that it runs without
crashing.
"""
import csv

import numpy as np
import pytest

from stw.align import AlignConfig, check_installed, run_pytom_alignment
from stw.averaging import global_average
from stw.config import RunConfig
from stw.orchestrator import run_config

pytestmark = pytest.mark.native


def _skip_if_not_installed():
    checks = check_installed()
    if not all(c.ok for c in checks):
        pytest.skip(
            "PyTom / compiled _swig_frm extension not found — see "
            "docs/install/pytom.md and scripts/compile_pytom_frm.sh"
        )


def _make_rough_copy(src_dir, dst_dir, pattern="particle_*.mrc", seed=0, max_angle=20.0, max_shift=3.0):
    import mrcfile
    from scipy.ndimage import rotate
    from scipy.ndimage import shift as nd_shift

    rng = np.random.default_rng(seed)
    dst_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p.name for p in src_dir.glob(pattern))
    for f in files:
        with mrcfile.open(src_dir / f, permissive=True) as m:
            vol = np.asarray(m.data).astype(np.float32)
            apix = float(m.voxel_size.x)
        angles = rng.uniform(-max_angle, max_angle, size=3)
        shifts = rng.uniform(-max_shift, max_shift, size=3)
        v = rotate(vol, angles[0], axes=(1, 2), reshape=False, order=1, mode="constant")
        v = rotate(v, angles[1], axes=(0, 2), reshape=False, order=1, mode="constant")
        v = rotate(v, angles[2], axes=(0, 1), reshape=False, order=1, mode="constant")
        v = nd_shift(v, shifts, order=1, mode="constant")
        with mrcfile.new(dst_dir / f, overwrite=True) as m:
            m.set_data(v.astype(np.float32))
            m.voxel_size = apix
    return files


def test_frm_alignment_recovers_coherence(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    rough_dir = tmp_path / "rough"
    files = _make_rough_copy(tiny_fixture_dir, rough_dir)

    cfg = AlignConfig.model_validate({
        "particles": str(rough_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "mask": {"kind": "sphere", "radius": 10.0},
        "out_dir": str(tmp_path / "out"),
    })
    report = run_pytom_alignment(cfg)
    assert report.status == "ok"
    assert report.n_particles == len(files)
    assert report.aligned_particle_dir.exists()

    rough_avg = global_average(rough_dir, files)
    aligned_avg = global_average(report.aligned_particle_dir, files)
    original_avg = global_average(tiny_fixture_dir, files)

    # the real, measurable signal: alignment must recover MOST of the sharpness
    # lost to the rough perturbation, not just run without crashing
    assert aligned_avg.std() > rough_avg.std()
    assert aligned_avg.std() > 0.9 * original_avg.std()


def test_frm_alignment_writes_poses_csv(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    rough_dir = tmp_path / "rough"
    files = _make_rough_copy(tiny_fixture_dir, rough_dir, seed=1)

    cfg = AlignConfig.model_validate({
        "particles": str(rough_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "mask": {"kind": "sphere", "radius": 10.0},
        "out_dir": str(tmp_path / "out"),
    })
    report = run_pytom_alignment(cfg)
    assert report.status == "ok"
    with open(report.poses_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(files)
    expected_cols = {"particle", "shift_x", "shift_y", "shift_z", "rot_z1", "rot_x", "rot_z2", "score"}
    assert expected_cols <= set(rows[0].keys())


def test_aligned_output_feeds_into_a_normal_run(tiny_fixture_dir, tmp_path):
    """The whole point of the feature: aligned output must be directly usable
    as a normal stw run's particles: input, no format bridging needed."""
    _skip_if_not_installed()
    rough_dir = tmp_path / "rough"
    files = _make_rough_copy(tiny_fixture_dir, rough_dir, seed=2)

    align_cfg = AlignConfig.model_validate({
        "particles": str(rough_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "mask": {"kind": "sphere", "radius": 10.0},
        "out_dir": str(tmp_path / "align_out"),
    })
    align_report = run_pytom_alignment(align_cfg)
    assert align_report.status == "ok"

    run_cfg = RunConfig.model_validate({
        "particles": str(align_report.aligned_particle_dir), "pattern": "particle_*.mrc",
        "pixel_size": 5.0, "k": 2, "mask": {"kind": "auto"}, "packages": ["hac"],
        "out_dir": str(tmp_path / "classify_out"),
    })
    run_report = run_config(run_cfg)
    assert run_report.results[0]["status"] == "ok"
    assert sum(run_report.results[0]["n_per_class"].values()) == len(files)


def test_rerun_skips_the_expensive_align_step(tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    rough_dir = tmp_path / "rough"
    _make_rough_copy(tiny_fixture_dir, rough_dir, seed=3)

    cfg = AlignConfig.model_validate({
        "particles": str(rough_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "mask": {"kind": "sphere", "radius": 10.0},
        "out_dir": str(tmp_path / "out"),
    })
    first = run_pytom_alignment(cfg)
    assert first.status == "ok"
    second = run_pytom_alignment(cfg)
    assert second.status == "ok"
    assert second.elapsed_sec < first.elapsed_sec / 2  # skipped the MPI search entirely
