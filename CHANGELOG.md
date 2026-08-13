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
