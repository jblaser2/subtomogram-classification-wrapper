# Designing a mask

Every package `stw` wires up (except HAC Baseline, which can run maskless)
needs a mask before classification — a soft-edged region of the box the
comparison actually looks at. Pick one of four kinds via `mask.kind` in your
config, or preview any of them standalone with `stw mask` before committing
to a full run.

## The four kinds

- **`auto`** (the default) — a blind, label-free soft sphere sized to enclose
  most of the particle's own density envelope. Computed from the global
  average of your particles, no ground truth or class labels needed. This is
  the right starting point if you don't already know a good mask for your
  structure.
- **`sphere`** — a soft-edged sphere at `mask.radius` voxels, centered on the
  box center by default (or `mask.center`, `[z, y, x]` voxels).
- **`cylinder`** — a disc of `mask.radius` extruded ±`mask.half_height` along
  `mask.axis` (`x`/`y`/`z`) — useful for elongated or membrane-embedded
  complexes where a sphere would either clip real signal or include too much
  background.
- **`file`** — your own mask MRC, `mask.path`, same box size as your
  particles. Use this once you've hand-tuned a mask (in `stw mask`, IMOD, or
  elsewhere) and want every package to share the identical file.

All four (except `file`, which is used as-is) share the same soft cosine
falloff (`mask.edge` voxels, default 3) — a hard-edged mask introduces
Fourier-domain ringing that several packages' own bandpass/SVD steps are
sensitive to.

## Preview one before running anything

```console
stw mask --particles ./subtomos --kind sphere --radius 24 --out preview.mrc
```

This builds the mask (identical logic `stw run` itself uses) and writes a QC
overlay PNG next to it — three orthogonal slices of your particles' global
average with the mask contour drawn in red, so you can see exactly what
you're keeping before spending time on a full run:

```console
wrote preview.mrc
QC overlay: .stw_mask_cache/mask_<hash>.overlay.png
```

Try a few radii/kinds this way and look at the overlay each time; there's no
need to run any package to iterate on mask geometry.

## How caching works

Inside a real `stw run`, the resolved mask MRC is cached by a content hash of
every field that defines it (`mask.kind`, `radius`, `half_height`, `axis`,
`center`, `edge`, or the `file` path) — every package in the same run shares
the identical mask file, and changing any mask field is guaranteed to produce
a fresh file rather than silently reusing a stale one (a real caching bug
class found and fixed multiple times across individual adapters early on;
see `docs/limitations.md`'s "Native package installs are genuinely fragile"
section). A QC overlay is written alongside the cached mask automatically
too, in `<out_dir>/_cache/mask_<hash>.overlay.png`.

## Mask-related pitfalls worth knowing about

- **Too tight and you concentrate signal on a coincidental axis, too broad
  and several packages collapse to a contrast/intensity split instead of a
  structural one.** This isn't unique to `stw` — it's a real, extensively
  documented property of PCA/embedding-family methods (ProTomo, Dynamo,
  DISCA) in the source benchmark project this tool grew out of. There's no
  universal "right" mask size; `auto` is a reasonable blind starting point,
  not a guarantee.
- `center_mode="box"` (the default center for `sphere`/`cylinder`, and what
  `auto` uses unless told otherwise) assumes your particles are genuinely
  centered — appropriate for `alignment_state: fine` input. `rough`-aligned
  input is more likely to be off-center; `auto`'s mask still centers on the
  box unless you pass rough/poorly-centered data, in which case a
  center-of-mass–based mask would clip less real signal (not yet exposed as
  a config option — see `src/stw/masks/auto.py`'s `center_mode="com"` if you
  need it today).
- A cylindrical mask doesn't map cleanly onto every package's own native
  mask primitives — ProTomo, for instance, has no native cylinder type at
  all (its own primitives are elliptic/Gaussian/rectangular/molecular), so
  `stw` always converts the resolved mask MRC into whatever format that
  package needs rather than asking it to express the shape itself.
