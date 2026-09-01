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

0. **Align first (optional)** — a collapsible section above the main particle
   directory field, for roughly-aligned input specifically (see
   [`docs/align.md`](align.md) — a real global search, PyTom's FRM, not a
   from-scratch aligner, and it needs its own compiled extension most PyTom
   installs don't have; the section shows what's missing if it's
   unavailable). Uses its **own** mask fields, deliberately separate from the
   classification mask below — reusing one mask for both has actually
   destroyed classification signal before, see `docs/align.md`. On success,
   shows a live preview of the aligned average and a "Use this aligned
   output →" button that fills the main particle directory/pattern/pixel
   size fields for you.
1. **Particles / mask / wedge / classification** — a form covering
   `RunConfig`'s core fields (particle directory, pattern, pixel size,
   alignment state, mask kind + params, wedge kind + tilt range, `k`, seeds,
   mode, output directory). This mirrors the YAML config the CLI takes, not
   a separate schema. A "Center Z/Y/X" override (blank = box center) is
   available for `sphere`/`cylinder` — see
   [`docs/mask-design.md`](mask-design.md) for what `cylinder`'s `axis`
   (its long axis) vs. `radius` (perpendicular to that axis) actually mean.
   "Subsample to N particles" (blank = use every particle) draws a random,
   seeded (`Subsample seed`) subset of that size once and classifies only
   that subset — useful for a real-world download in the tens of thousands
   of particles (e.g. an EMPIAR dataset), where classifying every particle
   with every package isn't practical for a first pass.
2. **Preview dataset / Preview mask** — load the particle set (particle
   count, box, pixel size, a central-slice image of the global average) or
   overlay the current mask form values on that same slice as a
   semi-transparent color fill, both with no run started. Each has its own
   "Close" button to clear it back out of the sidebar. Loading the global
   average streams every particle off disk, the slow part at real-dataset
   scale (tens of minutes for tens of thousands of particles) — both run as
   a background job with a live progress bar (particles loaded so far / total),
   and share one in-memory cache keyed by the particle set's fingerprint, so
   previewing the mask right after previewing the dataset (or vice versa)
   does not re-stream the whole particle set a second time.
3. **Packages** — every registered adapter, live install status (green/red
   dot, from the same `check_installed()` the CLI's `stw check-env` runs),
   pre-checked when installed, plus a one-line algorithm summary and a
   `k range`/`fixed k` badge for capability-limited adapters (see
   [`docs/packages.md`](packages.md)).
4. **Run** — submits the config, then streams live per-package progress
   (the same step/substep events `stw run`'s Rich progress bars show) over
   Server-Sent Events. Every requested package gets a row immediately, in a
   "queued" state, each with its own **Cancel** button — clicking it kills
   that package's job (its subprocess, and its process group, so e.g. an
   MPI-launched job's worker processes die too) if it's already running, or
   skips it outright if it's still queued behind an earlier one, without
   affecting any other package in the run. HAC Baseline is the one exception:
   it runs in-process (no subprocess), so it can only be cancelled before it
   starts, not mid-computation. The Progress panel auto-collapses once the
   run finishes (a "show" toggle in its header reopens it — useful for
   checking a failure message or per-job timing after the fact) and always
   reopens itself at the start of a new run.
5. **Results** — a table of every job's status (including `cancelled`, for
   anything killed or skipped via the Cancel button)/timing/class sizes,
   with a note at the top if subsampling was used (N used / N total); a
   (package, k) with more than one seed collapses into one summary row
   ("N seeds ▸", expandable) rather than listing every seed — there's no
   principled way to pick a "best" seed without ground truth (which isn't
   wired into the orchestrator; see `RunConfig.ground_truth`, currently
   unused), so this narrows the table visually rather than choosing a
   winner for you. Below the table: an on-demand rendered class-average
   panel per job (central Z-slice per class — MRCs aren't browser-
   displayable, so this is generated server-side, fresh on every request,
   not cached — click any panel image to open it full-size in a new tab),
   the cross-package comparison figure when at least two packages succeeded
   (also click-to-full-size — the underlying figure already scales with
   package/seed count, but a browser-shrunk `<img>` doesn't), and an "All
   class averages" grid showing every successful job's panel side by side
   in one place.

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
