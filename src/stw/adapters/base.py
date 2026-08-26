"""
The Adapter contract every package plugin implements. An adapter wraps a
package's EXISTING launcher (or, in preview mode, a lightweight approximation
of it) — it never reimplements the package's algorithm.

Design note: `check_installed()`/`validate_job()` never launch the package —
that's what makes "see requirements before you opt in" a real, always-current
answer rather than a docs page that goes stale.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from stw.capabilities import Capabilities, Incompatibility, validate_job
from stw.progress import NullSink, ProgressSink
from stw.requirements import InstallTier, PackageReport, Requirement, run_checks
from stw.results import PackageResult
from stw.spec import Job


@dataclass(frozen=True)
class PlannedStep:
    name: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: Path | None = None
    cached: bool = False


class Adapter(ABC):
    name: ClassVar[str]
    display_name: ClassVar[str]
    tier: ClassVar[InstallTier]
    capabilities: ClassVar[Capabilities]
    requirements: ClassVar[tuple[Requirement, ...]] = ()
    steps: ClassVar[tuple[str, ...]] = ("run",)
    # One or two plain-language sentences on the real classification algorithm this
    # adapter drives -- surfaced by `stw gui`'s package picker and docs/packages.md so
    # "what does this package actually do" doesn't require reading adapter source or
    # docstrings. Every adapter should set this; the empty default is only a fallback.
    algorithm: ClassVar[str] = ""
    progress_patterns: ClassVar[tuple[tuple[re.Pattern, str], ...]] = ()

    # --- pre-flight only; must never launch the package -----------------
    @classmethod
    def check_installed(cls, *, deep: bool = False) -> PackageReport:
        checks = run_checks(cls.requirements)
        non_optional_ok = all(c.ok for c in checks if not c.requirement.optional)
        degraded = [c.message for c in checks if c.requirement.optional and not c.ok]
        return PackageReport(
            package=cls.name,
            display_name=cls.display_name,
            tier=cls.tier,
            installed=non_optional_ok,
            checks=checks,
            degraded=degraded,
        )

    @classmethod
    def validate_job_config(
        cls, *, k: int, mask_kind, wedge_kind, alignment_state, n_particles: int
    ) -> list[Incompatibility]:
        return validate_job(
            cls.name, cls.capabilities, k=k, mask_kind=mask_kind, wedge_kind=wedge_kind,
            alignment_state=alignment_state, n_particles=n_particles,
        )

    # --- execution --------------------------------------------------------
    @abstractmethod
    def plan(self, job: Job) -> list[PlannedStep]:
        """Return the concrete steps this job would run, without running them
        (powers `--dry-run`)."""

    @abstractmethod
    def run(self, job: Job, progress: ProgressSink | None = None) -> PackageResult:
        """Execute the job end to end (plan -> launch -> collect) and return a
        populated PackageResult. Must not raise for an ordinary run failure —
        catch and return status='failed' with `.error` set; only requirement/
        incompatibility failures are expected to be caught by the caller
        before `run()` is ever invoked."""

    def collect(self, job: Job) -> dict[str, int]:
        """Parse this package's native output into {particle: class_int}.
        Most adapters call this from within run(); exposed separately so
        tests can exercise output-parsing without a real launch."""
        raise NotImplementedError

    # convenience for subclasses
    @staticmethod
    def _null_sink() -> ProgressSink:
        return NullSink()
