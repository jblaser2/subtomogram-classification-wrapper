# What each package actually does

One line per package on the real classification algorithm `stw` drives —
never a reimplementation, always the package's own launcher. The same text
is shown inline in `stw gui`'s package picker.

!!! tip "Visual walkthroughs"
    For a step-by-step visual walkthrough of each algorithm (real data, real
    computed numbers for the 6 primary packages), see
    [**jblaser2.github.io/sta-classification-figures**](https://jblaser2.github.io/sta-classification-figures/)
    — a companion site from the same benchmark project this tool grew out
    of. The short algorithm tags below intentionally match that site's own
    wording; per-package links go straight to each package's figure page.

For full install/requirements/capability detail per package (not covered by
the figures site, which is about the algorithm, not installing it), see its
own `docs/install/<pkg>.md` page, linked below.

## Real native packages

- **[EMAN2](install/eman2.md)** ([figures](https://jblaser2.github.io/sta-classification-figures/eman2/figure.html))
  — Fourier-space PCA + k-means (`e2spt_pcasplit.py`).
- **[PyTom](install/pytom.md)** ([figures](https://jblaser2.github.io/sta-classification-figures/pytom/figure.html))
  — iterative auto-focus classification (`auto_focus_classify_nofrm.py`).
- **[RELION](install/relion.md)** ([figures](https://jblaser2.github.io/sta-classification-figures/relion/figure.html))
  — regularized ML-EM, orientation search off (`relion_refine` Class3D).
- **[PEET](install/peet.md)** ([figures](https://jblaser2.github.io/sta-classification-figures/peet/figure.html))
  — wedge-masked-difference (WMD) PCA + k-means (`averageAll`/`pca`/`clusterPca`).
- **[ProTomo](install/protomo.md)** ([figures](https://jblaser2.github.io/sta-classification-figures/protomo/figure.html))
  — bandpass + SVD-MSA + Ward-HAC (`subvolsvd.sh`/`subvolhac.sh`).
- **[Dynamo](install/dynamo.md)** ([figures](https://jblaser2.github.io/sta-classification-figures/dynamo/figure.html))
  — CC-matrix kernel PCA + k-means (`dpkpca`).
- **[DISCA](install/disca.md)** ([figures](https://jblaser2.github.io/sta-classification-figures/disca/figure.html))
  — self-supervised deep clustering loop (YOPO CNN + Gaussian-mixture EM).
  Genuinely slow (hours/seed at real dataset scale); never in a default
  package set.
- **[STOPGAP](install/stopgap.md)** ([figures](https://jblaser2.github.io/sta-classification-figures/stopgap/figure.html))
  — amplitude-weighted phase-difference (AWPD) PCA + k-means
  (`rot_vol`/`calc_ccmat`/`calc_pca_ccmat`).

## HAC Baseline

Correlation distance + Ward-HAC ([figures](https://jblaser2.github.io/sta-classification-figures/hac_baseline/figure.html))
— a generic, package-independent control, not tied to any real classification
software. Useful as a sanity-check floor to compare every real package
against.

## `mode: preview` — zero-install approximations

Three packages (Dynamo, PyTom, ProTomo) have a lightweight, dependency-free
Python port that approximates their real algorithm well enough for a rough,
zero-install comparison — never a substitute for the real package, and each
one's own `check-env`/GUI note says so explicitly. See
[`docs/limitations.md`](limitations.md#mode-preview) for measured fidelity
against the real algorithm.

## Excluded entirely

TomoFlow and OPUS-TOMO are out of scope for `stw` itself — both are far too
slow for a quick, first-look comparison tool — but the figures site still
covers them for reference: optical flow + PCA + k-means, and β-VAE latent
space + k-means, respectively. See
[`docs/limitations.md`](limitations.md#excluded-packages).
