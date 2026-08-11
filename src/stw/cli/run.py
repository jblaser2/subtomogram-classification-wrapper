from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from stw.config import RunConfig
from stw.orchestrator import run_config
from stw.progress import RichProgressSink

console = Console()


def run(
    config_path: Path = typer.Argument(..., help="YAML/JSON RunConfig file"),
    package: list[str] = typer.Option(None, "--package", help="Override config's package list (repeatable)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the planned steps for every job without running"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="No live progress bars"),
) -> None:
    """Run every requested package against one particle set and write a
    comparison report. Missing requirements or an incompatible package are
    skipped, not fatal — see the run report for what happened."""
    cfg = RunConfig.from_file(config_path)
    if package:
        cfg = cfg.model_copy(update={"packages": list(package)})

    sink = None if (dry_run or quiet) else RichProgressSink()
    try:
        report = run_config(cfg, progress=sink, dry_run=dry_run)
    finally:
        if sink is not None:
            sink.stop()

    if dry_run:
        console.print("[bold]Dry run — planned steps per package:[/bold]")
        for r in report.results:
            console.print(f"  {r['package']} k={r['k']} seed={r['seed']}: {r['status']}")
            for step in r.get("provenance", {}).get("planned_steps", []):
                console.print(f"    - {step}")
        return

    console.print(f"\n[bold]Run complete.[/bold] Report written to {cfg.out_dir}/run_report.json")
    n_ok = sum(1 for r in report.results if r["status"] == "ok")
    n_total = len(report.results)
    console.print(f"{n_ok}/{n_total} jobs succeeded.")
    for r in report.results:
        if r["status"] != "ok":
            console.print(f"  [yellow]{r['package']} k={r['k']} seed={r['seed']}: {r['status']}[/yellow]"
                          + (f" — {r['error']}" if r.get("error") else ""))
