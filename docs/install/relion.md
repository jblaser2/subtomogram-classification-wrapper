# Installing RELION

**Tier C — detected, not auto-installed.** No license needed, but there is
no trustworthy conda-forge/bioconda package (only a stale, unmaintained
personal-channel one at the time of writing) — the real install is a CMake
source build, same as RELION's own official documentation recommends.

```console
git clone https://github.com/3dem/relion.git
cd relion
mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=$HOME/relion-install
make -j$(nproc)
make install
```

Validated against `relion` at commit `cad71bf` (`5.0.1-10-gcad71bf6`), CPU-only
build (no `-DCUDA=ON`) — `stw`'s RELION adapter never uses GPU acceleration
(`--gpu`/`--blush` aren't implemented). See the
[official RELION install guide](https://relion.readthedocs.io/en/release-5.0/Installation.html)
for GPU builds, dependencies (FFTW, an MPI implementation for the multi-node
binaries — not needed for `relion_refine` alone), and platform-specific notes.

## `stw` doesn't look at a conda env for this one

Unlike EMAN2/PyTom, `stw`'s RELION adapter needs **no package-specific
Python bindings at all** — building RELION's own input formats (a 3D
CTF/wedge cube, a two-block STAR file) and parsing its `_data.star` output
are pure numpy/text-format work, done in-process with `stw`'s own
dependencies. The only real requirement is the `relion_refine` binary
itself.

`stw` looks for `relion_refine` on `PATH` first, then a few common
from-source install locations (`~/relion-install/bin`, `/usr/local/relion/bin`,
`/opt/relion/bin`). If yours lives somewhere else, set
`package_options.relion.relion_bin` to the exact binary path in your config.

Verify with:

```console
relion_refine --version
stw check-env --package relion
```

## What `stw` actually does with it

`stw`'s RELION adapter drives real `relion_refine` in Class3D mode
(regularized ML-EM in Fourier space — not a PCA/embedding method), always
with `--skip_align` (identity poses; `stw` assumes pre-aligned input
project-wide, see [`../limitations.md`](../limitations.md)) and CPU-only
(no `--gpu`/`--blush`).

Like PyTom, RELION has a **real, working missing-wedge pass-through**:
`wedge.kind: uniform` with `tilt_min`/`tilt_max` bakes a real single-axis
missing-wedge 3D CTF cube (RELION's own `rlnCtfImage` format) built from
your actual tilt range. Leaving wedge unset uses an all-ones (no wedge
weighting) CTF cube — not a silently assumed tilt geometry.

`--random_seed` is a **true, reproducible seed** here — unlike EMAN2, PyTom,
and most preview adapters, whose "seed" is just a run index.

RELION's regularized ML-EM is documented (in the source STA benchmark
project this tool grew out of) to collapse to one dominant class on some
low-SNR real cryoET data. That's a real algorithm-level finding about
RELION's fit for very low-SNR subtomogram classification, not a bug in this
adapter — if you see it, it's real signal about the method, not the wrapper.
