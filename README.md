# subtomogram-classification-wrapper (`stw`)

Run subtomogram classification across many cryoET packages with **one config**, and get
class averages + a cross-package comparison matrix back — without installing and learning
each package's own CLI, file formats, and quirks one at a time.

> **Status: early development (pre-v0.1).** The core library, HAC Baseline, three
> dependency-free `mode: preview` adapters (`dynamo-preview`/`pytom-preview`/`protomo-preview`),
> and eight real native packages (**EMAN2**, **PyTom**, **RELION**, **PEET**, **ProTomo**,
> **Dynamo**, **DISCA**, **STOPGAP** — all verified end-to-end against real installs) all work — try
> `stw list`. PyTom and RELION both have a genuinely working missing-wedge pass-through. DISCA
> is real but genuinely slow (hours/seed at real dataset scale) — never include it in a
> default/`--all` package set. A local web GUI (`stw gui`, needs the `gui` extra) is also
> up — see [`docs/gui.md`](docs/gui.md). See [`ROADMAP.md`](ROADMAP.md) for the full plan
> and [`docs/limitations.md`](docs/limitations.md) for what this tool does and doesn't do yet.

## Why

Testing a classification hypothesis across the field's major 3D-classification packages
(RELION, STOPGAP, Dynamo, PEET, PyTom, EMAN2, ProTomo, DISCA, ...) means learning MATLAB
scripts, MCR binaries, compiled C tools, and half a dozen incompatible file formats — one
package at a time. `stw` wraps that behind one config:

```yaml
particles: ./subtomos
pattern: "subtomo_*.mrc"
k: 2
mask: { kind: cylinder, radius: 27, half_height: 12, axis: y, edge: 4 }
alignment_state: fine
packages: [hac]
out_dir: ./stw_out
```

```console
$ stw check-env            # see what's installed, and what each package needs if it isn't
$ stw run config.yaml       # runs every requested package, writes class averages + a comparison
```

## Design principles

- **Native packages by default.** `stw` shells out to each package's real implementation.
  `mode: preview` runs fast, dependency-light Python approximations instead (currently
  Dynamo/PyTom/ProTomo) — useful for trying the tool with zero installs, but opt-in, not the
  default, and each one reports its own measured fidelity via `stw check-env` — see
  [`docs/limitations.md`](docs/limitations.md).
- **See requirements before you opt in.** Every package declares what it needs (a conda
  env, MATLAB + a specific toolbox, a GPU, disk space, ...); `stw check-env` reports pass/fail
  for each *before* anything runs, so you can opt out of packages you can't support.
- **A failure in one package never kills the batch.** Missing requirements or a mid-run
  crash are recorded per package and reported at the end, not fatal.
- **No universal claims where none exist.** Alignment and missing-wedge handling vary a lot
  by package; `stw` is explicit in its output about what each package actually did with your
  data rather than pretending every method is equivalent. See
  [`docs/limitations.md`](docs/limitations.md).

## Installation

```console
pip install -e ".[dev]"      # from a clone, while in early development
```

(Not yet on PyPI — see [`docs/publishing.md`](docs/publishing.md).)

Packages themselves are a separate story — see `stw check-env` and `docs/install/`.
Some packages (EMAN2, PyTom, DISCA) are conda-installable via `conda env create -f envs/<pkg>.yml`
(see each package's own `docs/install/<pkg>.md` for the exact command and any gotchas);
a prebuilt image with both already set up is available too, see [`docker/README.md`](docker/README.md).
Others (RELION, PEET, Dynamo, STOPGAP, ProTomo) have no conda/pip path at all — a from-source
build, IMOD, a MATLAB license, or a closed compiled binary — that `stw` can only detect and
guide you through, not install for you.

Prefer a GUI over YAML? `pip install ".[gui]"` then `stw gui` — a local web app (like
launching `napari` from the terminal) covering the same config, package picker, and live
progress the CLI has. See [`docs/gui.md`](docs/gui.md).

## Documentation

Full docs (quickstart, config reference, per-package install guides, limitations) build
with `mkdocs` from this repo's own `docs/` directory — see [`mkdocs.yml`](mkdocs.yml).
Once GitHub Pages is enabled for this repo (Settings → Pages → Source: GitHub Actions),
`.github/workflows/docs.yml` publishes it automatically on every push to `main`.

## Contributing an adapter for a new package

Adapters are discovered via the `stw.adapters` entry-point group, so a new package's
support doesn't require a PR to this repo — see `src/stw/adapters/base.py` for the
`Adapter` contract.

## License

MIT — see [`LICENSE`](LICENSE).
