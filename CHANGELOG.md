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

### Fixed
- Native-format mask caching (EMAN2's `standard_mask.hdf`, PyTom's `mask.em`) was keyed only
  on file existence, not the mask's own content hash — changing masks across `stw run`
  invocations sharing an `out_dir` would have silently reused a stale converted mask. Found
  while validating PyTom's wedge caching and fixed in both adapters.
