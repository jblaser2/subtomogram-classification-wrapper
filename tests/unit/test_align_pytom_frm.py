"""Unit tests for stw.align.pytom_frm's pure-Python logic -- no PyTom install
needed (the module itself only needs pytom.lib._swig_frm at RUN time, not
import time)."""
from pathlib import Path

from stw.align.pytom_frm import _default_options, _latest_aligned_pl, _wedge_angle
from stw.spec import WedgeKind, WedgeSpec


def test_default_options_scale_with_box_and_stay_in_range():
    for box in (24, 32, 48, 80, 128):
        opts = _default_options(box)
        assert opts["bw_low"] < opts["bw_high"]
        assert opts["freq"] <= opts["bw_high"]
        assert opts["peak_offset"] >= 4
        # a real bug this project has hit before: bandwidth/frequency too close
        # to Nyquist crashes FRM's spherical-harmonic transform outright
        assert opts["bw_high"] < box / 2
        assert opts["freq"] < box / 2


def test_wedge_angle_none_means_full_coverage():
    assert _wedge_angle(WedgeSpec(kind=WedgeKind.NONE)) == 0.0


def test_wedge_angle_uniform_symmetric():
    wedge = WedgeSpec(kind=WedgeKind.UNIFORM, tilt_min=-60, tilt_max=60)
    assert _wedge_angle(wedge) == 30.0


def test_wedge_angle_never_negative():
    wedge = WedgeSpec(kind=WedgeKind.UNIFORM, tilt_min=-89, tilt_max=89)
    assert _wedge_angle(wedge) >= 0.0


def test_latest_aligned_pl_picks_highest_iteration(tmp_path):
    for i in (0, 1, 10, 2):
        (tmp_path / f"aligned_pl_iter{i}.xml").write_text("<FRMResult/>")
    latest = _latest_aligned_pl(tmp_path)
    assert latest.name == "aligned_pl_iter10.xml"  # numeric, not lexicographic


def test_latest_aligned_pl_none_when_missing(tmp_path):
    assert _latest_aligned_pl(tmp_path) is None


def test_latest_aligned_pl_returns_path(tmp_path):
    (tmp_path / "aligned_pl_iter3.xml").write_text("<FRMResult/>")
    result = _latest_aligned_pl(tmp_path)
    assert isinstance(result, Path)
    assert result == tmp_path / "aligned_pl_iter3.xml"
