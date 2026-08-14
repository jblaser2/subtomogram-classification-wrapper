"""Unit tests for DISCA's pure-Python input-packaging logic (mask + Fourier
crop + standardization) -- no conda env, torch, or GPU needed."""
import numpy as np
import pytest

from stw.adapters.disca import build_disca_input, fourier_crop


def test_fourier_crop_noop_when_same_size():
    vol = np.random.default_rng(0).normal(size=(8, 8, 8)).astype(np.float32)
    out = fourier_crop(vol, 8)
    assert np.allclose(out, vol, atol=1e-5)


def test_fourier_crop_downsamples_shape():
    vol = np.random.default_rng(0).normal(size=(24, 24, 24)).astype(np.float32)
    out = fourier_crop(vol, 12)
    assert out.shape == (12, 12, 12)


def test_fourier_crop_rejects_upsampling():
    vol = np.zeros((8, 8, 8), dtype=np.float32)
    with pytest.raises(ValueError):
        fourier_crop(vol, 16)


def test_fourier_crop_preserves_mean_amplitude_of_smooth_signal():
    # a smooth (low-frequency-only) signal should survive downsampling almost
    # exactly, since Fourier cropping only discards high frequencies.
    n = 16
    zz, yy, xx = np.mgrid[0:n, 0:n, 0:n]
    vol = (np.sin(2 * np.pi * zz / n) + 2.0).astype(np.float32)
    out = fourier_crop(vol, 8)
    assert abs(out.mean() - vol.mean()) < 0.05


def test_build_disca_input_applies_mask_and_standardizes(tmp_path):
    import mrcfile

    box = 8
    d = tmp_path
    vol_a = np.full((box, box, box), 5.0, dtype=np.float32)
    vol_a[0, 0, 0] = 100.0  # masked-out corner, should be zeroed by the mask
    with mrcfile.new(d / "a.mrc", overwrite=True) as m:
        m.set_data(vol_a)
    mask = np.ones((box, box, box), dtype=np.float32)
    mask[0, 0, 0] = 0.0

    result = build_disca_input(d, ["a.mrc"], mask, box)
    v = result["vs"]["a.mrc"]["v"]
    assert v.shape == (box, box, box)
    assert abs(v.mean()) < 1e-4  # zero-mean after standardization
    assert result["vs"]["a.mrc"]["id"] == "a.mrc"
    assert result["vs"]["a.mrc"]["m"] is None


def test_build_disca_input_no_mask_keeps_full_volume(tmp_path):
    import mrcfile

    box = 8
    with mrcfile.new(tmp_path / "b.mrc", overwrite=True) as m:
        m.set_data(np.full((box, box, box), 3.0, dtype=np.float32))
    result = build_disca_input(tmp_path, ["b.mrc"], None, box)
    assert "b.mrc" in result["vs"]
    assert result["vs"]["b.mrc"]["v"].shape == (box, box, box)


def test_build_disca_input_crops_to_requested_box(tmp_path):
    import mrcfile

    box = 16
    with mrcfile.new(tmp_path / "c.mrc", overwrite=True) as m:
        m.set_data(np.random.default_rng(1).normal(size=(box, box, box)).astype(np.float32))
    result = build_disca_input(tmp_path, ["c.mrc"], None, 8)
    assert result["vs"]["c.mrc"]["v"].shape == (8, 8, 8)


def test_build_disca_input_preserves_file_order(tmp_path):
    import mrcfile

    box = 4
    for name in ("z.mrc", "a.mrc", "m.mrc"):
        with mrcfile.new(tmp_path / name, overwrite=True) as f:
            f.set_data(np.zeros((box, box, box), dtype=np.float32))
    files = ["z.mrc", "a.mrc", "m.mrc"]  # deliberately not sorted
    result = build_disca_input(tmp_path, files, None, box)
    assert list(result["vs"].keys()) == files
