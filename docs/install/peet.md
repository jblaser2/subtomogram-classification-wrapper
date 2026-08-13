# Installing PEET

**Tier C — detected, not auto-installed.** No license needed (the
classification tools — `averageAll`/`pca`/`clusterPca`/`usePcaMotiveLists` —
are MCR binaries, no MATLAB license required), but there's no conda/pip
path at all: PEET and IMOD are each their own installer that sets up a
"source this script" environment.

1. Install [IMOD](https://bio3d.colorado.edu/imod/) (provides `point2model`).
2. Install [PEET](https://bio3d.colorado.edu/PEET/) ("Particle" — provides
   `averageAll`/`pca`/`clusterPca`/`usePcaMotiveLists`).
3. Confirm each ships a setup script you can `source` to put its binaries on
   `PATH` — typically named `IMOD-linux.sh` and `Particle.sh`.

`stw` looks for these two scripts at `~/Applications/IMOD-linux.sh` and
`~/Applications/Particle.sh` by default. Point it at different locations
with `package_options.peet.imod_setup` / `package_options.peet.particle_setup`.

Verify with:

```console
source ~/Applications/IMOD-linux.sh && which point2model
source ~/Applications/Particle.sh && which averageAll pca clusterPca usePcaMotiveLists
stw check-env --package peet
```

## What `stw` actually does with it

`stw`'s PEET adapter drives the real pipeline documented by PEET itself —
`averageAll` (grand average) → `pca` (WMD-PCA) → `clusterPca` (PEET's own
native k-means) → `usePcaMotiveLists` (writes class labels back into the
motive list) — never reimplements any of it. Every native call sources both
setup scripts first, since that's the only way this software is meant to be
invoked (no static binary paths to rely on).

**A real, hard-won gotcha replicated here**: supplying one MRC file per
particle as separate `fnVolume` "tomograms" silently breaks PEET —
`getInitialMOTL` only iterates the *first* tomogram when every tomogram has
exactly one particle, producing a rank-1 PCA matrix and a degenerate
near-all-one-class split (confirmed via `strace` in the source STA benchmark
project this tool grew out of). The fix, always applied: every particle is
stacked into **one** MRC "tomogram" (particle `i` at Z-offset `i * box`)
with a single scattered-point IMOD model, so PEET treats it as one tomogram
with N particles.

`clusterPca` exposes no seed control, so `seed` here is a run index, like
EMAN2/PyTom — not a genuine reproducible seed like RELION's. Missing-wedge
weighting is always off (`flgWedgeWeight = 0`), matching this project's
validated default for pre-aligned, uniform-wedge-corrected input; PEET's own
`.prm` format does support real wedge weighting, this adapter just doesn't
enable it (unlike the PyTom/RELION adapters' real wedge pass-through).
