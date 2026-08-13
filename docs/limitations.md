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

**PyTom is the one adapter with a real, verified wedge pass-through**:
`wedge.kind: uniform` bakes a real `SingleTiltWedge` (PyTom's own model) into
its particle-list XML at prep time. Leaving wedge unset does **not** fall
back to PyTom's own script default (a generic 30-degree wedge) — `stw`
assumes full (0-degree) coverage instead, since silently guessing a tilt
geometry you never stated would be worse than assuming none. HAC Baseline,
EMAN2, and every `preview` adapter ignore wedge info entirely (`wedge: {none}`)
and warn if you supply any.

If you supply `wedge.kind: per_particle`, it is currently accepted and stored
for provenance but used by **zero** adapters at this stage — including PyTom,
whose `SingleTiltWedge` model is a single wedge angle shared by every
particle, not a true per-particle geometry.

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

## Native package installs are genuinely fragile

Both real adapters built so far needed real fixes beyond "run the documented
install command," discovered by actually installing and running each
package fresh rather than trusting a one-liner:

- **EMAN2**: the installed `e2spt_pcasplit.py` needs one patch (a
  `np.int` → `np.int64` fix) to run on any numpy released after ~2023.
  `stw`'s adapter applies this automatically, idempotently, on every run.
- **PyTom**: not on PyPI, and no `pip install` works at all — it needs the
  *legacy* `python setup.py install`, and its C extensions only compile on
  **gcc/g++ 12** (not whatever's current; verified conda-forge's `gcc-15.x`
  fails). See `docs/install/pytom.md` for the full story, or use the
  provided Docker/Podman image (`docker/Dockerfile.tier-ab`) to skip all of
  this — it bakes in both fixes and is verified working end-to-end.

Expect the remaining Tier B/C/D packages (RELION, DISCA, PEET, ProTomo,
Dynamo, STOPGAP — none have an adapter yet, see `ROADMAP.md`) to surface
their own share of this kind of real-world install friction too.

## Excluded packages

TomoFlow and OPUS-TOMO are intentionally out of scope: both are far too slow
for a tool meant to give a quick, first-look comparison. DISCA will likely
need the same treatment once it has an adapter (not yet built) given its
runtime (hours per seed on a single GPU workstation, versus seconds-to-minutes
for every package wired up so far) — it should probably never be part of any
future `--all`/default package set.
