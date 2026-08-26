# Limitations — read this before trusting a comparison across packages

## The test fixture is deliberately easy — ARI=1.0 means "the wiring works," not "this is solved"

Every adapter's verification claims in this repo's commit history (and the
scores you'll see if you run the tests yourself) use
`tests/fixtures/tiny/` — 32 synthetic particles built by
`tests/fixtures/make_fixture.py`, **not real cryoET data**. Two classes, each
a shared "body" blob plus a large, spatially well-separated class-specific
blob, plus modest Gaussian noise (~5:1 signal-to-noise-std ratio). That's
about as easy a classification problem as one can construct — real cryoET
data is far noisier, with missing-wedge artifacts and much subtler
conformational differences layered on top.

A perfect score on this fixture is a proxy for **"the plumbing is correct"**
(the mask applied properly, the particle-to-index mapping into each
package's native format didn't get scrambled, the native output got parsed
back correctly) — not a claim that any of these methods achieve perfect
accuracy on real biological data. A *wrong* answer here is a strong bug
signal (and has caught real ones); a perfect one isn't a benchmark result.

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
- **RELION**: no trustworthy conda-forge/bioconda package exists — the real
  install is a CMake source build (see `docs/install/relion.md`). Separately,
  a real bug was found and fixed in `stw`'s own adapter, not RELION itself:
  `relion_refine`'s own `--i`/`--ref`/`--o`/`--solvent_mask` argument parsing
  misidentifies a valid path as invalid if the path string contains an `@`
  anywhere (found on a machine whose username is `user@domain`, easily
  inherited by a temp/output directory). The adapter now always passes paths
  relative to a fixed working directory rather than raw absolute strings.
- **PEET**: no conda/pip path — both IMOD and PEET/"Particle" ship as
  "source this script" installs (see `docs/install/peet.md`). Separately, a
  real correctness gotcha (confirmed via `strace` in the source STA
  benchmark project): supplying one MRC file per particle as separate
  `fnVolume` "tomograms" silently breaks PEET — it only ever iterates the
  *first* tomogram once every tomogram has exactly one particle, giving a
  rank-1 PCA matrix and a degenerate near-all-one-class split with no error.
  `stw` always stacks every particle into one MRC "tomogram" with a single
  scattered-point IMOD model instead.
- **ProTomo**: no conda/pip path — a "source this script" install like PEET's, with
  a genuinely unusual extra dependency found by direct probing: its classification
  step's LAPACK call (`subvolsvd.sh`'s `SGESDD`) crashes against this kind of
  system's own BLAS/LAPACK and only works with **MATLAB's bundled MKL library**
  `LD_PRELOAD`ed instead — a real MATLAB install is required on the machine even
  though MATLAB itself is never launched (no license or toolbox needed, unlike
  Dynamo/STOPGAP). Separately, a subtle correctness gotcha in ProTomo itself: its
  `subvolhac.sh` reads `CLASSES`/`CLSFACT` from a one-time `cycle-000/param.sh`
  snapshot written at workspace-creation time, not from `param-template.sh` even
  when explicitly re-`source`d immediately before the call — `stw` always rewrites
  `cycle-000/param.sh` directly before every classify call. See
  `docs/install/protomo.md`.
- **Dynamo**: Tier D — hard-requires MATLAB's Parallel Computing Toolbox license, no
  CPU-only fallback. Two real findings from validating this adapter: (1) `matlab -batch`
  occasionally (~1 in 8 invocations observed) segfaults in an unrelated telemetry module
  (`libmwddux.so`) on process exit *after* the real computation completes and its output
  is flushed — this adapter checks for `eigencomponents.csv` actually existing rather than
  trusting the subprocess's exit code, and the same flakiness was found and fixed in `stw`'s
  own `MATLAB_TOOLBOX` requirement checker (a license check can crash before or after
  printing its answer). (2) On `stw`'s own easy test fixture, k-means on the blind
  top-10-eigencomponent default lands near chance even though the true class-separating
  signal is cleanly present in the embedding (verified directly) — not a plumbing bug, the
  same "blind PC/factor selection isn't always the discriminating axis" property already
  established for ProTomo/STOPGAP/Dynamo in the source project; see
  `package_options.dynamo.pc_cols` and `docs/install/dynamo.md`.
- **DISCA**: no license or compile step (pip-installable PyTorch), but a real correctness
  gotcha found while building this adapter: the vendored `torch_disca_run.py`'s original
  channel-axis handling only avoids crashing by coincidence at box=32 (see
  `docs/install/disca.md`) — `stw` always applies the fix (`DISCA_FIX_CHANNELS=1`), not as
  an opt-in. Also genuinely unseeded (unlike every other adapter here, "seed" doesn't control
  anything at all) and, unlike every other package wired up so far, genuinely slow at real
  dataset scale (hours per seed) — see the Excluded packages section below.

- **STOPGAP**: no public download at all — obtained via a private archive from its
  developers (see `docs/install/stopgap.md`). Tier D, but — unlike Dynamo — no Parallel
  Computing Toolbox license needed; its parallelism is OS-level MPI, confirmed by reading
  every `.m` script the PCA path touches. Real, machine-specific gotcha found while
  building this adapter: the vendored install's `exec/lib/stopgap_config*.sh` hardcode a
  MATLAB-runtime `LD_LIBRARY_PATH` for whoever originally configured that copy — `stw`
  always exports its own correct value first (from `package_options.stopgap.matlab_root`),
  relying on the vendored scripts' own `export ...:$LD_LIBRARY_PATH` form to append rather
  than replace it. Separately, `stw`'s own `MPI` requirement checker only checked `PATH`,
  which missed this reference machine's OpenMPI entirely (RHEL's `openmpi` RPM installs
  `mpiexec` without ever adding it to `PATH`) — `resolve_mpi_bin()` now also checks a
  handful of common distro install paths. On `stw`'s own easy test fixture, no eigen-
  projection column or small subset examined recovers a clean class separation the way
  Dynamo's embedding did (best found, ARI~0.29) — checked directly (not assumed) after
  independently confirming the embedding pipeline itself is structurally correct; see
  `docs/install/stopgap.md`.

## Excluded packages

TomoFlow and OPUS-TOMO are intentionally out of scope: both are far too slow
for a tool meant to give a quick, first-look comparison. DISCA now has a real
adapter (unlike TomoFlow/OPUS-TOMO, it's a genuine part of `stw`'s package
set) but the same runtime concern applies directly: hours per seed at real
dataset scale, versus seconds-to-minutes for every other package wired up so
far. It should never be part of any `--all`/default package set — always opt
into it explicitly.
