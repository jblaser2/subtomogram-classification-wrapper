import pytest
from pydantic import ValidationError

from stw.config import RunConfig


def _base(**overrides):
    data = {"particles": "./particles", "packages": ["hac"], **overrides}
    return data


def test_minimal_config_valid():
    cfg = RunConfig.model_validate(_base())
    assert cfg.k_values == [2]
    assert cfg.seed_values == [1]


def test_empty_packages_rejected():
    with pytest.raises(ValidationError):
        RunConfig.model_validate(_base(packages=[]))


def test_k_zero_rejected():
    with pytest.raises(ValidationError):
        RunConfig.model_validate(_base(k=0))


def test_k_list_supported():
    cfg = RunConfig.model_validate(_base(k=[2, 3, 4]))
    assert cfg.k_values == [2, 3, 4]


def test_sphere_mask_requires_radius():
    with pytest.raises(ValidationError):
        RunConfig.model_validate(_base(mask={"kind": "sphere"}))


def test_cylinder_mask_requires_radius_and_height():
    with pytest.raises(ValidationError):
        RunConfig.model_validate(_base(mask={"kind": "cylinder", "radius": 10}))
    cfg = RunConfig.model_validate(_base(mask={"kind": "cylinder", "radius": 10, "half_height": 5}))
    assert cfg.mask.radius == 10


def test_file_mask_requires_path():
    with pytest.raises(ValidationError):
        RunConfig.model_validate(_base(mask={"kind": "file"}))


def test_uniform_wedge_requires_tilt_range():
    with pytest.raises(ValidationError):
        RunConfig.model_validate(_base(wedge={"kind": "uniform"}))
    cfg = RunConfig.model_validate(
        _base(wedge={"kind": "uniform", "tilt_min": -60, "tilt_max": 60})
    )
    assert cfg.wedge.tilt_min == -60


def test_seed_values_from_int_vs_list():
    cfg = RunConfig.model_validate(_base(seeds=3))
    assert cfg.seed_values == [1, 2, 3]
    cfg2 = RunConfig.model_validate(_base(seeds=[5, 7]))
    assert cfg2.seed_values == [5, 7]


def test_roundtrip_yaml(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text("particles: ./p\npackages: [hac]\nk: 3\n")
    cfg = RunConfig.from_file(p)
    assert cfg.k_values == [3]
