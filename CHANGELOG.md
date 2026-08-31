# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added
- Initial repo scaffolding: `src/stw` package layout, core abstractions
  (`spec`, `config`, `requirements`, `capabilities`), mask primitives (sphere + cylinder),
  generic class-averaging, cross-package comparison, the `Adapter` contract, and a first
  Tier-A adapter (HAC Baseline).
- CLI: `stw list`, `stw check-env`, `stw init`, `stw run`.
- CI: unit tests + adapter contract tests on every push.
- `mode: preview` adapters (`dynamo-preview`, `pytom-preview`, `protomo-preview`) — vendored,
  dependency-free Python approximations of each package's real classifier, each surfacing its
  own measured fidelity as a `check-env` note and a run-time warning. `get_adapter_for_mode()`
  resolves a bare package name (`dynamo`) to its `-preview` variant only when `mode: preview`
  is set, staying forward-compatible with a future native adapter of the same name.
- **EMAN2 adapter** — the first real native package. Wraps EMAN2's own tools inside a `eman2`
  conda env, with a cached multi-step prep (patch/ingest/consensus-average/postprocess/mask
  convert) shared across every k/seed. Verified end-to-end against a real installed EMAN2:
  exact recovery on the synthetic fixture, cached reruns ~2.4x faster. `docs/install/eman2.md`
  + `envs/eman2.yml` added.
- **PyTom adapter** — real (not preview), driving `auto_focus_classify_nofrm.py` via `mpirun`
  inside a `pytom_env` conda env. First adapter with a real, verified missing-wedge
  pass-through (`wedge.kind: uniform` bakes a real `SingleTiltWedge` into PyTom's particle-list
  XML). Verified end-to-end against a real installed PyTom: exact recovery on the fixture.
  `docs/install/pytom.md` + `envs/pytom.yml` added.
- **Tier A/B container image** (`docker/Dockerfile.tier-ab`) bundling HAC Baseline, all three
  preview adapters, EMAN2, and PyTom. Built and run end-to-end with Podman (rootless, no
  Docker daemon): a real 3-package run against the tiny fixture scored ARI=1.0 against ground
  truth for HAC/EMAN2/PyTom alike, with full cross-package agreement. See `docker/README.md`.
- **RELION adapter** — real Class3D, driving `relion_refine` directly (no conda env needed at
  all: prep is pure numpy/text-format work done in-process). Second adapter with a real,
  verified missing-wedge pass-through (a real single-axis 3D CTF cube built from the actual
  tilt range). `--random_seed` is a genuine reproducible seed here, unlike EMAN2/PyTom's
  run-index pseudo-seed. Verified end-to-end against a real `relion_refine` 5.0.1 build: exact
  recovery on the fixture. `docs/install/relion.md` added; reclassified to Tier C after
  confirming no trustworthy conda-forge/bioconda package exists.
