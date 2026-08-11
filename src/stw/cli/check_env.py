from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from stw.adapters import registry

console = Console()


def check_env(
    package: str | None = typer.Option(None, "--package", "-p", help="Check only this package"),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Report install status and requirements for every registered package,
    WITHOUT launching any of them. This is the same check the orchestrator
    runs before every `stw run`, and the artifact to paste into a bug report."""
    reg = registry()
    names = [package] if package else sorted(reg)
    reports = []
    for name in names:
        if name not in reg:
            console.print(f"[red]unknown package: {name}[/red]")
            raise typer.Exit(code=1)
        reports.append(reg[name].check_installed())

    if as_json:
        typer.echo(json.dumps([r.to_dict() for r in reports], indent=2))
        return

    for r in reports:
        status = "[green]installed[/green]" if r.installed else "[red]missing requirements[/red]"
        console.print(f"\n[bold]{r.display_name}[/bold] ({r.package}, tier={r.tier}) — {status}")
        table = Table(show_header=True, header_style="bold")
        table.add_column("requirement")
        table.add_column("ok")
        table.add_column("message")
        for c in r.checks:
            if c.ok:
                mark = "[green]y[/green]"
            elif c.requirement.optional:
                mark = "[yellow]optional[/yellow]"
            else:
                mark = "[red]n[/red]"
            table.add_row(f"{c.requirement.kind}: {c.requirement.name}", mark, c.message)
        if r.checks:
            console.print(table)
        else:
            console.print("  (no external requirements)")
        for note in r.degraded:
            console.print(f"  [yellow]degraded:[/yellow] {note}")
