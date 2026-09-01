"""
Ties everything together for one `stw run`: resolve particles + mask once,
preflight every requested package (a missing requirement or a capability
mismatch skips that package rather than aborting the batch), dispatch jobs,
collect results, build class averages + the cross-package comparison, and
write a run report.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from stw import __version__
from stw.adapters import get_adapter_for_mode
from stw.compare import ComparisonReport, PackageLabels, build_comparison
from stw.config import RunConfig
from stw.masks.resolve import resolve_mask
from stw.process import cancel_scope
from stw.progress import NullSink, ProgressSink
from stw.requirements import PackageReport
from stw.results import PackageResult
from stw.spec import Job, MaskSpec, ParticleSet, WedgeSpec


@dataclass
class RunReport:
    stw_version: str
    config: dict
    preflight: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    comparison: dict | None = None
    n_particles_total: int | None = None
    n_particles_used: int | None = None

    def write(self, out_dir: str | Path) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "run_report.json").write_text(json.dumps(asdict(self), indent=2, default=str))
        (out / "summary.md").write_text(self._render_summary())

    def _render_summary(self) -> str:
        lines = [f"# stw run report (stw {self.stw_version})", ""]
        if self.n_particles_total is not None and self.n_particles_used != self.n_particles_total:
            lines.append(
                f"Subsampled to {self.n_particles_used}/{self.n_particles_total} particles "
                f"(seed={self.config.get('subsample_seed', 0)})."
            )
            lines.append("")
        lines.append("## Packages")
        for r in self.results:
            status = r["status"]
            line = f"- **{r['package']}** (k={r['k']}, seed={r['seed']}): {status}"
            if status == "ok":
                line += f" — {r.get('elapsed_sec', '?')}s, classes: {r.get('n_per_class', {})}"
            elif r.get("error"):
                line += f" — {r['error']}"
            lines.append(line)
            for w in r.get("warnings", []):
                lines.append(f"  - warning: {w}")
        if self.comparison:
            lines.append("")
            lines.append("## Cross-package comparison")
            for pair, ari in self.comparison.get("pairwise_ari", {}).items():
                lines.append(f"- {pair}: ARI={ari['ari']:.3f} (n={ari['n_shared']})")
            consensus = self.comparison.get("consensus", {})
            if consensus:
                lines.append(
                    f"- {consensus.get('n_full_agreement', 0)}/{consensus.get('n_shared', 0)} "
                    "particles have full agreement across all packages"
                )
        return "\n".join(lines) + "\n"


def run_config(
    config: RunConfig,
    *,
    progress: ProgressSink | None = None,
    dry_run: bool = False,
    cancel_flags: dict[str, threading.Event] | None = None,
) -> RunReport:
    """`cancel_flags`: optional {package: Event}, one entry per package a caller
    wants to be able to cancel mid-run (the GUI sets one per requested package;
    the CLI never passes this, so every CLI run stays uncancellable and behaves
    exactly as before -- see process.cancel_scope/JobCancelled)."""
    sink = progress or NullSink()

    particles = ParticleSet.discover(config.particles, config.pattern, config.pixel_size)
    n_particles_total = len(particles)
    if config.subsample is not None:
        particles = particles.subsample(config.subsample, config.subsample_seed)

    mask_spec = MaskSpec(
        kind=config.mask.kind, path=config.mask.path, center=config.mask.center,
        radius=config.mask.radius, half_height=config.mask.half_height, axis=config.mask.axis,
        edge=config.mask.edge,
    )
    wedge_spec = WedgeSpec(
        kind=config.wedge.kind, tilt_min=config.wedge.tilt_min, tilt_max=config.wedge.tilt_max,
        tilt_axis=config.wedge.tilt_axis, table=config.wedge.table,
    )

    # .resolve(): a relative out_dir must become absolute here, once, since every job's
    # workdir/cache_dir/mask_path derives from it and several adapters run multi-step
    # subprocesses with cwd set to a SUBDIRECTORY of out_dir -- a relative path passed as
    # a subprocess *argument* in that situation re-resolves against the new cwd, landing
    # in a nonexistent nested location (found via the GUI's relative "./stw_out" default,
    # but a bug in this shared code path, affecting the CLI equally for a relative out_dir).
    out_dir = Path(config.out_dir).resolve()
    # fingerprint(): reusing the same out_dir for two different particle sets (e.g. a
    # test fixture, then a real dataset) must NOT reuse cached prep built from the
    # other one -- no adapter's own internal caching accounts for particle-set
    # identity on its own (several key only on the mask, e.g. a same-radius sphere
    # mask on two different box sizes would otherwise collide too), so this is keyed
    # in once, at the root, for every package + the shared mask cache alike.
    particles_key = particles.fingerprint()
    cache_root = out_dir / "_cache" / particles_key
    mask_path = None if dry_run else resolve_mask(mask_spec, particles, cache_root)

    preflight: list[PackageReport] = []
    results: list[PackageResult] = []

    for package in config.packages:
        adapter_cls = get_adapter_for_mode(package, config.mode)
        report = adapter_cls.check_installed()
        preflight.append(report)
        cancel_event = (cancel_flags or {}).get(package)

        for k in config.k_values:
            for seed in config.seed_values:
                # Checked before doing any work, not just before adapter.run() --
                # catches a package cancelled while still queued behind an
                # earlier one (jobs run strictly sequentially within one
                # run_config() call), not just one killed mid-subprocess.
                if cancel_event is not None and cancel_event.is_set():
                    results.append(PackageResult(
                        package=adapter_cls.name, k=k, seed=seed, status="cancelled",
                    ))
                    continue

                if not report.installed:
                    if config.on_missing_requirement == "fail":
                        raise RuntimeError(f"{package}: missing requirements — {report.to_dict()}")
                    results.append(PackageResult(
                        package=adapter_cls.name, k=k, seed=seed, status="missing_requirements",
                    ))
                    continue

                incompatibilities = adapter_cls.validate_job_config(
                    k=k, mask_kind=mask_spec.kind, wedge_kind=wedge_spec.kind,
                    alignment_state=config.alignment_state, n_particles=len(particles),
                )
                errors = [i for i in incompatibilities if i.severity == "error"]
                warnings = [i.message for i in incompatibilities if i.severity == "warning"]
                if errors:
                    results.append(PackageResult(
                        package=adapter_cls.name, k=k, seed=seed, status="incompatible",
                        error="; ".join(e.message for e in errors), warnings=warnings,
                    ))
                    continue

                workdir = out_dir / package / f"k{k}" / f"seed{seed:02d}"
                cache_dir = out_dir / package / "_cache" / particles_key
                job = Job(
                    package=adapter_cls.name, particles=particles, mask_path=mask_path, mask_spec=mask_spec,
                    wedge=wedge_spec, alignment_state=config.alignment_state, k=k, seed=seed,
                    workdir=workdir, cache_dir=cache_dir, options=config.package_options.get(package, {}),
                )
                adapter = adapter_cls()

                if dry_run:
                    steps = adapter.plan(job)
                    results.append(PackageResult(
                        package=adapter_cls.name, k=k, seed=seed, status="skipped", warnings=warnings,
                        provenance={"planned_steps": [s.name for s in steps]},
                    ))
                    continue

                with cancel_scope(cancel_event):
                    result = adapter.run(job, progress=sink)
                # A killed subprocess surfaces as an ordinary status='failed' PackageResult
                # (every adapter's run() catches JobCancelled via its own broad `except
                # Exception` -- see process.JobCancelled's docstring); reclassify it here,
                # the one place that actually knows cancellation was requested, rather than
                # touching every adapter's exception handling.
                if result.status == "failed" and cancel_event is not None and cancel_event.is_set():
                    result.status = "cancelled"
                result.warnings.extend(warnings)
                results.append(result)

    comparison: ComparisonReport | None = None
    successful = [r for r in results if r.status == "ok" and r.labels]
    if not dry_run and len(successful) >= 2:
        packages = [PackageLabels(name=f"{r.package}_k{r.k}s{r.seed}", labels=r.labels) for r in successful]
        warn_map = {p.name: r.warnings for p, r in zip(packages, successful)}
        comparison = build_comparison(packages, out_png=out_dir / "comparison" / "cross_package.png", warnings=warn_map)

    report = RunReport(
        stw_version=__version__,
        config=json.loads(config.model_dump_json()),
        preflight=[p.to_dict() for p in preflight],
        results=[r.to_dict() for r in results],
        comparison=comparison.to_dict() if comparison else None,
        n_particles_total=n_particles_total,
        n_particles_used=len(particles),
    )
    if not dry_run:
        report.write(out_dir)
    return report