- **PEET adapter** — drives the real `averageAll` → `pca` → `clusterPca` → `usePcaMotiveLists`
  pipeline (WMD-PCA + PEET's own native k-means, not reimplemented). Tier C: sources IMOD's and
  PEET's own setup scripts before every native call rather than assuming any fixed PATH.
  Replicates a real gotcha from the source STA benchmark project: one MRC per particle as
  separate `fnVolume` "tomograms" silently breaks PEET (only the first tomogram gets iterated
  when every tomogram has one particle) — fixed by always stacking every particle into one MRC
  "tomogram" with a single IMOD model. Verified end-to-end against real IMOD + PEET 1.18.2:
  exact recovery on the fixture, cached reruns ~2x faster. `docs/install/peet.md` added.
- **ProTomo adapter** — drives the real `tomoprepare` → `subvolinitial.sh` →
  `subvolsvd.sh` → `subvolhac.sh` pipeline (SVD/MSA + Ward-HAC). Tier C, but with a
  genuinely unusual dependency found by direct probing: `subvolsvd.sh`'s own LAPACK
  call crashes against this kind of system's BLAS/LAPACK and needs MATLAB's bundled
  MKL `LD_PRELOAD`ed instead — a real MATLAB install, though MATLAB itself is never
  launched. Found and fixed a subtle correctness bug: `subvolhac.sh` reads its
  `CLASSES`/`CLSFACT` from a one-time `cycle-000/param.sh` snapshot, not from
  re-`source`d `param-template.sh` — enabling a real caching win, since the expensive
  SVD step is independent of `k` and can be cached once per mask, shared across every
  `k`/seed. Deliberately skips ProTomo's own `subvolclassaverage.sh`/`subvolclassalign.sh`
  (unneeded — `subvolhac.sh` alone already writes everything needed, and `stw` builds
  its own generic class averages). Verified end-to-end against real ProTomo/I3 3.1.0:
  exact recovery on the fixture, a cached rerun at a different k ~7x faster, two
  different masks build two distinct cached workspaces. `docs/install/protomo.md` added.
- **Dynamo adapter** — drives the real `dpkpca` embedding (`dpkpca.new` -> `.unfold()` ->
  `prealign` -> `ccmatrix` -> `eigentable` -> `eigenvolumes`), cached once per particle set
  + mask; the final clustering (`sklearn.cluster.KMeans`, a genuine reproducible seed unlike
  EMAN2/PEET's run-index pseudo-seed) runs in Python per `(k, seed)`. Tier D: hard-requires
  MATLAB's Parallel Computing Toolbox license. Found and honestly documented a real, non-bug
  finding: blind top-10-eigencomponent k-means lands near chance on the test fixture even
  though the true class-separating signal is cleanly present in the embedding — the same
  "blind PC/factor selection isn't always the discriminating axis" property already
  established for ProTomo/STOPGAP/Dynamo in the source project; exposes
  `package_options.dynamo.pc_cols` as the same tuning knob. Verified end-to-end against a
  real Dynamo + MATLAB R2024a + PCT install both ways (honest near-chance blind default,
  exact recovery with `pc_cols` tuned), k=3 non-degeneracy, ~60x faster cached rerun across
  k, and two distinct masks building two distinct cached embeddings. `docs/install/dynamo.md`
  added.
- **DISCA adapter** — drives the real YOPO CNN + Gaussian-mixture EM training/classification
  loop (`torch_disca_run.py`, vendored from the `aitom` toolkit) inside a `disca` conda env.
  Tier B: pip-installable PyTorch, reclassified from "(unconfirmed)" to confirmed. Input
  packaging (mask + Fourier-crop + standardization) is pure numpy/mrcfile logic done
  in-process. Always passes `DISCA_FIX_CHANNELS=1` (a required correctness fix at any box
  size other than 32, not an opt-in toggle). Genuinely unseeded — `seed` is a run index in
  name only; only the mask-dependent input packaging is cached, every classification run is
  an independent training run. Found and honestly documented a real, non-bug finding: three
  independent runs on the test fixture all landed at near-chance ARI despite each completing
  correctly, matching DISCA's own documented scope (large-scale de novo discovery, not fine
  classification of a handful of pre-aligned particles). Verified end-to-end against a real
  `disca` conda env + GPU: k=2/k=3 both non-degenerate, ~65-70s per run on the test fixture
  (versus 2.5-4.7 hours/seed at real dataset scale — never part of a default/`--all` set).
  `docs/install/disca.md` + `envs/disca.yml` added.
- **STOPGAP adapter** — drives the real CC-matrix PCA pipeline (`rot_vol` -> `calc_ccmat` ->
  `calc_pca_ccmat`, compiled MCR binaries dispatched via `mpiexec`) + k-means, previously
  parked (2026-08-14) over two concerns that turned out non-blocking: `build_inputs.m`'s
  apparent T4P-specific hardcoding only applied to that one dataset's driver (a generic
  single-virtual-tomogram variant already existed and just needed generalizing, vendored as
  `build_inputs_generic.m`), and the MATLAB crash-on-exit risk is handled the same defensive
  way as Dynamo (check the output file, not the subprocess return code). Tier D, but — unlike
  Dynamo — no Parallel Computing Toolbox license needed; parallelism is OS-level MPI. Real
  wedge pass-through (`wedge.kind: uniform` builds an actual tilt-range wedgelist;
  `wedge.kind: none` assumes a full +-90 degree range). `seed` is a genuine reproducible seed.
  Found and honestly documented a real, fixture-specific finding: no PC subset examined here
  recovers a clean class separation on the test fixture the way Dynamo's did (best found,
  ARI~0.29), after independently confirming the embedding pipeline itself is structurally
  correct. Verified end-to-end against a real STOPGAP + MATLAB R2024a + OpenMPI install:
  full pipeline runs cleanly (~96s on the fixture), k=3 non-degeneracy, ~150x faster cached
  rerun across k, two distinct masks build two distinct cached embeddings, and a supplied
  uniform wedge reaches the wedgelist. `docs/install/stopgap.md` added.
