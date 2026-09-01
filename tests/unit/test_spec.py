import mrcfile
import numpy as np
import pytest

from stw.spec import ParticleSet, ParticleSetError


def _write(path, shape=(8, 8, 8), apix=None):
    with mrcfile.new(path, overwrite=True) as m:
        m.set_data(np.zeros(shape, dtype=np.float32))
        if apix is not None:
            m.voxel_size = apix


def test_discover_happy_path(tmp_path):
    _write(tmp_path / "p1.mrc", apix=5.0)
    _write(tmp_path / "p2.mrc", apix=5.0)
    ps = ParticleSet.discover(tmp_path, "*.mrc")
    assert len(ps) == 2
    assert ps.box == 8
    assert ps.pixel_size == pytest.approx(5.0)


def test_discover_empty_dir_raises(tmp_path):
    with pytest.raises(ParticleSetError):
        ParticleSet.discover(tmp_path, "*.mrc")


def test_discover_nonexistent_dir_raises(tmp_path):
    with pytest.raises(ParticleSetError):
        ParticleSet.discover(tmp_path / "nope", "*.mrc")


def test_discover_inconsistent_box_raises(tmp_path):
    _write(tmp_path / "p1.mrc", shape=(8, 8, 8), apix=5.0)
    _write(tmp_path / "p2.mrc", shape=(10, 10, 10), apix=5.0)
    with pytest.raises(ParticleSetError):
        ParticleSet.discover(tmp_path, "*.mrc")


def test_discover_default_apix_of_one_is_rejected(tmp_path):
    """mrcfile's own default when a header never sets voxel_size is 1.0 A/px —
    a real MRC defect this must not silently accept."""
    _write(tmp_path / "p1.mrc", apix=None)
    with pytest.raises(ParticleSetError):
        ParticleSet.discover(tmp_path, "*.mrc")


def test_discover_explicit_pixel_size_overrides(tmp_path):
    _write(tmp_path / "p1.mrc", apix=None)
    ps = ParticleSet.discover(tmp_path, "*.mrc", pixel_size=13.33)
    assert ps.pixel_size == pytest.approx(13.33)


def _tiny_set(tmp_path, n=20):
    for i in range(n):
        _write(tmp_path / f"p{i:03d}.mrc", apix=5.0)
    return ParticleSet.discover(tmp_path, "*.mrc")


def test_subsample_returns_requested_count(tmp_path):
    ps = _tiny_set(tmp_path, n=20)
    sub = ps.subsample(5, seed=0)
    assert len(sub) == 5
    assert set(sub.files) <= set(ps.files)
    assert list(sub.files) == sorted(sub.files)  # canonical row order preserved


def test_subsample_larger_than_set_returns_everything(tmp_path):
    ps = _tiny_set(tmp_path, n=5)
    sub = ps.subsample(1000)
    assert sub.files == ps.files


def test_subsample_is_reproducible_for_same_seed(tmp_path):
    ps = _tiny_set(tmp_path, n=20)
    a = ps.subsample(6, seed=42)
    b = ps.subsample(6, seed=42)
    assert a.files == b.files


def test_subsample_different_seeds_can_differ(tmp_path):
    ps = _tiny_set(tmp_path, n=20)
    a = ps.subsample(6, seed=1)
    b = ps.subsample(6, seed=2)
    assert a.files != b.files  # not guaranteed in general, but true for this fixture/seed pair


def test_subsample_rejects_zero_or_negative(tmp_path):
    ps = _tiny_set(tmp_path, n=5)
    with pytest.raises(ParticleSetError):
        ps.subsample(0)
    with pytest.raises(ParticleSetError):
        ps.subsample(-3)


def test_subsample_changes_fingerprint(tmp_path):
    """A subsampled run must not collide in the orchestrator's particle-set-keyed
    cache with a full run over the same directory -- see ParticleSet.fingerprint()."""
    ps = _tiny_set(tmp_path, n=20)
    sub = ps.subsample(5, seed=0)
    assert sub.fingerprint() != ps.fingerprint()
