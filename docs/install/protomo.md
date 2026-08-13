
# Installing ProTomo

**Tier C — detected, not auto-installed.** No license needed for ProTomo/I3
itself (it's a freely-distributed compiled binary with its own "source this
script" install, like PEET), but its classification step has a real, unusual
runtime dependency: **a MATLAB install on the machine**, not for a license or
to run any MATLAB script, but to `LD_PRELOAD` MATLAB's own bundled MKL
library. Verified directly while building this adapter: `subvolsvd.sh`'s
LAPACK call (`SGESDD`) fails outright against this kind of system's own
BLAS/LAPACK (OpenBLAS via conda) and only succeeds with MATLAB's `mkl.so` +
`libiomp5.so` preloaded instead.

1. Install [ProTomo/I3 3.1.0](https://github.com/anthonis/protomo) (or your
   site's distribution of it) somewhere, e.g. `~/Applications/protomo-3.1.0`.
   It ships its own `setup.sh` that sets `PATH`/`LD_LIBRARY_PATH` — `stw`
   looks for it at `~/Applications/protomo-3.1.0/setup.sh` by default;
   override with `package_options.protomo.protomo_setup`.
2. Have a MATLAB install on the same machine (any recent version — this
   adapter only ever borrows its bundled MKL, never launches `matlab`
   itself, so no toolbox or license is needed). `stw` looks for
   `bin/glnxa64/mkl.so` + `sys/os/glnxa64/libiomp5.so` under
   `/usr/local/MATLAB/R2024a`, then `~/Applications/matlab`, in that order;
   override the root with `package_options.protomo.matlab_root`.

Verify with:

```console
source ~/Applications/protomo-3.1.0/setup.sh && which tomoprepare i3preproc subvolsvd.sh subvolhac.sh
stw check-env --package protomo
```

## What `stw` actually does with it

`stw`'s ProTomo adapter drives the real `tomoprepare` → `subvolinitial.sh` →
`subvolsvd.sh` → `subvolhac.sh` pipeline (SVD-based multivariate statistical
analysis + Ward-linkage hierarchical clustering) — never reimplements any of
it. It deliberately never calls ProTomo's own `subvolclassaverage.sh`/
`subvolclassalign.sh`: `subvolhac.sh` alone already writes the one file
(`<prefix>-class.i3i`) `tomoinfo -cls` needs to recover per-particle labels,
and `stw` builds its own generic class averages (like every other adapter)
rather than relying on any package's native ones — this also sidesteps a
documented ProTomo quirk (a benign but confusing native error on a
near-empty HAC class).

**Two real gotchas found and fixed while building this adapter** (both
confirmed by direct probing, not assumed from documentation):

- **`subvolhac.sh`'s `CLASSES`/`CLSMIN`/`CLSMAX`/`CLSFACT` come from
  `cycle-000/param.sh`, a one-time snapshot `subvolinitial.sh` writes — not
  from `process/param-template.sh`, even re-`source`d immediately before the
  call.** This adapter always rewrites `cycle-000/param.sh` directly before
  every classify call. It also means the expensive step
  (`subvolsvd.sh`, computing per-particle SVD/MSA coordinates) doesn't
  depend on `CLASSES` at all — it's cached once per particle set + mask,
  shared across every `k`/seed; only the cheap `subvolhac.sh` (no MKL preload
  needed) is redone per `(k, seed)` job, safe because `stw`'s orchestrator
  runs jobs strictly sequentially within one `stw run`.
- ProTomo's own zero-translation-search option (`MRAPKR="0 0 0"`) actually
  means *unbounded* search, not "none," and can corrupt edge-padded
  particles. Since `stw` requires pre-aligned (`fine`) input anyway,
  ProTomo's own aligner (`subvolreference.sh`/`subvolalign.sh`) is never
  invoked at all — the raw series is copied straight to `-mra.i3i`.

Every particle is bandpass-filtered before SVD (`MSALOWPASS`/`MSAHIGHPASS`,
default ~0.06–0.40 cycles/px of Nyquist) — baked into every run, not an
optional toggle. Missing-wedge weighting is always off (`WDGCOMP="false"`).
Fully deterministic (Ward-HAC on a fixed SVD has no RNG at all) — unlike
EMAN2/PEET's "seed is a run index," `seed` means nothing here at all.
