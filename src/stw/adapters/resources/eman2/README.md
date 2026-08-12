# Vendored EMAN2 pipeline scripts

Vendored verbatim from the STA benchmark project
(`packages/eman2/T4P/scripts/`), which validated this exact pipeline against
real T4P cryoET data. Unlike the `preview/` ports, these scripts don't
reimplement anything — they drive EMAN2's own `e2spt_average.py`,
`e2refine_postprocess.py`, and `e2spt_pcasplit.py` (real EMAN2, run inside a
conda env named `eman2`).

- `patch_scripts.py` — patches the *installed* `e2spt_pcasplit.py` in place
  (idempotent, backs up first): fixes a `np.int` deprecation that breaks on
  modern numpy, and gates two optional behavior changes (reference-based
  missing-wedge fill, per-particle normalization) behind flags/env vars that
  default to EMAN2's original behavior. `stw`'s EMAN2 adapter always applies
  Patch 1 (required just to run) and leaves Patches 2/3 at their default-off
  behavior unless a user opts in via `package_options`.
- `make_project.py` — ingests a directory of MRC particles into EMAN2's own
  `particles.hdf`/`ptcls.lst`/`initial_ref.hdf` project format.
- `make_identity_parms.py` — writes a `particle_parms_NN.json` with identity
  orientations, since `stw` (like the source project) assumes pre-aligned
  input and performs no subtomogram alignment search.
