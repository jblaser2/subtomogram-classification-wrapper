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
