"""Unit tests for RELION's pure-Python prep/parsing functions — no
relion_refine binary needed, no library bindings, just numpy + text format
logic."""
from pathlib import Path

import numpy as np

from stw.adapters.relion import (
    _max_tilt,
    build_star,
    build_wedge_ctf,
    parse_relion_classes,
    parse_star_particles,
)
from stw.spec import AlignmentState, Job, MaskSpec, ParticleSet, WedgeKind, WedgeSpec


def _job(wedge=WedgeSpec()):
    particles = ParticleSet(particle_dir=Path("/data"), pattern="*.mrc", files=(), box=32, pixel_size=5.0)
    return Job(
        package="relion", particles=particles, mask_path=None, mask_spec=MaskSpec(),
        wedge=wedge, alignment_state=AlignmentState.FINE, k=2, seed=1,
        workdir=Path("/tmp/x"), cache_dir=Path("/tmp/x/_cache"),
    )


def test_max_tilt_none_means_full_coverage():
    assert _max_tilt(_job()) == 90.0


def test_max_tilt_uniform_symmetric():
    wedge = WedgeSpec(kind=WedgeKind.UNIFORM, tilt_min=-50, tilt_max=50)
    assert _max_tilt(_job(wedge)) == 50.0


def test_max_tilt_uniform_asymmetric_averages():
    wedge = WedgeSpec(kind=WedgeKind.UNIFORM, tilt_min=-40, tilt_max=60)
    assert _max_tilt(_job(wedge)) == 50.0


def test_build_wedge_ctf_full_coverage_is_all_ones():
    ctf = build_wedge_ctf(32, 90.0)
    assert np.allclose(ctf, 1.0)


def test_build_wedge_ctf_partial_coverage_is_between_zero_and_one():
    ctf = build_wedge_ctf(32, 50.0)
    frac = ctf.mean()
    assert 0.0 < frac < 1.0


def test_build_wedge_ctf_narrower_tilt_means_less_coverage():
    wide = build_wedge_ctf(32, 70.0).mean()
    narrow = build_wedge_ctf(32, 30.0).mean()
    assert narrow < wide


def test_build_wedge_ctf_keeps_dc_term():
    ctf = build_wedge_ctf(32, 0.0)
    c = 32 // 2
    assert ctf[c, c, c] == 1.0


def test_build_star_contains_both_blocks_and_all_particles():
    content = build_star(Path("/data"), ["p1.mrc", "p2.mrc"], Path("/data/ctf.mrc"), 5.0, 32)
    assert "data_optics" in content
    assert "data_particles" in content
    assert "/data/p1.mrc" in content
    assert "/data/p2.mrc" in content
    assert "/data/ctf.mrc" in content


def test_parse_star_particles_roundtrip(tmp_path):
    content = build_star(Path("/data"), ["p1.mrc", "p2.mrc"], Path("/data/ctf.mrc"), 5.0, 32)
    star = tmp_path / "test.star"
    star.write_text(content)
    rows = parse_star_particles(star)
    assert len(rows) == 2
    assert rows[0]["_rlnImageName"] == "/data/p1.mrc"
    assert rows[0]["_rlnCtfImage"] == "/data/ctf.mrc"


def test_parse_relion_classes_maps_basenames_to_class_numbers(tmp_path):
    input_content = build_star(Path("/data"), ["p1.mrc", "p2.mrc"], Path("/data/ctf.mrc"), 5.0, 32)
    input_star = tmp_path / "input.star"
    input_star.write_text(input_content)

    output_content = input_content.replace(
        "_rlnOriginZAngst #9\n", "_rlnOriginZAngst #9\n_rlnClassNumber #10\n"
    )
    lines = output_content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("/data/p1.mrc"):
            lines[i] = line + " 1"
        elif line.startswith("/data/p2.mrc"):
            lines[i] = line + " 2"
    output_star = tmp_path / "output.star"
    output_star.write_text("\n".join(lines) + "\n")

    labels = parse_relion_classes(output_star, input_star)
    assert labels == {"p1.mrc": 1, "p2.mrc": 2}


def test_parse_relion_classes_raises_on_empty_output(tmp_path):
    input_star = tmp_path / "input.star"
    input_star.write_text(build_star(Path("/data"), ["p1.mrc"], Path("/data/ctf.mrc"), 5.0, 32))
    empty_star = tmp_path / "empty.star"
    empty_star.write_text("data_particles\n\nloop_\n_rlnImageName #1\n")

    import pytest

    with pytest.raises(RuntimeError):
        parse_relion_classes(empty_star, input_star)