- **`stw gui`** — a local web GUI (new `gui` extra: FastAPI + uvicorn), not a native
  desktop build: binds `127.0.0.1` by default, opens a browser tab, and drives the exact
  same `RunConfig`/`registry()`/`run_config()` core the CLI uses. A new `QueueProgressSink`
  (`stw.gui.server`) implements the same `ProgressSink` protocol as `RichProgressSink`/
  `JsonlProgressSink`, streaming live per-package progress to the browser over
  Server-Sent Events. Class-average MRCs are rendered to a PNG panel on demand
  (`stw.gui.render`, cached to disk on first request); the cross-package comparison figure
  is served directly. Single-user, in-memory run registry, no persistence beyond the
  process lifetime. `docs/gui.md` added.
- **Dataset preview** in `stw gui`: a "Preview dataset" button loads the particle set
  (no run started) and shows particle count, box size, pixel size, and a central-slice
  PNG of the unweighted global average, so a config can be sanity-checked before
  committing to a full run (`POST /api/preview`, `render_volume_slice_png`).
- **Per-package algorithm summaries**: every adapter now declares a short, one-line
  `algorithm` ClassVar describing the real classification method it drives, surfaced in
  `stw gui`'s package picker (along with a `k range`/`fixed k` badge for capability-
  limited adapters like `pytom-preview`'s validated-only k=2) and consolidated in a new
  `docs/packages.md` overview page (linked from the GUI and from `README.md`). Wording is
  deliberately aligned with the companion
  [sta-classification-figures](https://jblaser2.github.io/sta-classification-figures/)
  site's own algorithm tags (a step-by-step visual walkthrough per package, now linked
  from `docs/packages.md` as the reference for actually understanding each algorithm) —
  cross-checking against it caught two real wording errors in this project's own text:
  PEET's "WMD" was mis-expanded as "weighted multivariate-data" (it's
  wedge-masked-difference) and STOPGAP's method was missing the AWPD
  (amplitude-weighted phase-difference) name entirely.
- **Mask preview** in `stw gui`: a "Preview mask" button next to the mask fields builds
  the mask from the current form values (sphere/cylinder/auto/file, no run started) and
  overlays it as a semi-transparent color fill on the same central-slice global average
  the dataset preview uses (`POST /api/preview-mask`, `render_mask_overlay_png`).
- Both preview panels (dataset and mask) now have a "Close" button so the sidebar can be
  cleared without reloading the page.
- **Mask center override**: `stw gui`'s mask section now exposes optional Center Z/Y/X
  fields (blank = box center) for `sphere`/`cylinder`, matching `RunConfig`'s existing
  `mask.center` field, which the form previously had no way to set at all.
- **Collapsible progress panel**: auto-collapses when a run finishes (a "show" toggle in
  its header reopens it to check a failure message or per-job timing after the fact) and
  always reopens at the start of a new run.
- **Results table grouping**: a (package, k) with more than one seed now collapses into
  one summary row ("N seeds ▸", expandable) instead of listing every seed — narrows a
  crowded multi-seed/multi-k results table visually. No automatic "best seed" selection
  is offered, since there's no principled way to define "best" without ground truth
  (`RunConfig.ground_truth` exists but isn't wired into the orchestrator).
- **Comparison figure and class-average panels are now click-to-full-size** (open the raw
  PNG in a new tab) — `render_comparison_figure`'s own figure size already scales with
  package/seed count, but a browser-shrunk `<img>` was making it illegible with more than
  a few packages.
- **"All class averages" grid**: every successful job's class-average panel now also
  renders together in one grid below the comparison figure, not just one at a time via
  each row's own button.
- **`stw align`** — a new alignment feature for roughly-aligned (not from-scratch
  unaligned) input, driving PyTom's real FRM (Fast Rotational Matching): a genuine
  global SO(3) rotational search plus joint translational refinement, run to
  convergence via PyTom's own real gold-standard (even/odd, FSC-driven adaptive
  lowpass) protocol under `mpirun` — never reimplements the algorithm. Chosen over two
  alternatives after directly building and testing both: a hand-rolled NumPy aligner
  from the source benchmark project (local-refinement-only, never validated on
  genuinely unaligned data) and Dynamo's `dalign` (a real global search too, but every
  real attempt at it crashed on an unresolved bug inside Dynamo's own compiled
  table-serialization binary, data-shape-triggered). Needs a compiled `_swig_frm`
  extension most PyTom builds don't ship with — new `scripts/compile_pytom_frm.sh`
  clones PyTom fresh and builds it with the handful of relaxed C flags its bundled
  1997-era spherical-harmonics source needs under a modern compiler (confirmed by
  actually compiling and running a real alignment through it, not just reading the
  source). New `stw align` CLI command and a collapsible "Align first" section in
  `stw gui`, both requiring their own alignment mask, deliberately separate from the
  classification mask — reusing one for both was tried once in the source project and
  silently destroyed the classification signal (blind ARI 0.637 -> near-chance). Real,
  machine-specific compatibility shim needed: PyTom's own `pytom/bin/FRMAlignment.py`
  still does `import pytom_mpi`/`from pytom_volume import ...` (pre-refactor flat
  module names only resolvable today via `pytom.lib.*`), worked around in a small
  vendored runner rather than patching PyTom's own source. Verified end-to-end on a
  real, deliberately roughly-misaligned copy of the tiny test fixture: FRM alignment
  recovered the perturbed average's sharpness from 0.136 back to 0.165 (vs. the truly
  pre-aligned fixture's own 0.168), the aligned output classifies cleanly through a
  normal `stw run` with no format bridging, and a bare re-run correctly skips the
  expensive MPI search entirely. `docs/align.md` added.

