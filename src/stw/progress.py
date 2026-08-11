"""
ProgressSink — how a running Job reports itself upward, whether that's a CLI
progress bar today or a GUI's live view later. Deliberately a Protocol (not a
base class) so implementations stay swappable without inheritance.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


class ProgressSink(Protocol):
    def start_job(self, package: str, steps: list[str]) -> None: ...
    def step(self, package: str, name: str, index: int, total: int) -> None: ...
    def substep(self, package: str, text: str) -> None: ...
    def log_line(self, package: str, line: str) -> None: ...
    def finish_job(self, package: str, ok: bool, message: str = "") -> None: ...


class NullSink:
    def start_job(self, package: str, steps: list[str]) -> None:
        pass

    def step(self, package: str, name: str, index: int, total: int) -> None:
        pass

    def substep(self, package: str, text: str) -> None:
        pass

    def log_line(self, package: str, line: str) -> None:
        pass

    def finish_job(self, package: str, ok: bool, message: str = "") -> None:
        pass


class RichProgressSink:
    """Live multi-bar CLI progress, one bar per package."""

    def __init__(self) -> None:
        from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.fields[package]}[/bold]"),
            BarColumn(),
            TextColumn("{task.fields[status]}"),
            TimeElapsedColumn(),
        )
        self._progress.start()
        self._tasks: dict[str, int] = {}

    def start_job(self, package: str, steps: list[str]) -> None:
        task_id = self._progress.add_task("", total=len(steps) or 1, package=package, status="starting...")
        self._tasks[package] = task_id

    def step(self, package: str, name: str, index: int, total: int) -> None:
        if package in self._tasks:
            self._progress.update(self._tasks[package], completed=index, total=total, status=name)

    def substep(self, package: str, text: str) -> None:
        if package in self._tasks:
            self._progress.update(self._tasks[package], status=text)

    def log_line(self, package: str, line: str) -> None:
        pass  # full logs go to the per-job log file, not the live bar

    def finish_job(self, package: str, ok: bool, message: str = "") -> None:
        if package in self._tasks:
            status = ("[green]done[/green] " if ok else "[red]failed[/red] ") + message
            self._progress.update(self._tasks[package], status=status)

    def stop(self) -> None:
        self._progress.stop()


@dataclass
class ProgressEvent:
    event: str  # start_job | step | substep | log_line | finish_job
    package: str
    payload: dict


class JsonlProgressSink:
    """One JSON object per line, for CI or a future GUI to consume."""

    def __init__(self, stream=None) -> None:
        self._stream = stream or sys.stdout

    def _emit(self, event: str, package: str, **payload) -> None:
        record = ProgressEvent(event=event, package=package, payload=payload)
        self._stream.write(json.dumps(asdict(record)) + "\n")
        self._stream.flush()

    def start_job(self, package: str, steps: list[str]) -> None:
        self._emit("start_job", package, steps=steps)

    def step(self, package: str, name: str, index: int, total: int) -> None:
        self._emit("step", package, name=name, index=index, total=total)

    def substep(self, package: str, text: str) -> None:
        self._emit("substep", package, text=text)

    def log_line(self, package: str, line: str) -> None:
        self._emit("log_line", package, line=line)

    def finish_job(self, package: str, ok: bool, message: str = "") -> None:
        self._emit("finish_job", package, ok=ok, message=message)


def sink_to_file(path: str | Path) -> JsonlProgressSink:
    return JsonlProgressSink(Path(path).open("w"))
