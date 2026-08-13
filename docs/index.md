# subtomogram-classification-wrapper

Run subtomogram classification across many cryoET packages with **one
config**, and get class averages plus a cross-package comparison matrix back
— without installing and learning each package's own CLI, file formats, and
quirks one at a time.

!!! note "Status: early development (pre-v0.1)"
    The core library, HAC Baseline, three dependency-free `mode: preview`
    adapters, and two real native packages (EMAN2, PyTom — both verified
    end-to-end against real installs, including inside a container image)
    all work today. See the [roadmap](https://github.com/jblaser2/subtomogram-classification-wrapper/blob/main/ROADMAP.md)
    for what's next.

## Why

Testing a classification hypothesis across the field's major 3D-classification
packages (RELION, STOPGAP, Dynamo, PEET, PyTom, EMAN2, ProTomo, DISCA, ...)
means learning MATLAB scripts, MCR binaries, compiled C tools, and half a
dozen incompatible file formats — one package at a time. `stw` wraps that
behind one config:

```yaml
particles: ./subtomos
pattern: "subtomo_*.mrc"
k: 2
mask: { kind: cylinder, radius: 27, half_height: 12, axis: y, edge: 4 }
alignment_state: fine
packages: [hac, eman2, pytom]
out_dir: ./stw_out
```

```console
stw check-env      # see what's installed, and what each package needs if it isn't
stw run config.yaml # runs every requested package, writes class averages + a comparison
```

Start with the [quickstart](quickstart.md), or jump straight to a package's
[install guide](install/eman2.md). Read [limitations](limitations.md) before
trusting a cross-package comparison — it documents exactly what each mode
does and doesn't handle (alignment, missing wedge, fidelity of the preview
approximations).

## Design principles

- **Native packages by default.** `stw` shells out to each package's real
  implementation. `mode: preview` runs fast, dependency-light Python
  approximations instead — useful for trying the tool with zero installs,
  but opt-in, not the default.
- **See requirements before you opt in.** `stw check-env` reports pass/fail
  for every package's actual requirements *before* anything runs.
- **A failure in one package never kills the batch.**
- **No universal claims where none exist.** Alignment and missing-wedge
  handling vary a lot by package — `stw` says plainly what each package
  actually did with your data.

## Installation

```console
pip install subtomogram-classification-wrapper
```

(Not yet published — see [publishing](publishing.md) for the current state.
For now, install from a clone: `pip install -e ".[dev]"`.)
