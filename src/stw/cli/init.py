from __future__ import annotations

from pathlib import Path

import typer

_TEMPLATE = """\
# stw run config — see docs/config-reference.md for every field
particles: ./subtomos
pattern: "*.mrc"
k: 2
mask:
  kind: auto        # none | sphere | cylinder | file | auto
alignment_state: fine   # unaligned | rough | fine — most packages here require fine
packages: [hac]
out_dir: ./stw_out
"""


def init_config(
    out: Path = typer.Option(Path("stw_config.yaml"), "--out", "-o", help="Where to write the starter config"),
    schema: bool = typer.Option(False, "--schema", help="Print the RunConfig JSON Schema instead"),
) -> None:
    """Write a starter YAML config, or print the full JSON Schema for GUI/tooling use."""
    if schema:
        import json

        from stw.config import RunConfig

        typer.echo(json.dumps(RunConfig.model_json_schema(), indent=2))
        return

    if out.exists():
        typer.confirm(f"{out} already exists — overwrite?", abort=True)
    out.write_text(_TEMPLATE)
    typer.echo(f"wrote {out}")
