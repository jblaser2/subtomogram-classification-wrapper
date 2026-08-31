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
- [x] **M10 — DISCA**, real YOPO CNN feature extractor + Gaussian-mixture EM (`torch_disca_run.py`,
  vendored from the `aitom` toolkit), iterated inside a `disca` conda env. Tier B: pip-installable
  PyTorch, no license/compile trickery — confirmed and reclassified from the original "(unconfirmed)"
  tier-table annotation. Input packaging (mask + Fourier-crop to DISCA's own 32³ regime +
  per-particle standardization) is pure numpy/mrcfile logic done in-process, no conda env needed
  for that part. Always passes `DISCA_FIX_CHANNELS=1` (not an opt-in toggle): the vendored script's
  original behavior silently treats the spatial box-size axis as the channel count unless this is
  set, which only avoided crashing by coincidence at box=32 — required for correctness at any
  other box size, the same "apply the real fix, don't leave a known bug as default" call already
  made for EMAN2's `np.int` patch. Genuinely unseeded (torch/numpy/CUDA RNGs are never seeded) —
  `seed` is a run index in name only, unlike EMAN2/PEET's deterministic-algorithm bookkeeping
  index; only the mask-dependent input packaging is cached, every classification run is a fresh
  independent training run. Verified end-to-end against a real `disca` conda env (torch 2.11+cu128)
  on a single consumer GPU: k=2/k=3 both complete and produce non-degenerate splits in ~65-70s per
  run on the test fixture (not the 2.5-4.7 **hours**/seed the source project reports at real
  dataset scale — this is the one adapter that should never be part of a default/`--all` package
  set). Found and honestly documented a real, non-bug finding: three independent runs on the test
  fixture all landed at near-chance ARI (0.033, -0.031, -0.012) despite each completing correctly
  — matches DISCA's own documented scope (large-scale de novo discovery across thousands of
  particles, not fine classification of a handful of pre-aligned ones) and the source project's
  own extensive results showing it frequently locks onto a contrast axis instead of the true
  structural one even at hundreds of real particles.