### Fixed
- PyTom's `mpirun` call failed outright inside a container (OpenMPI's `prterun` refuses to run
  as root at all without `--allow-run-as-root`, and a container's default user is root). The
  adapter now adds this flag automatically when running as root (a no-op otherwise).
- `envs/pytom.yml` now pins `gcc=12`/`gxx=12`: PyTom's C extensions are SWIG-generated wrappers
  predating Python 3's C API and contain a couple of genuine ISO C violations that pre-GCC-14
  toolchains only warn about; GCC 14+ promotes them to hard errors by default and the build
  fails outright (confusingly: past `pytom/bin/pytom` never being generated, not with an
  obvious compiler error). Also: the install must go through `conda run`, never a bare
  interpreter path, since the compile step's own subprocess calls (`swig`, the compiler)
  resolve by bare name against whatever's on `PATH`.
- Native-format mask caching (EMAN2's `standard_mask.hdf`, PyTom's `mask.em`) was keyed only
  on file existence, not the mask's own content hash — changing masks across `stw run`
  invocations sharing an `out_dir` would have silently reused a stale converted mask. Found
  while validating PyTom's wedge caching and fixed in both adapters.
- `conda_env` requirement checks only looked at two hardcoded personal-machine paths
  (`~/conda-envs`, `~/miniforge3/envs`) — couldn't find envs anywhere else (a Docker/Podman
  image's `/opt/conda/envs`, Anaconda's default layout, ...). Now asks `conda env list --json`
  first, falling back to a wider set of common paths.
- The vendored PyTom classifier script crashed (`AttributeError` on a `None` `Score`) against
  a freshly-installed PyTom, because `pytom.basic.structures.ParticleList.pickle()` in current
  upstream assumes every particle already has a score — pre-aligned particle lists never set
  one. Added a small compatibility shim (gives each particle an explicit zero score first).
  Found while validating the Tier A/B Docker image against a fresh PyTom install.
- `relion_refine`'s own `--i`/`--ref`/`--o`/`--solvent_mask` argument parsing misidentifies a
  valid path as invalid if the path string contains an `@` anywhere (found on a machine whose
  username is `user@domain`, easily inherited by a temp/output directory). The RELION adapter
  now always passes paths relative to a fixed working directory instead of raw absolute
  strings, the same pattern already used for EMAN2.
- The `EXECUTABLE` requirement checker only checked bare `PATH` — real for a from-source binary
  with no fixed install convention (e.g. `relion_refine`). It now also searches a declarable
  list of common fallback directories.
- The ProTomo adapter's particle-series symlinks broke when `particles:` was a relative path:
  `Path.symlink_to()` on a relative target resolves relative to the symlink's *own* directory,
  not the invoking cwd, so every symlink inside `stacks/` pointed one directory level too deep.
  Fixed by resolving each particle path to absolute before creating the symlink.
- The `MATLAB_TOOLBOX` requirement checker could report a real, valid license as missing:
  `matlab -batch`'s occasional segfault in an unrelated telemetry module (found while
  validating the Dynamo adapter, roughly 1 in 8 invocations, always after the license check's
  own answer was already printed) could append crash-dump text to stdout or pre-empt the print
  entirely, breaking an exact `stdout.strip() == "1"` match. Now reads only the first non-empty
  stdout line and retries once before concluding the license is unavailable.
