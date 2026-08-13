# Roadmap

Full architecture rationale lives in the project's design plan (author's local notes); this
file tracks the public milestone sequence.

- [x] **M0 — scaffolding + generalized core.** Config/spec types, mask primitives (sphere +
  cylinder), generic class-averaging, cross-package comparison math, the
  requirements/capabilities framework, `stw check-env`/`list`/`init`. CI green with unit tests
  and no external cryoET software installed.
- [x] **M1 — end-to-end with HAC Baseline only.** Locks the `Adapter` contract before a second
  package is added. `stw run` on the tiny fixture produces predictions, class averages, a
  comparison report, and a run report; `--dry-run`/resume-via-cache work; a broken/incompatible
  job doesn't abort the batch.
- [x] **M2 — preview mode.** Three lightweight, dependency-free Python ports (approximating
  Dynamo/PyTom/ProTomo — `dynamo-preview`/`pytom-preview`/`protomo-preview`) wired up as
  adapters. A 4-method comparison (with HAC Baseline) runs end to end and in CI with zero
  native installs. `mode: preview` in a config auto-resolves a bare package name (`dynamo`) to
  its `-preview` variant; `mode: native` never does, so this stays forward-compatible once a
  real native adapter for the same name lands. Each preview adapter surfaces its measured
  fidelity/limitations as a `check-env` note and a run-time warning — see the module docstrings
  in `src/stw/adapters/preview/`.
- [x] **M3 — EMAN2**, the first real native pilot (conda-installable, no GPU/MATLAB/license).
  Wraps EMAN2's own `e2spt_average.py`/`e2refine_postprocess.py`/`e2spt_pcasplit.py` (never
  reimplements the algorithm); a cached multi-step prep (patch → ingest → consensus average →
  postprocess → mask convert, shared across every k/seed) precedes a per-run classify step.
  Verified end-to-end against a real installed `eman2` conda env: k=2 recovers the fixture's
  true split exactly (ARI=1.0), k=3 gives a non-degenerate split, and a cached second run is
  ~2.4x faster than the first. `seed` here is a run index (EMAN2's own CLI exposes no
  `random_state`), matching the same caveat already documented for `pytom-preview`.
- [x] **M4 — PyTom**, real (not preview): drives real `auto_focus_classify_nofrm.py` via
  `mpirun` inside a `pytom_env` conda env, an iterative reference-pair difference-map
  classifier. The first adapter with a genuinely working missing-wedge pass-through —
  `wedge.kind: uniform` bakes a real `SingleTiltWedge` into PyTom's particle-list XML,
  verified by round-tripping two different tilt-range configs to two distinct correctly-angled
  cached XMLs. Verified end-to-end against a real installed `pytom_env`: k=2 recovers the
  fixture's true split exactly (ARI=1.0). Caught and fixed a real caching bug along the way
  (in both this adapter and EMAN2's): the native-format mask conversion was cached by
  existence only, not keyed to the mask's own content hash, so changing masks across runs
  sharing an `out_dir` would have silently reused a stale converted mask. Still missing a
  Tier A/B Docker image bundling every conda-installable package — folded into M5.
- **M5 — v0.1 release prep: done; actual publishing is your call, not automated.**
  - [x] **Tier A/B Docker/Podman image** (`docker/Dockerfile.tier-ab`) bundling HAC Baseline,
    all 3 preview adapters, EMAN2, and PyTom. Built AND run end-to-end with Podman (rootless,
    no daemon) — a real 3-package classification against the tiny fixture scored ARI=1.0 for
    all three against ground truth, full cross-package agreement. Needed two real fixes beyond
    the native install docs: PyTom's C extensions need gcc/g++ pinned to 12 (not conda-forge's
    current default), and PyTom's `mpirun` call needs `--allow-run-as-root` (a container's
    default user is root; the adapter now adds this automatically, a no-op elsewhere). See
    `docker/README.md`.
  - [x] **PyPI packaging prepped, not published.** Package name
    `subtomogram-classification-wrapper` confirmed available; `python -m build` + `twine check`
    both pass; the built wheel was installed into a clean venv and ran a real classification
    successfully. Actual `twine upload` deliberately left to you — see `docs/publishing.md` for
    the exact command and a GitHub Actions trusted-publishing workflow
    (`.github/workflows/release.yml`) that's wired up but inert until you configure PyPI's
    trusted-publisher settings for this repo.
  - [x] **conda-forge recipe drafted, not submitted.** `packaging/conda-forge/meta.yaml` is
    ready to file once a real PyPI release exists (submission is a PR to
    `conda-forge/staged-recipes` plus ongoing maintainership — see
    `packaging/conda-forge/README.md`).
  - [x] **Docs site built, not deployed.** `mkdocs.yml` + `docs/` build cleanly
    (`mkdocs build --strict`, verified locally) and `.github/workflows/docs.yml` will
    auto-publish to GitHub Pages on every push to `main` once Pages is enabled for this repo
    (Settings → Pages → Source: GitHub Actions — a one-time click only you can do).
  - [x] `docs/limitations.md` finalized: added a "native installs are genuinely fragile"
    section documenting the real EMAN2/PyTom install gotchas found while building the Docker
    image, and corrected two stale claims (DISCA has no adapter yet; there's no `stw install`
    CLI command — Tier B means "a checked-in `envs/*.yml`," not a built subcommand).
