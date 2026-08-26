"""Unit tests for PyTom's classified ParticleList XML parsing and the
wedge-angle conversion — pure functions, testable without the pytom_env
conda env or any real PyTom output."""
from pathlib import Path

from stw.adapters.pytom import _mpirun_prefix, _wedge_angle, latest_classified_xml, parse_classified_xml
from stw.spec import AlignmentState, Job, MaskSpec, ParticleSet, WedgeKind, WedgeSpec

_XML = """<?xml version="1.0"?>
<ParticleList>
  <Particle Filename="/data/particle_001.mrc">
    <Class Name="0"/>
  </Particle>
  <Particle Filename="/data/particle_002.mrc">
    <Class Name="1"/>
  </Particle>
</ParticleList>
"""


def _job(wedge=WedgeSpec()):
    particles = ParticleSet(particle_dir=Path("/data"), pattern="*.mrc", files=(), box=32, pixel_size=5.0)
    return Job(
        package="pytom", particles=particles, mask_path=None, mask_spec=MaskSpec(),
        wedge=wedge, alignment_state=AlignmentState.FINE, k=2, seed=1,
        workdir=Path("/tmp/x"), cache_dir=Path("/tmp/x/_cache"),
    )


def test_parse_classified_xml(tmp_path):
    """PyTom's own <Class Name="K"/> is 0-indexed; stw's convention (every
    other adapter) is 1-indexed, so this must come back +1'd."""
    xml = tmp_path / "classified_pl_iter3.xml"
    xml.write_text(_XML)
    labels = parse_classified_xml(xml)
    assert labels == {"particle_001.mrc": 1, "particle_002.mrc": 2}


def test_latest_classified_xml_picks_highest_iter(tmp_path):
    for i in (0, 1, 10, 2):
        (tmp_path / f"classified_pl_iter{i}.xml").write_text(_XML)
    latest = latest_classified_xml(tmp_path)
    assert latest.name == "classified_pl_iter10.xml"  # numeric, not lexicographic


def test_latest_classified_xml_none_when_missing(tmp_path):
    assert latest_classified_xml(tmp_path) is None


def test_wedge_angle_none_means_full_coverage():
    assert _wedge_angle(_job()) == 0.0


def test_wedge_angle_uniform_symmetric():
    wedge = WedgeSpec(kind=WedgeKind.UNIFORM, tilt_min=-60, tilt_max=60)
    assert _wedge_angle(_job(wedge)) == 30.0


def test_wedge_angle_uniform_asymmetric_averages():
    wedge = WedgeSpec(kind=WedgeKind.UNIFORM, tilt_min=-50, tilt_max=70)
    # max_tilt = (50+70)/2 = 60 -> missing wedge half-angle = 30
    assert _wedge_angle(_job(wedge)) == 30.0


def test_wedge_angle_never_negative():
    wedge = WedgeSpec(kind=WedgeKind.UNIFORM, tilt_min=-89, tilt_max=89)
    assert _wedge_angle(_job(wedge)) >= 0.0


def test_mpirun_prefix_omits_flag_for_non_root(monkeypatch):
    monkeypatch.setattr("os.geteuid", lambda: 1000, raising=False)
    argv = _mpirun_prefix("4")
    assert argv == ["mpirun", "-np", "4"]


def test_mpirun_prefix_adds_flag_for_root(monkeypatch):
    """A container's default user is root, and OpenMPI's mpirun/prterun
    refuses to run at all as root without this flag -- found while
    validating the Tier A/B Docker image."""
    monkeypatch.setattr("os.geteuid", lambda: 0, raising=False)
    argv = _mpirun_prefix("4")
    assert argv == ["mpirun", "-np", "4", "--allow-run-as-root"]
