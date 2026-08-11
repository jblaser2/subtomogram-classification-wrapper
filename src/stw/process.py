"""
Subprocess launching for adapters. This is a deliberate rewrite of STA's
`_base.run_cmd`, which blocked until the subprocess exited (`subprocess.run`)
— fine for a batch benchmark harness, but incompatible with a live progress
bar. `run_streaming` tees each line to a log file *and* to a ProgressSink as
it's produced, and a `progress_patterns` list lets an adapter turn specific
log lines (e.g. "Class3D iteration 12 of 25") into a substep update.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from stw.progress import NullSink, ProgressSink


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
) -> tuple[int, TimingRecord]:
    """Run a command, streaming combined stdout+stderr line-by-line to a log
    file and to `sink`. Returns (returncode, TimingRecord). A sibling
    `<log_path>.timing.json` is written when `log_path` is given, matching the
    STA original's provenance behavior.
    """
    sink = sink or NullSink()
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
        )
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
