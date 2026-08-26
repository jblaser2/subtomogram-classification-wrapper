# GUI

A local, no-install-elsewhere web GUI — the same idea as launching `napari`
from the command line: it starts a local server on your own machine, opens a
browser tab, and never leaves `localhost`. It drives the exact same
`RunConfig`/`registry()`/`run_config()` core the CLI does — not a second
implementation of anything.

```console
pip install 'subtomogram-classification-wrapper[gui]'
stw gui
```

This starts a server at `http://127.0.0.1:8765` and opens it in your default
browser. Options:

```console
stw gui --port 9000          # different port
stw gui --no-browser         # print the URL instead of opening a tab
stw gui --host 0.0.0.0       # bind beyond localhost (LAN-reachable — see note below)
```

!!! warning
    `stw gui` binds to `127.0.0.1` by default on purpose: there's no
    authentication, and it runs local shell commands (conda, MATLAB, mpiexec,
    ...) on whatever machine it's started on. Only pass `--host 0.0.0.0` on a
    trusted network, and never on a machine reachable from the open internet.

## What it does

1. **Particles / mask / wedge / classification** — a form covering
   `RunConfig`'s core fields (particle directory, pattern, pixel size,
   alignment state, mask kind + params, wedge kind + tilt range, `k`, seeds,
   mode, output directory). This mirrors the YAML config the CLI takes, not
   a separate schema.
2. **Packages** — every registered adapter, live install status (green/red
   dot, from the same `check_installed()` the CLI's `stw check-env` runs),
   pre-checked when installed.
3. **Run** — submits the config, then streams live per-package progress
   (the same step/substep events `stw run`'s Rich progress bars show) over
   Server-Sent Events.
4. **Results** — a table of every job's status/timing/class sizes, an
   on-demand rendered class-average panel (central Z-slice per class — MRCs
   aren't browser-displayable, so this is generated server-side, cached to
   disk on first request), and the cross-package comparison figure when at
   least two packages succeeded.

## Design notes

- **Single-user, local-only, no persistence.** Runs live in an in-memory
  registry for the life of the server process — restarting `stw gui` loses
  the list of past runs (the underlying `run_report.json`/predictions/class
  averages on disk are untouched, same as any `stw run`). This is
  deliberately not a multi-user dashboard.
- **The form is hand-written, not schema-generated**, even though
  `RunConfig.model_json_schema()` is exposed at `/api/schema` (and was the
  original design intent) — a fully generic JSON-schema-to-form renderer
  handling nested objects, enums, and `int | list[int]` unions is real work
  with limited payoff over a form that already knows `RunConfig`'s actual
  (small, stable) field set. The schema endpoint stays available for future
  use (client-side validation hints, a future scriptable client, ...).
- **No file upload** — the particle directory is a path on the same machine
  the server is running on, exactly like the CLI. This is not a hosted
  service; there is nothing to upload to.
- Every run's progress is real, not simulated: the GUI's `QueueProgressSink`
  is a second implementation of the same `ProgressSink` protocol
  `RichProgressSink`/`JsonlProgressSink` already implement (see
  `stw.progress`), pushing the identical event stream into a queue instead
  of a terminal or a file.
