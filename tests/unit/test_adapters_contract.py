"""
Contract tests run against EVERY registered adapter, including ones needing
MATLAB/GPU/compiled binaries this CI runner will never have. None of this
launches the actual package — it only checks that each adapter's static
declarations and pre-flight logic are well-formed, which is real coverage
even with zero cryoET software installed.
"""
from pathlib import Path

import pytest

from stw.adapters import registry
from stw.spec import AlignmentState, MaskKind, WedgeKind

ADAPTERS = list(registry().items())


@pytest.mark.parametrize("name,adapter_cls", ADAPTERS, ids=[n for n, _ in ADAPTERS])
def test_check_installed_never_raises(name, adapter_cls):
    report = adapter_cls.check_installed()
    assert report.package == name
    assert isinstance(report.installed, bool)


@pytest.mark.parametrize("name,adapter_cls", ADAPTERS, ids=[n for n, _ in ADAPTERS])
def test_capabilities_are_well_formed(name, adapter_cls):
    caps = adapter_cls.capabilities
    assert len(caps.mask_kinds) > 0
    assert len(caps.wedge) > 0
    assert len(caps.alignment_states) > 0
    assert caps.gpu in ("required", "optional", "unused")
    assert caps.seed_semantics in ("true_seed", "run_index", "none")


@pytest.mark.parametrize("name,adapter_cls", ADAPTERS, ids=[n for n, _ in ADAPTERS])
def test_validate_job_rejects_unaligned_unless_supported(name, adapter_cls):
    problems = adapter_cls.validate_job_config(
        k=2, mask_kind=MaskKind.NONE, wedge_kind=WedgeKind.NONE,
        alignment_state=AlignmentState.UNALIGNED, n_particles=1000,
    )
    if AlignmentState.UNALIGNED not in adapter_cls.capabilities.alignment_states:
        assert any(p.severity == "error" for p in problems)


@pytest.mark.parametrize("name,adapter_cls", ADAPTERS, ids=[n for n, _ in ADAPTERS])
def test_validate_job_rejects_too_few_particles(name, adapter_cls):
    caps = adapter_cls.capabilities
    problems = adapter_cls.validate_job_config(
        k=2, mask_kind=next(iter(caps.mask_kinds)), wedge_kind=WedgeKind.NONE,
        alignment_state=next(iter(caps.alignment_states)), n_particles=0,
    )
    assert any(p.field == "particles" for p in problems)


@pytest.mark.parametrize("name,adapter_cls", ADAPTERS, ids=[n for n, _ in ADAPTERS])
def test_plan_returns_steps_with_no_none_in_argv(name, adapter_cls, tmp_path, tiny_fixture_dir=None):
    from stw.spec import Job, MaskSpec, ParticleSet, WedgeSpec

    particles = ParticleSet(
        particle_dir=Path("/nonexistent"), pattern="*.mrc",
        files=("a.mrc", "b.mrc", "c.mrc", "d.mrc"), box=32, pixel_size=5.0,
    )
    job = Job(
        package=name, particles=particles, mask_path=None, mask_spec=MaskSpec(kind=MaskKind.NONE),
        wedge=WedgeSpec(), alignment_state=AlignmentState.FINE, k=2, seed=1,
        workdir=tmp_path / "work", cache_dir=tmp_path / "cache",
    )
    steps = adapter_cls().plan(job)
    assert len(steps) > 0
    for step in steps:
        assert all(arg is not None for arg in step.argv)