- [x] **M6 — RELION**, real Class3D (regularized ML-EM, not a PCA/embedding method), always
  `--skip_align` + CPU-only (no `--gpu`/`--blush`). Reclassified from the original Tier B guess
  to **Tier C**: no trustworthy conda-forge/bioconda package exists (only a stale, unmaintained
  personal-channel one) — the real install is a CMake source build. Unlike EMAN2/PyTom, prep
  needs zero package-specific library bindings — building RELION's own CTF-cube/STAR-file
  input formats and parsing its `_data.star` output is pure numpy/text-format work done
  in-process with `stw`'s own dependencies; the only subprocess call is `relion_refine` itself.
  Second adapter (after PyTom) with a real, verified missing-wedge pass-through — a real
  single-axis 3D CTF cube built from the user's actual tilt range, not a generic default.
  `--random_seed` is a genuine reproducible seed here (unlike EMAN2/PyTom's run-index
  pseudo-seed). Verified end-to-end against a real `relion_refine` 5.0.1 build: k=2 recovers
  the fixture's true split exactly (ARI=1.0), k=3 gives a non-degenerate split, and two
  different wedge configs produce two distinct correctly-shaped cached CTF cubes/STAR files.
  Found and fixed a real bug along the way: `relion_refine`'s own `--i`/`--ref`/`--o`/
  `--solvent_mask` argument parsing breaks if the path string contains an `@` anywhere (this
  machine's username is `user@domain`, easily inherited by a temp/output directory) — the
  adapter now always passes paths relative to a fixed working directory. Also generalized the
  `EXECUTABLE` requirement checker to search common install-location fallbacks beyond bare
  `PATH`, since a from-source binary like `relion_refine` is rarely actually on it.
- [x] **M7 — PEET**, real `averageAll` → `pca` → `clusterPca` → `usePcaMotiveLists` pipeline
  (WMD-PCA + PEET's own native k-means, not reimplemented). Tier C: no conda/pip path at all —
  both IMOD (`point2model`) and PEET/"Particle" (the classification tools, MCR binaries, no
  MATLAB license needed) ship as "source this script" installs; the adapter sources both before
  every native call. Replicates a real, hard-won gotcha from the source STA benchmark project
  (confirmed there via `strace`): one MRC file per particle as separate `fnVolume` "tomograms"
  silently breaks PEET (`getInitialMOTL` only iterates the first tomogram when every tomogram
  has one particle, giving a rank-1 PCA matrix and a degenerate split) — fixed by always
  stacking every particle into one MRC "tomogram" with a single scattered-point IMOD model.
  `clusterPca` exposes no seed control, so `seed` here is a run index, like EMAN2/PyTom. Wedge
  weighting stays off (`flgWedgeWeight = 0`, matching the validated default) — PEET's `.prm`
  format does support real wedge weighting, this adapter just doesn't enable it. Verified
  end-to-end against real IMOD + PEET 1.18.2: k=2 recovers the fixture's true split exactly
  (ARI=1.0), k=3 gives a non-degenerate split, and a cached second run is roughly 2x faster
  (the slow stacked-volume/`averageAll`/`pca` stages are skipped).
- [x] **M8 — ProTomo**, real SVD/MSA (`subvolsvd.sh`) + Ward-linkage hierarchical
  clustering (`subvolhac.sh`), driven through `tomoprepare` -> `subvolinitial.sh` ->
  `subvolsvd.sh` -> `subvolhac.sh`. Tier C: ProTomo/I3 3.1.0 itself needs no license
  (a "source this script" install, like PEET), but its classification step has an
  unusual real dependency found by direct probing: `subvolsvd.sh`'s own LAPACK call
  (`SGESDD`) crashes against this kind of system's BLAS/LAPACK and only works with
  MATLAB's bundled MKL `LD_PRELOAD`ed instead -- a real MATLAB install is required on
  the machine even though MATLAB itself is never launched (no toolbox/license check,
  unlike Dynamo/STOPGAP). Found and fixed a genuine, subtle correctness bug along the
  way: `subvolhac.sh`'s `CLASSES`/`CLSFACT` come from a one-time `cycle-000/param.sh`
  snapshot `subvolinitial.sh` writes, not from re-`source`d `param-template.sh` --
  confirmed by direct probing (editing the latter and re-sourcing it silently had no
  effect on the classification result). That same finding enabled a real caching win:
  `subvolsvd.sh` (expensive, independent of `k`) is cached once per particle set +
  mask, shared across every `k`/seed; only `cycle-000/param.sh` + the cheap
  `subvolhac.sh` (no MKL preload needed) are redone per job. Deliberately skips
  ProTomo's own `subvolclassaverage.sh`/`subvolclassalign.sh` entirely -- `subvolhac.sh`
  alone already writes everything `tomoinfo -cls` needs, and `stw` builds its own
  generic class averages like every other adapter, sidestepping a documented ProTomo
  quirk (a benign but confusing native error on a near-empty HAC class) for free.
  Fully deterministic (Ward-HAC on a fixed SVD has no RNG at all) -- `seed` means
  nothing here, unlike EMAN2/PEET's run-index pseudo-seed. Verified end-to-end against
  a real ProTomo/I3 3.1.0 install: k=2 recovers the fixture's true split exactly
  (ARI=1.0), k=3 gives a non-degenerate split, two different mask configs build two
  distinct cached workspaces, and a cached rerun at a different k is ~7x faster
  (SVD is skipped; only the HAC step reruns).
- **STOPGAP — parked (2026-08-14, Josh's call), not started.** Scoped and researched (see
  commit history), but genuinely heavier than the previous four: (1) its distribution isn't a
  simple public download the way EMAN2/PyTom/RELION/PEET are — STA's own setup notes describe
  obtaining it via a "shared archive," and its custom `build_inputs.m` glue script hardcodes a
  T4P-specific filename pattern, so a generic replacement would need to be written from
  scratch, not ported; (2) while checking MATLAB's PCT license (confirmed valid) for this exact
  environment, MATLAB itself segfaulted on exit (in an unrelated telemetry module, after
  correctly printing the license check result) — a real reliability risk for verifying a
  multi-step MATLAB pipeline to the same standard as the previous four. Revisit once that's
  less of a concern, or if STOPGAP becomes more relevant to prioritize despite it.
- [x] **M9 — Dynamo**, real `dpkpca` (CC-matrix eigendecomposition on the top eigencomponents +
  k-means), driven through `dpkpca.new` -> `.unfold()` -> `prealign` -> `ccmatrix` ->
  `eigentable` -> `eigenvolumes`. Tier D: hard-requires MATLAB's Parallel Computing Toolbox
  license, no CPU-only fallback. The embedding is deterministic/seed-independent and cached once
  per particle set + mask, shared across every `k`/seed; only the final clustering (plain
  `sklearn.cluster.KMeans` in Python, not MATLAB) depends on `(k, seed)` — `seed` is a genuine
  reproducible seed here, unlike EMAN2/PEET's run-index pseudo-seed. The MATLAB crash-on-exit
  risk flagged when STOPGAP was parked turned out to be real but low-severity: `matlab -batch`
  segfaults in an unrelated telemetry module (`libmwddux.so`) on exit roughly 1 in 8 invocations,
  always *after* the real computation completes and its output is flushed — this adapter checks
  for `eigencomponents.csv` actually existing rather than trusting the subprocess's exit code,
  the same defensive pattern PEET's `usePcaMotiveLists` already needed. The same flakiness was
  found and fixed in `stw`'s own `MATLAB_TOOLBOX` requirement checker (a license check can crash
  before or after printing its answer — it hit this exact adapter's own native test suite once
  during validation), which now reads only the first stdout line and retries once. Found and
  honestly documented a real, non-bug finding: on the test fixture, k-means on the blind top-10
  eigencomponent default lands near chance even though the true class-separating signal is
  cleanly present (verified directly — a single eigencomponent column alone gets ARI=1.0) — the
  same "blind PC/factor selection isn't always the discriminating axis" property already
  established for ProTomo/STOPGAP/Dynamo in the source project. `package_options.dynamo.pc_cols`
  exposes the same tuning knob used there; verified end-to-end both ways (blind default reported
  honestly as near-chance, `pc_cols` override recovers the fixture's true split exactly), plus
  k=3 non-degeneracy, embedding-cache reuse across k (~60x faster), and two distinct masks
  building two distinct cached embeddings.
- **M10+ — remaining packages**: DISCA (kept out of any `--all` default given its runtime).
- **M11 — GUI**, deferred until after v0.1, built on the same core library (`RunConfig`'s
  JSON Schema, the requirements/capabilities report, JSONL progress events).

## Package install tiers

| Tier | Meaning | Packages |
|---|---|---|
| A | Vendored, always available | HAC Baseline, preview-mode ports |
| B | A conda env from a checked-in `envs/<pkg>.yml` sets it up (`conda env create -f envs/<pkg>.yml -n <pkg>`, per that package's own `docs/install/<pkg>.md` — no dedicated `stw install` CLI command exists yet) | EMAN2, PyTom, DISCA (unconfirmed) |
| C | Detected, not auto-installed (no license needed, but no reliable conda/pip path — a source build) | PEET, **ProTomo** (no license itself, but its classification step needs a MATLAB install on the machine for its bundled MKL library — see `docs/install/protomo.md`), **RELION** (no trustworthy conda-forge/bioconda package exists; official install is a CMake source build) |
| D | MATLAB-licensed and/or per-machine compile step | **Dynamo** (Parallel Computing Toolbox required, no CPU-only fallback), STOPGAP |

TomoFlow and OPUS-TOMO are intentionally out of scope — both are too slow for a "quick"
comparison tool.
