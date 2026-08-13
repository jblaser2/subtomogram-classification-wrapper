"""Unit tests for ProTomo's pure-Python prep/parsing functions -- no ProTomo
binaries or MATLAB needed, just string/regex logic."""
from pathlib import Path

from stw.adapters.protomo import (
    build_param_template,
    build_series_prep,
    parse_tomoinfo_cls,
    set_cycle_classes,
)


def test_build_series_prep_lists_files_in_order():
    prep = build_series_prep(["b.mrc", "a.mrc"])
    lines = prep.strip().splitlines()
    assert lines[0] == "search stacks"
    assert lines[2] == "attach b.mrc"
    assert lines[3] == "attach a.mrc"
    assert lines[-1] == "save dataset.i3i"


def test_build_param_template_contains_resolved_fields():
    tpl = build_param_template(
        Path("/data/stacks"), Path("/data/mask.i3i"), box=80, k=3, msafact=40, clsfact="1-10",
    )
    assert 'export DATADIR="/data/stacks"' in tpl
    assert 'export MSAMASK="/data/mask.i3i"' in tpl
    assert 'export MOTIFSIZE="80 80 80"' in tpl
    assert 'export CLASSES="3"' in tpl
    assert 'export CLSMIN="3"' in tpl
    assert 'export CLSMAX="3"' in tpl
    assert 'export CLSFACT="1-10"' in tpl
    assert 'export MSAFACT=40' in tpl
    assert 'export WDGCOMP="false"' in tpl  # wedge always off


def test_build_param_template_elliptic_mask_size_scales_with_box():
    tpl_small = build_param_template(Path("/d"), Path("/m"), box=24, k=2, msafact=10, clsfact="1-5")
    tpl_large = build_param_template(Path("/d"), Path("/m"), box=80, k=2, msafact=10, clsfact="1-5")
    assert "elliptic 9 9 9" in tpl_small  # max(24//2-3, 4) = 9
    assert "elliptic 37 37 37" in tpl_large  # max(80//2-3, 4) = 37


def test_set_cycle_classes_rewrites_only_classification_lines(tmp_path):
    param_sh = tmp_path / "param.sh"
    param_sh.write_text(
        'export DATADIR="/data/stacks"\n'
        'export CLASSES="2"\n'
        'export CLSMIN="2"\n'
        'export CLSMAX="2"\n'
        'export CLSFACT="1-10"\n'
        'export MSAFACT=40\n'
    )
    set_cycle_classes(param_sh, k=3, clsfact="1-4")
    text = param_sh.read_text()
    assert 'export CLASSES="3"' in text
    assert 'export CLSMIN="3"' in text
    assert 'export CLSMAX="3"' in text
    assert 'export CLSFACT="1-4"' in text
    assert 'export DATADIR="/data/stacks"' in text  # untouched
    assert 'export MSAFACT=40' in text  # untouched


def test_parse_tomoinfo_cls_maps_index_to_filename():
    output = "\n".join([
        "tomoinfo: could not load libi3tiffio.so, TiffioModule disabled",
        "[ 2 ] 0 0",
        "[ 2 ] 1 1",
        "[ 2 ] 2 0",
    ])
    labels = parse_tomoinfo_cls(output, ["p0.mrc", "p1.mrc", "p2.mrc"])
    assert labels == {"p0.mrc": 0, "p1.mrc": 1, "p2.mrc": 0}


def test_parse_tomoinfo_cls_ignores_malformed_lines():
    output = "some warning\n[ not-bracketed ] garbage\n[ 1 ] 0 5\n"
    labels = parse_tomoinfo_cls(output, ["p0.mrc"])
    assert labels == {"p0.mrc": 5}


def test_parse_tomoinfo_cls_ignores_out_of_range_index():
    output = "[ 1 ] 7 2\n"
    labels = parse_tomoinfo_cls(output, ["p0.mrc"])
    assert labels == {}
