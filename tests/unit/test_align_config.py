"""Unit tests for AlignConfig -- pure pydantic validation, no PyTom needed."""
import pytest
from pydantic import ValidationError

from stw.align.config import AlignConfig


def test_mask_kind_none_is_rejected(tmp_path):
    with pytest.raises(ValidationError, match="requires a mask"):
        AlignConfig.model_validate({
            "particles": str(tmp_path), "mask": {"kind": "none"},
        })


def test_default_mask_is_auto(tmp_path):
    cfg = AlignConfig.model_validate({"particles": str(tmp_path)})
    assert cfg.mask.kind == "auto"


def test_sphere_mask_accepted(tmp_path):
    cfg = AlignConfig.model_validate({
        "particles": str(tmp_path), "mask": {"kind": "sphere", "radius": 10.0},
    })
    assert cfg.mask.kind == "sphere"
    assert cfg.mask.radius == 10.0


def test_options_default_empty_dict(tmp_path):
    cfg = AlignConfig.model_validate({"particles": str(tmp_path)})
    assert cfg.options == {}


def test_from_file_yaml(tmp_path):
    cfg_path = tmp_path / "align.yaml"
    cfg_path.write_text(f"""
particles: {tmp_path}
pattern: "particle_*.mrc"
pixel_size: 5.0
mask:
  kind: sphere
  radius: 10.0
out_dir: {tmp_path / "out"}
options:
  max_iter: 6
""")
    cfg = AlignConfig.from_file(cfg_path)
    assert cfg.pattern == "particle_*.mrc"
    assert cfg.options["max_iter"] == 6
