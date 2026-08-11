from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from stw.adapters import registry

console = Console()


def list_packages() -> None:
    """List every registered package adapter and its install tier."""
    table = Table(title="stw registered packages")
    table.add_column("name")
    table.add_column("display name")
    table.add_column("tier")
    table.add_column("variable k")
    table.add_column("gpu")

    for name, adapter_cls in sorted(registry().items()):
        caps = adapter_cls.capabilities
        table.add_row(
            name, adapter_cls.display_name, str(adapter_cls.tier),
            "yes" if caps.variable_k else "no", caps.gpu,
        )
    console.print(table)
    raise typer.Exit(code=0)
