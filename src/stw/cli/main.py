from __future__ import annotations

import typer

from stw import __version__
from stw.cli import check_env, gui, init, list_, mask, run

app = typer.Typer(
    name="stw",
    help="Run subtomogram classification across many cryoET packages with one config.",
    no_args_is_help=True,
)

app.command("list")(list_.list_packages)
app.command("check-env")(check_env.check_env)
app.command("init")(init.init_config)
app.command("run")(run.run)
app.command("mask")(mask.build_mask)
app.command("gui")(gui.gui)


@app.callback(invoke_without_command=False)
def _version_callback() -> None:
    pass


@app.command("version")
def version() -> None:
    """Print the installed stw version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