- [x] **M11 — STOPGAP** (previously parked 2026-08-14, un-parked 2026-08-26), real CC-matrix
  PCA (rigid pre-rotation `rot_vol` -> pairwise-CC `calc_ccmat` -> eigendecomposition
  `calc_pca_ccmat`, all three compiled MCR binaries dispatched via `mpiexec`) + k-means. Tier D:
  MATLAB needed (to run three plain sequential `.m` glue scripts and for the MCR binaries'
  runtime libraries) but — unlike Dynamo — no Parallel Computing Toolbox license; confirmed by
  reading every `.m` script the PCA path touches, none call `parpool`/`parfor`. Both parking
  concerns turned out to be non-blocking: (1) the "`build_inputs.m` hardcodes a T4P-specific
  filename pattern" concern only applied to STOPGAP's own T4P driver — the source project's
  FM_easy/T3SS variants (single virtual tomogram, sequential `subtomo_N.mrc` naming) were
  already fully generic, so `build_inputs_generic.m` (vendored in `resources/stopgap/`, `stw`'s
  own file, not third-party STOPGAP source) just needed parameterizing by an arbitrary glob
  pattern instead of writing new logic from scratch; `build_wedgelist.m`/`build_pca_aux.m`
  needed zero changes. (2) the MATLAB crash-on-exit risk (`libmwddux.so`, confirmed to
  reproduce here too, always *after* the real computation finishes) is handled the same way as
  Dynamo — check the expected output file, never trust the subprocess's return code.
  Distribution note: like the Dynamo/ProTomo parking concern predicted, STOPGAP has no
  confirmed public download URL (a private archive from its developers) — `check_installed()`
  only locates an existing install, same Tier-D "detect and guide" story as Dynamo.
  A real, machine-specific gotcha found and fixed: the vendored install's
  `exec/lib/stopgap_config*.sh` hardcode a MATLAB-runtime `LD_LIBRARY_PATH` for whoever
  originally configured it; this adapter now always exports its own correct value first
  (from `package_options.stopgap.matlab_root`) since the vendored scripts' own
  `export ...:$LD_LIBRARY_PATH` form appends rather than replaces, so both coexist safely even
  if the vendored path is wrong for the machine actually running `stw`. Also fixed a shared,
  previously-latent gap while building this: `stw`'s own `MPI` requirement checker only checked
  PATH, but this reference machine's OpenMPI (RHEL's `openmpi` RPM) installs `mpiexec` at
  `/usr/lib64/openmpi/bin/mpiexec` without ever putting it on PATH — `resolve_mpi_bin()` now
  falls back to that and a couple of other common distro install paths. Unlike Dynamo, wedge is
  a real pass-through here (`wedge.kind: uniform` builds an actual tilt-range wedgelist;
  `wedge.kind: none` assumes a full +-90 degree range, i.e. no missing-wedge weighting — CTF/
  exposure weighting is always off project-wide, no per-tomogram defocus/dose metadata exists
  for this dataset-agnostic pipeline to use). `seed` is a genuine reproducible seed (k-means
  `random_state=seed`), like Dynamo/ProTomo. PC_TOP=10 default matches the source project's own
  promoted default (native STOPGAP's is just the first 3 columns); `package_options.
  stopgap.pc_cols` overrides it. Verified end-to-end against a real STOPGAP (compiled MCR
  binaries) + MATLAB R2024a + OpenMPI install: the full embedding pipeline runs cleanly through
  `stw run` (~96s on the tiny fixture), k=3 gives a non-degenerate split, embedding-cache reuse
  across k is ~150x faster, two distinct masks build two distinct cached embeddings, and a
  supplied uniform wedge really does reach the wedgelist. Found and honestly documented a real,
  fixture-specific finding, unlike Dynamo's: no single eigen-projection column or small subset
  examined here gets close to a clean class separation (best found, column 3 alone, reaches only
  ARI~0.29 vs. Dynamo's ARI=1.0-on-one-column) — checked directly, not assumed, after confirming
  the embedding pipeline itself is structurally correct; plausibly a genuine property of
  real-space masked CC-matrix comparison responding differently than eigenvolume decomposition
  to this particular synthetic fixture, not a port bug.
- [x] **M12 — GUI**, a local web app (`stw gui`, FastAPI + a vanilla-JS/no-build-step
  frontend), not a native Qt/desktop build — the GUI's job (a config form, a
  requirements/install-status panel, a live progress dashboard) is forms-and-tables, not
  graphics, so avoiding a heavy Qt dependency for a napari-like "launches from the
  terminal, feels local" experience was the better tradeoff; `docs/gui.md` records this
  decision. Binds `127.0.0.1` by default (no auth, runs local shell commands — never meant
  to be exposed beyond localhost). Never a second implementation of anything: the same
  `RunConfig`/`registry()`/`run_config()` core the CLI already uses, and a second
  `ProgressSink` implementation (`QueueProgressSink`, pushing into an in-memory queue)
  alongside the existing `RichProgressSink`/`JsonlProgressSink`, streamed to the browser as
  Server-Sent Events. Single-user, local-only, no persistence beyond the process lifetime
  (an in-memory `RUNS` registry + a background `threading.Thread` per run — `run_config` is
  blocking and mostly waits on subprocesses, so this needed no async rewrite). Class
  averages are rendered to a PNG panel on demand (MRCs aren't browser-displayable) and
  cached to disk on first request; the cross-package comparison figure is served directly
  since it's already a PNG. The config form is hand-written against `RunConfig`'s known,
  stable field set rather than generically generated from `RunConfig.model_json_schema()`
  (still exposed at `/api/schema`, matching the original design intent, just not consumed
  by the frontend yet) — a fully generic JSON-schema-to-form renderer was judged not worth
  building for a "first draft" with a small, well-known field set. Verified end-to-end
  through the real HTTP API (FastAPI `TestClient`, no browser needed): package listing with
  live install status, a full HAC Baseline run through submit -> SSE progress stream ->
  report -> rendered class-average panel, config-validation errors surfacing as real 422s,
  and the comparison figure correctly 404ing when fewer than two packages succeed (the same
  rule the orchestrator itself enforces).

  **Post-first-draft fixes (2026-08-26), found via actually using the GUI**: two real,
  project-wide (not GUI-specific) bugs the GUI was the first thing to actually exercise.
  (1) `run_config()` never resolved a relative `out_dir` to absolute — the GUI form's own
  `./stw_out` default was the first realistic case, and any adapter running a subprocess
  with `cwd` set to a subdirectory of `out_dir` (EMAN2, PyTom) re-resolved a relative path
  argument against the wrong cwd and failed outright. Fixed at the root in
  `orchestrator.run_config()`/`ParticleSet.discover()`, not per-adapter. (2)
  `PackageResult.to_dict()` stringified `class_averages`' keys but not `n_per_class`'s,
  so the GUI's class-average panel always showed `n=?`. Both have regression tests
  (`tests/integration/test_run_hac_end_to_end.py`, `tests/native/test_eman2_real.py`,
  `tests/unit/test_results.py`, `tests/unit/test_gui_server.py`). Also added: a "Preview
  dataset" step (particle count/box/pixel size + a central-slice image of the unweighted
  global average, before committing to a full run) and a per-package `algorithm` summary
  (shown in the picker, plus a `docs/packages.md` overview page) so "what does this
  package actually do" doesn't require reading source.

  **Second round (same day), from real usage feedback**: (3) PyTom's class labels were
  0-indexed (its own native `<Class Name="K"/>`, passed straight through) while every
  other adapter is 1-indexed — visible at k=3 as EMAN2/HAC showing "1, 2, 3" next to
  PyTom's "0, 1, 2". Fixed by `+1`ing in `parse_classified_xml`. Shortened every
  adapter's `algorithm` summary to one line and cross-checked wording against the
  companion [sta-classification-figures](https://jblaser2.github.io/sta-classification-figures/)
  site (now `docs/packages.md`'s primary reference for actually understanding each
  algorithm, not just naming it) — caught two real errors in this project's own prior
  wording: PEET's "WMD" mis-expanded as "weighted multivariate-data" instead of
  wedge-masked-difference, and STOPGAP missing the AWPD (amplitude-weighted
  phase-difference) name entirely. Added a mask-preview overlay (semi-transparent color
  fill on the dataset-preview slice, built from the live form values, no run started)
  and close buttons on both preview panels.

  **Third round (same day), from real usage feedback**: a mask-center override
  (Center Z/Y/X, blank = box center) for sphere/cylinder — `RunConfig.mask.center`
  already existed but the form had no way to set it; `docs/mask-design.md` and the
  form's own labels now also spell out that cylinder's `axis` is the long/extrusion
  axis and `radius` is perpendicular to it. Lowered the mask-overlay's fill opacity
  (0.45 -> 0.25) so the underlying slice stays legible through it. The Progress panel
  now auto-collapses on completion with a "show" toggle to reopen it (for checking an
  error or per-job timing after the fact), reopening itself automatically at the start
  of the next run. A crowded multi-seed results table now collapses each (package, k)'s
  seeds into one expandable summary row — deliberately not an automatic "best seed"
  pick, since there's no principled definition of "best" without ground truth
  (`RunConfig.ground_truth` exists but was never wired into the orchestrator; scoring a
  run against it is still CLI/script-only via `stw.scoring.gt`). The comparison figure
  and every class-average panel are now click-to-full-size (the underlying figure
  already scales resolution with package/seed count; a browser-shrunk `<img>` was the
  actual problem), and an "All class averages" grid shows every successful job's panel
  together below the comparison figure, not just one at a time.

  **Fourth round (same day), from the first real (non-fixture) dataset run**: a
  serious project-wide caching-identity bug, surfaced the moment `stw gui` was
  actually pointed at a real dataset (672-particle T4P, reusing the same `out_dir`
  the tiny test fixture had used earlier in the same session) rather than only ever
  the committed test fixture. No adapter's `job.cache_dir` was ever keyed by *which
  particle set* built its cached prep — EMAN2/PyTom/RELION/PEET use it directly as
  their entire prep directory (no mask-awareness even), ProTomo/Dynamo/DISCA/STOPGAP
  sub-key it only by mask. Reusing `out_dir` across datasets therefore silently
  reused the first dataset's prep for the second, everywhere except PyTom, which
  failed loudly (`class(es) with zero particles`) because its cached particle-list
  XML referenced the first dataset's filenames under the second dataset's particle
  directory. Fixed once, at the root: `ParticleSet.fingerprint()` folds into
  `cache_dir`/`cache_root` in `orchestrator.run_config()` (and `stw mask`'s
  standalone cache) — no adapter needed to change, and every one of their own
  existing mask/wedge-based sub-keys still works exactly as before, just now nested
  one level under a per-dataset directory. A second, related GUI-only bug from the
  same test: the class-average panel endpoint disk-cached its rendered PNG keyed
  only by `out_dir/package/k/seed`, with no invalidation, so it kept serving the
  *first* dataset's stale image even after the fix above corrected the underlying
  MRCs — panels are no longer disk-cached at all, just rendered fresh in memory on
  every request (cheap enough that caching was never actually buying anything).
  This is the kind of bug class the tiny fixture alone could never have surfaced
  (every prior adapter test used a fresh `tmp_path` per test) — a reminder that
  fixture-only testing has a real blind spot around exactly this kind of
  cross-run/cross-dataset state.
- [x] **M13 — `stw align`**, real fine alignment for roughly-aligned (not
  from-scratch unaligned) input, closing part of the gap `docs/limitations.md`'s
  Alignment section had flagged since M0. Investigated three candidates before
  building anything (see `docs/align.md` for the full writeup): STA's own
  hand-rolled NumPy aligner (real and blind, but local-refinement-only — 61 random
  rotation candidates within ±15° of the *current* pose, never validated on
  genuinely unaligned data), Dynamo's `dalign` (a real global search, free plumbing
  reuse from the existing Dynamo adapter, but every real attempt at it crashed on
  an unresolved bug inside Dynamo's own compiled table-serialization binary,
  triggered unpredictably by particle count), and PyTom's FRM (Fast Rotational
  Matching) — chosen. FRM is a genuine global SO(3) search (spherical-harmonic
  correlation, multi-seed) plus joint translational refinement via PyTom's own real
  gold-standard (even/odd, FSC-driven) protocol; confirmed by directly compiling
  and running it, not just reading source.

  The compiled `_swig_frm` extension most PyTom builds lack (PyTom's own installer
  silently disables it on any modern gcc rather than failing) turned out to be a
  bounded, real fix, not a rewrite: `scripts/compile_pytom_frm.sh` clones PyTom
  fresh and builds its bundled 1997-era spherical-harmonics/Situs source with a
  handful of relaxed C flags (`-std=gnu89 -fcommon -Wno-implicit-function-declaration`
  etc.) plus a `$ORIGIN` rpath fix, verified end-to-end from a truly fresh clone (not
  just the dev copy used to find the fix) and by running a real self-alignment
  through the result (score=1.0, correct position, as expected). A second, separate
  real cross-version break found while wiring this up: PyTom's own
  `pytom/bin/FRMAlignment.py` still does `import pytom_mpi`/
  `from pytom_volume import ...` (pre-refactor flat module names only resolvable
  today via `pytom.lib.*`) — worked around with a small vendored runner that aliases
  them into `sys.modules` before running `FRMAlignment`'s own `__main__`, rather
  than patching PyTom's own source (the same shim class as the classification
  adapter's own `Score` fix).

  New `src/stw/align/` (not an Adapter — alignment has no k/seed/class-label
  contract): `AlignConfig`, `run_pytom_alignment()`, a new `ReqKind.CONDA_PYTHON_IMPORT`
  requirement kind (checks importability *inside* a named conda env via subprocess,
  since `stw` never runs inside a package's own env). Bootstraps its own reference
  (a plain average, no ground truth needed) and reuses ~80% of the existing PyTom
  classification adapter's plumbing (ParticleList XML, `mpirun` dispatch, the same
  `SingleTiltWedge` wedge model). The expensive MPI search step is cached
  (a bare re-run skips it entirely — found and fixed during verification: the first
  version cached only the prep steps, not the actual alignment). New `stw align` CLI
  command and a collapsible "Align first" GUI section, both requiring their own
  alignment mask — **reusing the classification mask for alignment was tried once in
  the source project and silently destroyed the classification signal** (blind ARI
  0.637 -> near-chance, since the translation search registers every particle onto
  whatever's inside the mask); `stw`'s own docs and GUI copy call this out
  explicitly rather than letting a user rediscover it.

  Verified end-to-end (native tests + a real GUI HTTP API test) on a real,
  deliberately roughly-misaligned copy of the tiny fixture (small random
  rotation+shift applied per particle, real scipy transforms): 4 real FSC-tracked
  iterations, sharpness (voxel std) recovered from 0.136 (rough) to 0.165 (vs. the
  truly-aligned fixture's own 0.168), poses written to a CSV for provenance, and the
  aligned output classifies cleanly through a normal `stw run` with zero format
  bridging. Honest limitation, stated directly in `docs/align.md`: the one real-data
  test in the source project (already-well-aligned T4P, as a sanity check, not
  genuinely rough data) showed no improvement by visual inspection — this has never
  been validated on real, genuinely rough data, only synthetic ones built for this
  verification.

## Package install tiers

| Tier | Meaning | Packages |
|---|---|---|
| A | Vendored, always available | HAC Baseline, preview-mode ports |
| B | A conda env from a checked-in `envs/<pkg>.yml` sets it up (`conda env create -f envs/<pkg>.yml -n <pkg>`, per that package's own `docs/install/<pkg>.md` — no dedicated `stw install` CLI command exists yet) | EMAN2, PyTom, **DISCA** (confirmed pip-installable PyTorch, no license/compile step; real training realistically needs a GPU though the code falls back to CPU) |
| C | Detected, not auto-installed (no license needed, but no reliable conda/pip path — a source build) | PEET, **ProTomo** (no license itself, but its classification step needs a MATLAB install on the machine for its bundled MKL library — see `docs/install/protomo.md`), **RELION** (no trustworthy conda-forge/bioconda package exists; official install is a CMake source build) |
| D | MATLAB-licensed and/or per-machine compile step | **Dynamo** (Parallel Computing Toolbox required, no CPU-only fallback), **STOPGAP** (MATLAB needed but, unlike Dynamo, no PCT license — parallelism is OS-level MPI) |

TomoFlow and OPUS-TOMO are intentionally out of scope — both are too slow for a "quick"
comparison tool.
