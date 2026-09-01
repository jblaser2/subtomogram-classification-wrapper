"""
Subprocess launching for adapters. This is a deliberate rewrite of STA's
`_base.run_cmd`, which blocked until the subprocess exited (`subprocess.run`)
— fine for a batch benchmark harness, but incompatible with a live progress
bar. `run_streaming` tees each line to a log file *and* to a ProgressSink as
it's produced, and a `progress_patterns` list lets an adapter turn specific
log lines (e.g. "Class3D iteration 12 of 25") into a substep update.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from stw.progress import NullSink, ProgressSink


class JobCancelled(RuntimeError):
    """Raised by run_streaming() when a live subprocess was killed because its
    cancel_event was set -- e.g. the GUI's per-package Cancel button. Every
    adapter's run() already wraps its run_streaming() calls in a broad
    `except Exception` (see adapters/base.py's "must not raise" contract), so
    this surfaces as an ordinary status='failed' PackageResult with this
    message -- the orchestrator then rewrites that to status='cancelled' once
    it confirms the matching cancel_event is set (see orchestrator.run_config())."""


# Read implicitly by run_streaming() when no explicit cancel_event is passed,
# so adapters never need their own cancel_event parameter or import -- the
# orchestrator sets this once per job (see stw.process.cancel_scope) and every
# run_streaming() call made underneath, however deep in an adapter's own call
# stack, picks it up automatically. None (the default) means "not cancellable",
# which is every CLI run today -- only the GUI wires up real Event objects.
_CURRENT_CANCEL_EVENT: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "_CURRENT_CANCEL_EVENT", default=None
)


@contextmanager
def cancel_scope(event: threading.Event | None):
    """Makes `event` the cancel_event every run_streaming() call underneath
    this `with` block observes by default, for the duration of the block."""
    token = _CURRENT_CANCEL_EVENT.set(event)
    try:
        yield
    finally:
        _CURRENT_CANCEL_EVENT.reset(token)


def _watch_for_cancel(proc: subprocess.Popen, cancel_event: threading.Event) -> None:
    """Runs in a daemon thread alongside run_streaming()'s main read loop --
    that loop only wakes up when the subprocess produces a line of output, so
    a plain per-line check would leave a silent (no-output-for-a-while) job
    uncancellable until it happened to print again. Polling independently here
    keeps kill latency bounded (~0.5s) regardless of the subprocess's own
    output behavior."""
    while proc.poll() is None:
        if cancel_event.wait(timeout=0.5):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                return  # already exited between the poll() check and here
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            return


@dataclass
class TimingRecord:
    argv: list[str]
    cwd: str | None
    start_epoch: float
    end_epoch: float
    elapsed_sec: float
    returncode: int

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2))


def run_streaming(
    argv: list[str],
    *,
    package: str = "",
    env_extra: dict[str, str] | None = None,
    cwd: str | Path | None = None,
    log_path: str | Path | None = None,
    sink: ProgressSink | None = None,
    progress_patterns: tuple[tuple[re.Pattern, str], ...] = (),
    cancel_event: threading.Event | None = None,
) -> tuple[int, TimingRecord]:
    """Run a command, streaming combined stdout+stderr line-by-line to a log
    file and to `sink`. Returns (returncode, TimingRecord). A sibling
    `<log_path>.timing.json` is written when `log_path` is given, matching the
    STA original's provenance behavior.

    `cancel_event`: if set (by the watcher thread noticing it's flagged) while
    this subprocess is running, the whole process group is killed and
    JobCancelled is raised instead of returning. Defaults to whatever
    cancel_scope() currently has in effect, so adapters never pass this
    explicitly. Every CLI run leaves this None throughout (see
    _CURRENT_CANCEL_EVENT's docstring), so `start_new_session` only changes
    the process-group behavior a GUI-driven, genuinely-cancellable run
    actually asked for -- a bare CLI `stw run` still puts subprocesses in the
    terminal's own process group, so Ctrl-C keeps killing them exactly as
    before.
    """
    sink = sink or NullSink()
    if cancel_event is None:
        cancel_event = _CURRENT_CANCEL_EVENT.get()
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)

    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "w") if log_path else None

    start = time.time()
    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd) if cwd else None, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            start_new_session=cancel_event is not None,
        )
        if cancel_event is not None:
            threading.Thread(target=_watch_for_cancel, args=(proc, cancel_event), daemon=True).start()
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            if log_file:
                log_file.write(line + "\n")
            sink.log_line(package, line)
            for pattern, label in progress_patterns:
                m = pattern.search(line)
                if m:
                    sink.substep(package, label.format(*m.groups(), **m.groupdict()))
        returncode = proc.wait()
    finally:
        if log_file:
            log_file.close()

    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelled(f"{package or argv[0]} cancelled by user")
    end = time.time()

    timing = TimingRecord(
        argv=[str(a) for a in argv],
        cwd=str(cwd) if cwd else None,
        start_epoch=start,
        end_epoch=end,
        elapsed_sec=round(end - start, 3),
        returncode=returncode,
    )
    if log_path:
        timing.write(f"{log_path}.timing.json")
    return returncode, timing


def conda_run_argv(env: str, *cmd: str) -> list[str]:
    return ["conda", "run", "-n", env, *cmd]
