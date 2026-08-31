# `stw align` — fine alignment for roughly-aligned data

Every classification package `stw` drives assumes pre-aligned
(`alignment_state: fine`) input — see [`docs/limitations.md`](limitations.md).
`stw align` closes part of that gap: a real global-alignment step for
particles that are *roughly* aligned already (correct-ish orientation, some
residual pose jitter) but not clean enough to classify well.

```console
stw align align_config.yaml
```

```yaml
# align_config.yaml
particles: /path/to/rough_particles
pattern: "*.mrc"
pixel_size: 13.328          # optional -- read from MRC headers if omitted
mask:
  kind: sphere               # a DIFFERENT, broader mask than you'll classify with -- see below
  radius: 20.0
out_dir: ./stw_align_out
options:
  max_iter: 6                 # optional overrides, see "Tuning" below
```

Output: `<out_dir>/aligned_particles/` (one MRC per input particle, same
filenames, fully aligned) and `<out_dir>/poses.csv` (per-particle recovered
shift/rotation/score, for provenance). Point a normal `stw run` config's
`particles:` straight at `aligned_particles/` — no format bridging needed.

Or from `stw gui`: a collapsible "Align first" section sits above the main
particle-directory field. Running it there shows a live preview of the
aligned average and a "Use this aligned output →" button that fills in the
main form for you.

## The one hard rule: use a different mask than you'll classify with

**Do not reuse your classification mask for alignment.** This is not a
style preference — reusing one was tried in the benchmark project this tool
grew out of and it silently destroyed the classification signal: alignment's
translation search registers every particle onto whatever's inside its
mask, so if that region is also the thing you're trying to classify by, the
result is that alignment erases the very difference between classes rather
than just removing pose jitter (measured effect: blind ARI dropped from
0.637 with a dedicated, broader alignment mask to near-chance when the
classification mask was reused). Use a wide, generic "is there real density
here at all" envelope for alignment — `mask.kind: auto` (the default) is a
reasonable starting point; a broad `sphere` covering the whole particle
works too.

## Why PyTom's FRM, not something else

Two other approaches were investigated in depth before choosing this one:

- **A hand-rolled NumPy aligner** (from the same source benchmark project,
  used to align two of its synthetic test datasets) is real and genuinely
  blind (no ground truth), but its rotation search is a *local* perturbation
  around each particle's *current* pose (61 random candidates within ±15°),
  with zero ability to do a global search or recover from a badly-wrong
  starting orientation — it was never validated on genuinely unaligned data.
- **Dynamo's `dalign`** is a real global search too, and its own plumbing is
  free to reuse (same MATLAB setup `stw`'s Dynamo classification adapter
  already needs) — but every real attempt at it in the source project
  crashed on an unresolved bug inside Dynamo's own compiled table-
  serialization binary, triggered unpredictably by particle count/shape, and
  its one working result never transferred its poses to any other package.

**PyTom's FRM (Fast Rotational Matching)** is a genuine global SO(3)
rotational search (spherical-harmonic correlation, multiple seeded
candidates) plus a joint translational refinement, run to convergence via
PyTom's own real gold-standard (even/odd, FSC-driven adaptive lowpass)
protocol — the same category of rigor as a real cryoEM refinement, not a
toy. It reuses most of `stw`'s existing PyTom classification plumbing
(ParticleList XML, `mpirun` dispatch, the same `SingleTiltWedge` wedge
model), and PyTom's own machinery applies the recovered poses — no
hand-rolled rotation-convention guessing.

## Requirements

Needs a real PyTom install (see [`docs/install/pytom.md`](install/pytom.md))
**plus a compiled FRM extension most PyTom builds don't ship with** — this
is a separate, optional requirement from classification, which never needs
it (`stw`'s PyTom classification adapter always runs with alignment search
disabled). Compile it with:

```console
scripts/compile_pytom_frm.sh          # defaults to the pytom_env conda env
```

This clones PyTom fresh, builds its bundled (1997-era) spherical-harmonics
source with a handful of relaxed C flags a modern compiler needs, and
installs the result into your existing `pytom_env`. Safe to re-run.
`stw check-env` doesn't cover this (it's not an Adapter) — check directly:

```console
stw align align_config.yaml   # refuses to start and explains what's missing
```

## Tuning

FRM's bandwidth/frequency parameters are sensitive to box size — defaults
here scale automatically (`peak_offset`, `bw_low`, `bw_high`, `freq` all
derived from your particles' box size), but can be overridden under
`options` if a real dataset needs different values:

| Option | Default | Meaning |
|---|---|---|
| `peak_offset` | `max(4, box // 4)` | translational search radius, voxels |
| `bw_low` / `bw_high` | `4` / scales with box | spherical-harmonic bandwidth range |
| `freq` | scales with box | initial frequency cutoff |
| `max_iter` | `4` | maximum refinement iterations (FSC-gated early stop) |

## What it does and doesn't do

- **Bootstraps its own reference** — a plain unweighted average of your
  input particles, no external map or ground truth needed.
- **Caches the expensive step**: re-running the exact same config skips the
  real MPI alignment search entirely (only the (cheap) initial bootstrap/prep
  steps and pose-application step ever need to redo anything if their own
  inputs changed).
- **Requires roughly-aligned input.** This is a real architectural limit,
  not a tuning knob: FRM here is validated as a refinement of an
  already-close starting pose, not a from-scratch search over arbitrary
  orientations. Feed it particles with wildly random poses and there is no
  guarantee it converges to anything meaningful.
- **Always check the result visually.** The one real-data test run in the
  source project (on already-well-aligned data, as a sanity check) showed no
  improvement — "reshuffling, not improvement" by direct class-average
  inspection. `stw align` has not been validated on real, genuinely rough
  data; treat a first real run as a hypothesis to check against the aligned
  class averages, not a guaranteed win.
