import mrcfile
import numpy as np
import pytest

from stw.averaging import EmptyClassError, class_averages, global_average


def _write(path, value, shape=(4, 4, 4)):
    with mrcfile.new(path, overwrite=True) as m:
        m.set_data(np.full(shape, value, dtype=np.float32))


def test_class_averages_known_mean(tmp_path):
    _write(tmp_path / "a1.mrc", 1.0)
    _write(tmp_path / "a2.mrc", 3.0)
    _write(tmp_path / "b1.mrc", 10.0)
    labels = {"a1.mrc": 1, "a2.mrc": 1, "b1.mrc": 2}
    averages, counts = class_averages(tmp_path, labels)
    assert averages[1].mean() == pytest.approx(2.0)
    assert averages[2].mean() == pytest.approx(10.0)
    assert counts == {1: 2, 2: 1}


def test_class_averages_missing_file_is_skipped(tmp_path):
    _write(tmp_path / "a1.mrc", 5.0)
    labels = {"a1.mrc": 1, "does_not_exist.mrc": 1}
    averages, counts = class_averages(tmp_path, labels)
    assert counts[1] == 1
    assert averages[1].mean() == pytest.approx(5.0)


def test_class_averages_empty_class_raises(tmp_path):
    labels = {"missing.mrc": 1}
    with pytest.raises(EmptyClassError):
        class_averages(tmp_path, labels)


def test_class_averages_normalize(tmp_path):
    _write(tmp_path / "a1.mrc", 5.0)
    averages, _ = class_averages(tmp_path, {"a1.mrc": 1}, normalize=True)
    # constant volume has std=0 -> normalize falls back to mean-subtraction only
    assert averages[1].mean() == pytest.approx(0.0, abs=1e-6)


def test_global_average(tmp_path):
    _write(tmp_path / "a1.mrc", 2.0)
    _write(tmp_path / "a2.mrc", 4.0)
    avg = global_average(tmp_path, ["a1.mrc", "a2.mrc"])
    assert avg.mean() == pytest.approx(3.0)
