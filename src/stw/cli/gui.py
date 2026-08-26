from __future__ import annotations

import threading
import webbrowser

import typer
from rich.console import Console

console = Console()


def gui(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8765, help="Bind port"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open a browser tab"),
) -> None:
    """Launch stw's local web GUI (needs the `gui` extra) and open it in your
    browser. Runs entirely on localhost -- driving the same core library as
    every other `stw` command, not a separate implementation."""
    try:
        import uvicorn
    except ImportError as e:
        console.print(
            "[red]The GUI needs the `gui` extra:[/red] "
            "pip install 'subtomogram-classification-wrapper[gui]'"
        )
        raise typer.Exit(code=1) from e

    from stw.gui.server import create_app

    app = create_app()
    url = f"http://{host}:{port}"
    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    console.print(f"[bold]stw gui[/bold] running at [cyan]{url}[/cyan] — Ctrl-C to stop")
    uvicorn.run(app, host=host, port=port, log_level="warning")