- The `MPI` requirement checker only looked at `PATH` — real distro OpenMPI packages (found
  while building the STOPGAP adapter: this reference machine's RHEL `openmpi` RPM) install
  `mpiexec`/`mpirun` without ever putting them on `PATH`. `resolve_mpi_bin()` now also checks a
  handful of common distro install paths (e.g. `/usr/lib64/openmpi/bin/mpiexec`).
- The STOPGAP adapter's `build_inputs_generic.m` call broke when `particles:` was a relative
  path, for the same reason already found and fixed for ProTomo: the matlab subprocess's `cwd`
  is the embedding cache dir, not the invoking cwd, so a relative particle path resolved to the
  wrong location. Fixed by resolving it to absolute before interpolating into the MATLAB call.
- A real, project-wide bug found via `stw gui` (whose form defaults to a relative
  `./stw_out`, the first thing to actually exercise this): `run_config()` never resolved
  a relative `out_dir` to absolute, so `job.workdir`/`job.cache_dir`/`mask_path` — and
  therefore anything derived from them, e.g. EMAN2's mask path or PyTom's particle-list
  output path — stayed relative too. Any adapter that runs a multi-step subprocess with
  `cwd` set to a *subdirectory* of `out_dir` (EMAN2, PyTom, and others) then re-resolved
  that same relative path against the wrong cwd, landing in a nonexistent nested location
  and failing outright. Fixed at the root: `out_dir` (in `orchestrator.run_config()`) and
  `particles.particle_dir` (in `ParticleSet.discover()`) are now resolved to absolute
  once, at the top, fixing every adapter at once rather than patching each one's own
  subprocess calls individually.
- `PackageResult.to_dict()` stringified `class_averages`' keys but left `n_per_class`'s
  keys as `int` — any caller keying off both together (the GUI's class-average panel
  renderer, which needs a class's particle count to label its slice) saw a type mismatch
  and always fell back to `n=?`. Both now consistently str-keyed.
- PyTom's class labels were 0-indexed (PyTom's own native `<Class Name="K"/>`, passed
  straight through), unlike every other adapter's 1-indexed convention — found via the
  GUI at k=3 (EMAN2/HAC showed "1, 2, 3", PyTom showed "0, 1, 2"). `parse_classified_xml`
  now `+1`s PyTom's own labels to match.
- The mask-preview overlay's fill (`alpha=0.45`) was too opaque to see the underlying
  grayscale slice clearly through it; reduced to `alpha=0.25`.
- The cylinder mask's `axis`/`radius`/`half_height` fields had no explanation of what
  they actually control — `docs/mask-design.md` and `stw gui`'s own field labels now
  say explicitly that `axis` is the long/extrusion axis and `radius` is perpendicular
  to it, independent of `half_height`.
- **A real, serious caching-identity bug, found via the GUI on a real dataset**: no
  adapter's `job.cache_dir` (EMAN2/PyTom/RELION/PEET use it directly as their whole
  prep dir; ProTomo/Dynamo/DISCA/STOPGAP sub-key it only by mask) ever accounted for
  *which particle set* built its cached prep. Reusing the same `out_dir` for two
  different datasets (e.g. `stw gui`'s form keeping its default `out_dir` across
  runs, as most users would naturally do switching from a quick test to a real
  dataset) silently reused the first dataset's cached prep for the second — loudly
  for PyTom (a hard `class(es) with zero particles` failure, since its cached
  particle-list XML referenced the first dataset's filenames, none of which exist
  under the second dataset's particle directory) and possibly *silently* for every
  other adapter, which have no equivalent existence check. Fixed at the root:
  `ParticleSet.fingerprint()` (a hash of particle directory/pattern/file list/box/
  pixel size) is now folded into `cache_dir`/`cache_root` in
  `orchestrator.run_config()` (and `stw mask`'s own standalone cache), so every
  distinct dataset automatically gets its own cache subdirectory — no adapter needed
  to change. **If you ran more than one dataset through the same `out_dir` before
  this fix, results from every adapter except PyTom (which failed loudly) should be
  treated as unverified and re-run.**
- A related GUI-only bug: the class-average panel endpoint cached its rendered PNG
  on disk keyed only by `out_dir/package/k/seed`, with no invalidation — reusing the
  same `out_dir` for a second dataset kept serving the *first* dataset's stale
  rendered image even after the fix above made the underlying class-average MRCs
  themselves correct. Panels are no longer disk-cached at all; `render_class_average_panel`
  now returns PNG bytes directly (rendering is cheap enough that there's no reason to
  cache it).
