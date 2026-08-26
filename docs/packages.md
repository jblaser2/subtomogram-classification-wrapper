# What each package actually does

One page, one paragraph per package, on the real classification algorithm
`stw` drives — never a reimplementation, always the package's own launcher.
The same text is shown inline in `stw gui`'s package picker. For full
install/requirements/capability detail per package, see its own
`docs/install/<pkg>.md` page (linked below).

## Real native packages

- **[EMAN2](install/eman2.md)** — `e2spt_pcasplit.py`: PCA on masked
  per-particle differences from a consensus average, then k-means in PCA
  space.
- **[PyTom](install/pytom.md)** — `auto_focus_classify_nofrm.py`: iterative
  reference-pair difference-map classification. Starts from k random
  references, alternates masked-NCC particle assignment with recomputing
  per-cluster averages and the mask region that best discriminates each
  reference pair.
- **[RELION](install/relion.md)** — `relion_refine`'s real 3D classification
  (Class3D): regularized maximum-likelihood expectation-maximization in
  Fourier space over k 3D references, orientation search disabled (`stw`
  assumes pre-aligned input project-wide).
- **[PEET](install/peet.md)** — real WMD-PCA + native `clusterPca` k-means,
  driven through `averageAll` → `pca` → `clusterPca` → `usePcaMotiveLists`:
  weighted multivariate-data PCA on masked per-particle differences, then
  PEET's own k-means in PCA space.
- **[ProTomo](install/protomo.md)** — I3/ProTomo's real `subvolsvd.sh`
  (SVD/multi-statistical-analysis on masked per-particle differences) +
  `subvolhac.sh` (Ward-linkage hierarchical clustering in the SVD's factor
  space, cut to k classes).
- **[Dynamo](install/dynamo.md)** — real `dpkpca`: CC-matrix eigendecomposition
  (`prealign` → `ccmatrix` → `eigentable` → `eigenvolumes`) producing
  per-particle eigencomponents, then k-means (in Python, not MATLAB) on the
  top components.
- **[DISCA](install/disca.md)** — a YOPO convolutional feature extractor +
  Gaussian-mixture-model EM, trained end to end per run (from the `aitom`
  toolkit) — a real deep-learning de novo discovery method, not a classical
  distance/PCA approach like the others here. Genuinely slow (hours/seed at
  real dataset scale); never in a default package set.
- **[STOPGAP](install/stopgap.md)** — real CC-matrix PCA: rigid-body
  pre-rotation (`rot_vol`) → pairwise correlation matrix (`calc_ccmat`) →
  eigendecomposition (`calc_pca_ccmat`), then k-means on the top
  eigen-projections.

## HAC Baseline

A generic, package-independent control, not tied to any real classification
software: Pearson correlation-coefficient distance between every particle
pair, then Ward-linkage hierarchical clustering cut to k classes. Useful as
a sanity-check floor to compare every real package against.

## `mode: preview` — zero-install approximations

Three packages (Dynamo, PyTom, ProTomo) have a lightweight, dependency-free
Python port that approximates their real algorithm well enough for a rough,
zero-install comparison — never a substitute for the real package, and each
one's own `check-env`/GUI note says so explicitly. See
[`docs/limitations.md`](limitations.md#mode-preview) for measured fidelity
against the real algorithm.

## Excluded entirely

TomoFlow and OPUS-TOMO are out of scope — both are far too slow for a
quick, first-look comparison tool. See
[`docs/limitations.md`](limitations.md#excluded-packages).
