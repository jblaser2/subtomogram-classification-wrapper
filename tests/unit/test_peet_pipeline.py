"""Unit tests for PEET's pure-Python prep/parsing functions — no IMOD/PEET
binaries needed, no library bindings, just numpy + text format logic."""
from pathlib import Path

import mrcfile
import numpy as np

from stw.adapters.peet import build_motl, build_prm, build_stacked_volume, parse_motl_classes


def _write(path, value, shape=(4, 4, 4)):
    with mrcfile.new(path, overwrite=True) as m:
        m.set_data(np.full(shape, value, dtype=np.float32))


def test_build_stacked_volume_shape_and_zscore(tmp_path):
    _write(tmp_path / "a.mrc", 5.0)
    _write(tmp_path / "b.mrc", 10.0)
    stacked = build_stacked_volume(tmp_path, ["a.mrc", "b.mrc"], box=4)
    assert stacked.shape == (8, 4, 4)
    # a constant-value volume has std=0 -> z-score falls back to mean-subtraction (all zero)
    assert np.allclose(stacked, 0.0)


def test_build_stacked_volume_places_particles_at_correct_z_offset(tmp_path):
    vol_a = np.zeros((4, 4, 4), dtype=np.float32)
    vol_a[0, 0, 0] = 100.0
    with mrcfile.new(tmp_path / "a.mrc", overwrite=True) as m:
        m.set_data(vol_a)
    _write(tmp_path / "b.mrc", 1.0)
    stacked = build_stacked_volume(tmp_path, ["a.mrc", "b.mrc"], box=4)
    assert stacked[0:4].std() > 0  # particle a's z-scored block
    assert np.allclose(stacked[4:8], 0.0)  # particle b (constant) z-scores to all zero


def test_build_motl_identity_has_zero_ccc():
    content = build_motl(3, identity=True)
    lines = content.strip().splitlines()
    assert len(lines) == 4  # header + 3 particles
    assert lines[1].startswith("0,")  # CCC=0
    assert lines[1].split(",")[3] == "1"  # pIndex


def test_build_motl_non_identity_has_ccc_one():
    content = build_motl(2, identity=False)
    lines = content.strip().splitlines()
    assert lines[1].startswith("1,")  # CCC=1, passes refThreshold
    assert lines[2].split(",")[3] == "2"  # pIndex


def test_build_prm_contains_required_fields():
    prm = build_prm(
        Path("/data/stack.mrc"), Path("/data/stack.mod"), Path("/data/iter1.csv"),
        Path("/data/mask.mrc"), box=32, pixel_size=5.0, n=10,
    )
    assert "fnVolume = {'/data/stack.mrc'}" in prm
    assert "flgWedgeWeight = 0" in prm  # wedge always off, matching this adapter's scope
    assert "pcaFnParticleMask = '/data/mask.mrc'" in prm
    assert "refThreshold  = [10, 10]" in prm


def test_build_prm_uses_custom_fn_output():
    prm = build_prm(
        Path("/data/stack.mrc"), Path("/data/stack.mod"), Path("/data/iter1.csv"),
        Path("/data/mask.mrc"), box=32, pixel_size=5.0, n=10, fn_output="myproject",
    )
    assert "fnOutput = 'myproject'" in prm


def test_parse_motl_classes_maps_pindex_to_class(tmp_path):
    content = build_motl(3, identity=False)
    lines = content.splitlines()
    # column 20 (index 19) is class; set particle 1 -> class 1, particle 2 -> class 2, particle 3 -> class 1
    parts = [lines[1].split(","), lines[2].split(","), lines[3].split(",")]
    parts[0][19] = "1"
    parts[1][19] = "2"
    parts[2][19] = "1"
    motl = tmp_path / "motl.csv"
    motl.write_text(lines[0] + "\n" + "\n".join(",".join(p) for p in parts) + "\n")

    labels = parse_motl_classes(motl, ["p1.mrc", "p2.mrc", "p3.mrc"])
    assert labels == {"p1.mrc": 1, "p2.mrc": 2, "p3.mrc": 1}


def test_parse_motl_classes_skips_malformed_lines(tmp_path):
    motl = tmp_path / "motl.csv"
    motl.write_text("header\ntoo,few,columns\n")
    labels = parse_motl_classes(motl, ["p1.mrc"])
    assert labels == {}
