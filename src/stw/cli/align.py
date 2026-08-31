from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from stw.align import AlignConfig, check_installed, run_pytom_alignment
from stw.progress import RichProgressSink

console = Console()


def align(
    config_path: Path = typer.Argument(..., help="YAML/JSON AlignConfig file"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="No live progress bar"),
) -> None:
    """Finely align roughly-aligned particles (PyTom's real FRM, a genuine
    global SO(3) search) into a new directory that feeds straight into a
    normal `stw run` (alignment_state: fine). Needs a real PyTom install
    plus a compiled FRM extension — see docs/install/pytom.md and
    scripts/compile_pytom_frm.sh. The alignment mask should NOT be the same
    mask you plan to classify with — see docs/align.md for why."""
    reports = check_installed()
    missing = [c for c in reports if not c.ok]
    if missing:
        console.print("[red]stw align is not available on this machine:[/red]")
        for c in missing:
            console.print(f"  [red]-[/red] {c.requirement.kind}: {c.requirement.name} — {c.message}")
            if c.requirement.install_hint:
                console.print(f"    [yellow]hint:[/yellow] {c.requirement.install_hint}")
        raise typer.Exit(code=1)

    cfg = AlignConfig.from_file(config_path)
    sink = None if quiet else RichProgressSink()
    try:
        report = run_pytom_alignment(cfg, progress=sink)
    finally:
        if sink is not None:
            sink.stop()

    if report.status != "ok":
        console.print(f"[red]stw align failed:[/red] {report.error}")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]Alignment complete.[/bold] {report.n_particles} particles in "
                  f"{report.elapsed_sec:.1f}s")
    console.print(f"  Aligned particles: [cyan]{report.aligned_particle_dir}[/cyan]")
    console.print(f"  Poses CSV:         {report.poses_csv}")
    for w in report.warnings:
        console.print(f"  [yellow]note:[/yellow] {w}")
    console.print(
        "\nPoint a normal `stw run` config's `particles:` at the aligned directory above "
        "(alignment_state: fine, the default) to classify the result."
    )
