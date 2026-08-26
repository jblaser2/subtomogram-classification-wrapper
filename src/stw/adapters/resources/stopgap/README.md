# STOPGAP glue scripts

None of these are official STOPGAP source — STOPGAP itself ships only
`sg_toolbox` (a MATLAB function library) and compiled MCR binaries
(`stopgap`, `stopgap_parser`, `sg_toolbox`) with no ready-made "take an
arbitrary particle directory and produce a PCA-classifiable dataset" driver.
All three files below just call real `sg_toolbox` functions to build that
driver; they never reimplement any STOPGAP algorithm.

- `build_wedgelist.m`, `build_pca_aux.m` — dataset-agnostic already (take
  only a rootdir + numeric params), no changes made.
- `build_inputs_generic.m` — `stw`'s own replacement for the source
  project's per-dataset `build_inputs*.m` variants (which either hardcode a
  `aligned_tom<T>_P<NNNN>.mrc` regex for real per-tomogram grouping, or — the
  pattern this file generalizes — put every particle into one virtual
  tomogram with sequential `subtomo_N.mrc` naming). `stw` has no real
  per-tomogram grouping for an arbitrary user's particle set, so the
  single-virtual-tomogram form is the only one that generalizes.

Row order contract: `build_inputs_generic.m` numbers particles `1..n` in
`sorted(glob(pattern))` order — the same canonical order `ParticleSet.files`
already guarantees — so `pca/eigenval_1.csv`'s row *i* always corresponds to
`job.particles.files[i]` with no separate id-mapping file needed.
