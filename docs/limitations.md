# Limitations — read this before trusting a comparison across packages

## Alignment

`stw` requires **pre-aligned (`alignment_state: fine`) input** for every package
currently wired up. Every native launcher these adapters wrap assumes this:
they apply existing particle poses rather than searching for new ones. Real
particle alignment (translational + angular refinement) is a substantially
different, much slower problem, and each package's own aligner works
differently — supporting it properly is a separate, later effort (a planned
`stw align` subcommand), not something bolted onto the classification wrapper.

- `alignment_state: rough` is accepted with a warning. It changes real
  behavior today (an `auto` mask centers on the density's center of mass
  instead of assuming the box center, to avoid clipping poorly-centered
  signal), but no package here actually re-aligns rough input.
- `alignment_state: unaligned` is a hard, immediate preflight error, not a
  silently wrong result.

## Missing wedge / tilt information

`stw` does **not** build a universal missing-wedge model. Wedge/tilt
information you supply is only used by adapters that declare real support for
it; everything else ignores it and records a warning (visible in the run
report and the comparison figure's caption). Building a correct wedge model
for every package — several of which are closed-source binaries — would mean
changing the *input data* rather than the method, which would silently
invalidate any comparison between packages that did and didn't get it.

If you supply `wedge.kind: per_particle`, it is currently accepted and stored
for provenance but used by **zero** adapters at this stage.

## `mode: preview`

`dynamo-preview`, `pytom-preview`, and `protomo-preview` are lightweight,
dependency-free Python approximations of each package's real classifier, not
the real packages. Their measured fidelity varies a lot:

- **`pytom-preview`** is the most faithful (closely matches real PyTom on
  FM_easy-like data) but only validated at k=2, and is explicitly *bimodal* on
  T4P-like data — roughly 2 in 5 seeds collapse to a near-chance split.
- **`dynamo-preview`** is mid-pack fidelity.
- **`protomo-preview`** is the weakest — a rough, directionally-informative
  substitute, not a stand-in for real ProTomo's numbers (ProTomo ships no
  source, so this port was built by inference only).

Every preview adapter surfaces its own caveat via `stw check-env` (as a note)
and on every run (as a warning in the run report), so it's never silently
presented as equivalent to the real package.

## Ground truth and scoring

Real data usually has no ground truth. `stw`'s scoring module
(`stw.scoring.gt`) exists for the tool's own tests against synthetic fixtures
and for power users validating against a known answer — it is not part of the
normal `stw run` output.

## Excluded packages

TomoFlow and OPUS-TOMO are intentionally out of scope: both are far too slow
for a tool meant to give a quick, first-look comparison. DISCA is included
but is not part of any future `--all`/default package set given its runtime
(hours per seed on a single GPU workstation, versus seconds-to-minutes for
every other package here).
