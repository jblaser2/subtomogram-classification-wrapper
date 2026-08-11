#!/usr/bin/env python3
"""
protomo_classify_py.py -- a pure-Python port of ProTomo's classification step
(subvolsvd.sh + subvolhac.sh), reimplementing the SVD/MSA + Ward-HAC math without
the closed-source `tomoclass` binary (I3/ProTomo 3.1.0).

WHY THIS EXISTS
---------------
ProTomo is a compiled C suite with no distributed source (`packages/protomo/research.md`).
Alignment (`subvolalign.sh`) is out of scope for this benchmark anyway -- every ProTomo run
in this project bypasses it (particles arrive pre-aligned, GT-pose or blind-aligned, and the
pipeline does a literal `raw.i3i` -> `mra.i3i` copy; see `scripts/run/adapters/protomo.py`).
This port picks up exactly where that copy leaves off: bandpass filter -> real-space mask ->
SVD (MSA) -> Ward-linkage HAC, reimplemented in numpy/scipy/mrcfile so ProTomo's
*classification* step is usable without the ProTomo installation. Follows the precedent and
structure of `packages/dynamo/python_port/dynamo_classify_py.py`.

WHAT PROTOMO'S REAL PIPELINE ACTUALLY DOES  (verified against `packages/protomo/research.md`,
`docs/classification_algorithms.md`'s "## ProTomo (I3)" section, and the literal parameter
values in `scripts/run/adapters/protomo.py` -- ground truth for what this project actually
runs, since `tomoclass` itself is a closed binary with no readable source)
--------------------------------------------------------------------------------------------
  1. subvolalign.sh   BYPASSED in this project (raw.i3i -> mra.i3i copy). Not ported here --
                      this script consumes already-aligned particles directly, same as the
                      Dynamo port consumes already-aligned particles rather than porting
                      `dalign`.
  2. subvolsvd.sh     writes `low-pass ${MSALOWPASS}` / `high-pass ${MSAHIGHPASS}` directives
                      into the `tomoclass` proc file immediately before the `svd to ...`
                      directive -- i.e. every particle is bandpass-filtered before the SVD
                      embedding. Canonical values (from protomo.py, shared by every run this
                      project builds, native and generic workspaces alike):
                        MSALOWPASS  = " 0.400 0.400 0.400 apod 0.050 0.050 0.050"
                        MSAHIGHPASS = "0.060 0.060 0.060 apod 0.007 0.007 0.007"
                      This is a PER-AXIS filter (independent x/y/z low+high cutoff, each with
                      its own Gaussian apodization width, fractional Nyquist 0-0.5) -- NOT a
                      spherical/radial shell like Dynamo's band. See "AMBIGUITY 1" below for
                      how this port turns 3 independent per-axis cutoffs into one 3D transfer
                      function.
  3. (MSAMASK)        a mask file (or an inline geometric-primitive spec) restricts the SVD to
                      the region of interest -- multiplicatively applied in real space, then
                      the SVD operates on the active (masked) voxels only.
  4. (MSAIMGSIZE)     optional central crop to a sub-box smaller than MOTIFSIZE, applied before
                      the mask/filter/SVD. For every run this port validates against,
                      MSAIMGSIZE == MOTIFSIZE (no-op) -- see "NOT EXERCISED BY VALIDATION" below.
  5. subvolsvd.sh     SVD-based MSA ("multivariate statistical analysis," described in
                      `research.md` as "the same family as correspondence analysis in 2D EM
                      classification") on the masked+filtered (+optionally cropped) stack,
                      producing `.sv` (singular values), `.rsv` (right singular vectors), and
                      `.coo` (per-particle SVD-factor coordinates). See "AMBIGUITY 2" below --
                      the exact MSA math (plain mean-centered SVD/PCA vs. true correspondence-
                      analysis mass-weighting) cannot be confirmed from a closed binary.
  6. subvolhac.sh     Ward-linkage HAC on a selected subset of `.coo` columns (`CLSFACT`, e.g.
                      "1-10" -- this project's blind Pass-1 default, 1-indexed inclusive range)
                      to produce k class labels.

TWO JUDGMENT CALLS, FLAGGED EXPLICITLY (read before trusting this port's numbers)
----------------------------------------------------------------------------------
AMBIGUITY 1 -- per-axis filter combination rule. `research.md`/`docs/classification_algorithms.md`
  document that LOWPASS/HIGHPASS are independent per-axis (x, y, z each get their own cutoff +
  apodization), but neither documents HOW the three per-axis 1D filters are combined into one
  3D transfer function -- `tomoclass` is closed. This port builds each axis's 1D bandpass
  profile with the SAME shape family as STOPGAP's `sg_bandpass_filter_1d.m` (raised/Gaussian-
  tapered low-pass minus a Gaussian-tapered high-pass, both in fractional-Nyquist units per
  the ProTomo doc's own units convention -- STOPGAP's version is in pixel units, this port's
  is in fractional Nyquist per ProTomo's convention) and then takes the SEPARABLE OUTER PRODUCT
  of the three 1D axis profiles (H(z,y,x) = Hz(kz)*Hy(ky)*Hx(kx)) to get the 3D filter. This is
  the natural reading of "independent low/high cutoff per axis" and matches how axis-separable
  Fourier filters are usually implemented elsewhere, but it is NOT confirmed against ProTomo's
  actual (inaccessible) source -- an elementwise-min combination, or some other rule, would also
  be consistent with the prose documentation. In this project's canonical runs the three axes
  share identical cutoff values, so the resulting box-shaped passband differs from a spherical
  shell mostly at the corners of frequency space (radius ~0.4*sqrt(3)=0.69 there vs 0.4 on-axis)
  -- a real, if secondary, difference from Dynamo's radial band.
AMBIGUITY 2 -- MSA math. This port implements "MSA" as plain mean-centered SVD (i.e. PCA on the
  masked+filtered voxel vectors), matching the Dynamo port's `--method pca` idiomatic path. This
  is NOT a confirmed bit-exact reproduction of ProTomo's actual correspondence-analysis-family
  algorithm (which may mass-weight rows/columns rather than just mean-center) -- same honesty
  standard as the Dynamo port's README flags for its own approximations.
AMBIGUITY 3 -- per-particle normalization, and mask/filter order (found during FM_easy
  validation, see the port's README "A real pathology, found and (partially) fixed" section).
  With the documented MSAHIGHPASS apodization (0.007, fractional Nyquist -- under 1 px for a
  96-box) taken literally, the resulting per-axis filter is close to an ideal box/step function.
  Applying it directly to a RAW (unmasked) particle -- i.e. filter-then-mask, boundary-to-
  boundary FFT with no real-space taper -- lets a handful of particles' box-boundary
  discontinuities ring into outlier-magnitude feature vectors that swamp every leading SVD
  factor, collapsing Ward-HAC to a degenerate ~all-vs-3 split (ARI ~ 0). Neither behavior is
  documented for `tomoclass` (closed binary); this port mitigates it two ways, both flagged as
  judgment calls, not confirmed ProTomo internals: (1) MASK BEFORE bandpass filtering (the soft
  apodized mask tapers the volume toward zero well inside the box before the FFT, instead of
  after), and (2) per-particle z-score normalization of the masked+filtered voxel vector before
  the ensemble mean-centering/SVD step (removes per-particle contrast/intensity-scale variance --
  a standard preprocessing step in real 2D-EM MSA/correspondence-analysis pipelines, which this
  port's plain-PCA approximation does not otherwise include). Both are needed to avoid the
  degenerate collapse; disable with `--normalize none` to reproduce/inspect the raw pathology.

NOT EXERCISED BY VALIDATION
----------------------------
`--msa-imgsize` (central crop) is implemented and wired through, but every validation run in
this port's README used MSAIMGSIZE == MOTIFSIZE (no crop) -- matching the real canonical T4P/
FM_easy runs this project actually built (see `scripts/run/adapters/protomo.py`'s
`_build_generic_workspace`, which always sets `MSAIMGSIZE="{box} {box} {box}"`). Treat the crop
path as unvalidated.

OUTPUT
------
A predictions CSV with columns `file,pred_label` (basename, 1-based int cluster id, matching
`fcluster`'s native numbering and ProTomo's own 1-based class-int convention) -- the exact
contract of scripts/eval/score_synthetic.py.

USAGE
-----
  conda run -n relion-5.0 python3 packages/protomo/python_port/protomo_classify_py.py \
      --labels <dir>/labels.csv --data <dir> \
      --mask <mask.mrc> --k 2 --clsfact 1-10 --out <preds.csv>
"""
import os
import csv
import sys
import glob
import argparse
import numpy as np
import mrcfile
from scipy.cluster.hierarchy import linkage, fcluster


# --------------------------------------------------------------------------- I/O
def read_mrc(path):
    return np.asarray(mrcfile.open(path, permissive=True).data, np.float32)


def write_mrc(path, vol, apix):
    with mrcfile.new(path, overwrite=True) as m:
        m.set_data(vol.astype(np.float32))
        if apix:
            m.voxel_size = apix


def load_particle_list(labels, data, glob_pat):
    """Return list of (basename, abspath). Prefer labels.csv, else glob the dir."""
    if labels and os.path.exists(labels):
        names = [r["file"] for r in csv.DictReader(open(labels))]
        return [(n, os.path.join(data, n)) for n in names]
    files = sorted(glob.glob(os.path.join(data, glob_pat)))
    return [(os.path.basename(f), f) for f in files]


# ---------------------------------------------------------------- per-axis bandpass
def axis_bandpass_profile(n, lo, lo_apod, hi, hi_apod):
    """1D bandpass profile over `n` corner-ordered FFT bins, fractional-Nyquist units
    (0..~0.5). Same shape family as STOPGAP's sg_bandpass_filter_1d.m: a low-pass
    plateau (1 inside `lo`, Gaussian-tapered by `lo_apod` beyond) minus a high-pass
    plateau (1 inside `hi`, same Gaussian taper by `hi_apod` beyond) -- i.e. passband
    is (hi, lo) with independent Gaussian-apodized edges on each side. See
    AMBIGUITY 1 in the module docstring for why this is a per-axis 1D profile, not
    yet the 3D filter.
    """
    freq = np.abs(np.fft.fftfreq(n)).astype(np.float64)  # corner order, 0..~0.5

    lpf = np.ones(n, dtype=np.float64)
    hi_idx = freq > lo
    if lo_apod > 1e-12:
        lpf[hi_idx] = np.exp(-((freq[hi_idx] - lo) / lo_apod) ** 2)
    else:
        lpf[hi_idx] = 0.0
    lpf[lpf < np.exp(-2)] = 0.0

    hpf = np.ones(n, dtype=np.float64)
    hi_idx2 = freq > hi
    if hi_apod > 1e-12:
        hpf[hi_idx2] = np.exp(-((freq[hi_idx2] - hi) / hi_apod) ** 2)
    else:
        hpf[hi_idx2] = 0.0
    hpf[hpf < np.exp(-2)] = 0.0

    return (lpf - hpf).astype(np.float32)


def make_bandpass_3d(shape_zyx, lowpass_xyz6, highpass_xyz6):
    """Corner-centered 3D bandpass transfer function from two 6-tuples
    (lo_x, lo_y, lo_z, apod_x, apod_y, apod_z) and (hi_x, hi_y, hi_z, apod_x, apod_y, apod_z)
    -- ProTomo's own "x y z apod x y z" ordering for LOWPASS/HIGHPASS/MSALOWPASS/MSAHIGHPASS.
    Builds one 1D profile per axis, then combines by separable outer product (AMBIGUITY 1).
    """
    lo_x, lo_y, lo_z, loa_x, loa_y, loa_z = lowpass_xyz6
    hi_x, hi_y, hi_z, hia_x, hia_y, hia_z = highpass_xyz6
    nz, ny, nx = shape_zyx
    Hz = axis_bandpass_profile(nz, lo_z, loa_z, hi_z, hia_z)
    Hy = axis_bandpass_profile(ny, lo_y, loa_y, hi_y, hia_y)
    Hx = axis_bandpass_profile(nx, lo_x, loa_x, hi_x, hia_x)
    return (Hz[:, None, None] * Hy[None, :, None] * Hx[None, None, :]).astype(np.float32)


def bandpass_real(vol, H_corner):
    """Real-space bandpass-filtered volume (H_corner already corner-ordered)."""
    return np.real(np.fft.ifftn(np.fft.fftn(vol) * H_corner)).astype(np.float32)


# --------------------------------------------------------------------- central crop
def central_crop(vol, size_xyz):
    """Crop a (z,y,x)-ordered volume to a centered sub-box of size (sx,sy,sz)
    (ProTomo's own x-y-z ordering for MSAIMGSIZE). None/no-op if size_xyz is None."""
    if size_xyz is None:
        return vol
    sx, sy, sz = size_xyz
    nz, ny, nx = vol.shape

    def _sl(n, s):
        s = min(s, n)
        start = (n - s) // 2
        return slice(start, start + s)

    return vol[_sl(nz, sz), _sl(ny, sy), _sl(nx, sx)]


# --------------------------------------------------------------------- CLSFACT parsing
def parse_factor_range(spec, nmax):
    """Parse a 1-indexed inclusive CLSFACT spec ("1-10", "1,3,5", "1-4,7-9") into a
    sorted list of 0-indexed column indices, clipped to [0, nmax)."""
    idxs = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            idxs.extend(range(int(a), int(b) + 1))
        else:
            idxs.append(int(part))
    idxs = sorted({i - 1 for i in idxs if 1 <= i <= nmax})
    if not idxs:
        raise ValueError(f"--clsfact {spec!r} selects no valid factors (nmax={nmax})")
    return idxs


# ----------------------------------------------------------------------- MSA (SVD)
def normalize_rows(X, mode):
    """Per-particle normalization of feature vectors, applied BEFORE ensemble
    mean-centering. See AMBIGUITY 3 in the module docstring: needed to avoid a
    degenerate Ward-HAC collapse driven by a handful of outlier-magnitude
    particles dominating the leading SVD factors under the documented (very
    sharp) bandpass filter. mode: "zscore" (default), "unitnorm", or "none"."""
    if mode == "none":
        return X
    mu = X.mean(axis=1, keepdims=True)
    if mode == "zscore":
        sd = X.std(axis=1, keepdims=True)
        return (X - mu) / (sd + 1e-8)
    if mode == "unitnorm":
        Xc = X - mu
        n = np.linalg.norm(Xc, axis=1, keepdims=True)
        return Xc / (n + 1e-8)
    raise ValueError(f"unknown --normalize mode {mode!r}")


def svd_msa_coords(X, nfact):
    """Mean-center then truncated (randomized) SVD -> per-particle coordinates
    (U*S), descending singular value order. This is the "MSA" step
    (subvolsvd.sh's .coo output) -- see AMBIGUITY 2 in the module docstring:
    this is plain mean-centered SVD/PCA, not a confirmed reproduction of
    ProTomo's exact (possibly mass-weighted correspondence-analysis-style) math.
    Uses sklearn's randomized solver (only `nfact` components are ever needed
    downstream) rather than a full economy SVD -- an implementation-speed
    choice, not an algorithmic one; results match full SVD's leading
    components up to solver tolerance."""
    from sklearn.decomposition import TruncatedSVD
    mu = X.mean(axis=0, keepdims=True)
    Xc = X - mu
    ncomp = min(nfact, min(Xc.shape) - 1)
    svd = TruncatedSVD(n_components=ncomp, algorithm="randomized", random_state=0)
    coords = svd.fit_transform(Xc)
    return coords


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="dir of aligned subtomogram .mrc files")
    ap.add_argument("--labels", default=None,
                    help="labels.csv (file[,label]); else glob --data")
    ap.add_argument("--glob", default="subtomo_*.mrc", help="glob if no labels.csv")
    ap.add_argument("--mask", required=True, help="SVD region mask .mrc (ProTomo's MSAMASK)")
    ap.add_argument("--mask-thresh", type=float, default=0.5,
                    help="threshold defining the 'active' voxel support extracted "
                         "into the feature vector (mask itself is still applied as "
                         "a soft real-space multiply before thresholding)")
    ap.add_argument("--k", type=int, required=True, help="number of clusters")
    ap.add_argument("--msa-imgsize", type=int, nargs=3, default=None,
                    metavar=("SX", "SY", "SZ"),
                    help="central crop before filter/mask/SVD (ProTomo's MSAIMGSIZE, "
                         "x y z order); default: no crop (MSAIMGSIZE==MOTIFSIZE)")
    ap.add_argument("--lowpass", type=float, nargs=6, default=[0.4, 0.4, 0.4, 0.05, 0.05, 0.05],
                    metavar=("LX", "LY", "LZ", "AX", "AY", "AZ"),
                    help="MSALOWPASS: per-axis cutoff (x y z) + Gaussian apod width "
                         "(x y z), fractional Nyquist. Default = this project's "
                         "canonical MSALOWPASS.")
    ap.add_argument("--highpass", type=float, nargs=6,
                    default=[0.06, 0.06, 0.06, 0.007, 0.007, 0.007],
                    metavar=("HX", "HY", "HZ", "AX", "AY", "AZ"),
                    help="MSAHIGHPASS, same layout as --lowpass. Default = this "
                         "project's canonical MSAHIGHPASS.")
    ap.add_argument("--nfact", type=int, default=40, help="max SVD factors (MSAFACT)")
    ap.add_argument("--clsfact", default="1-10",
                    help="1-indexed inclusive SVD-factor range/list for HAC "
                         "(ProTomo's CLSFACT; this project's blind Pass-1 default)")
    ap.add_argument("--normalize", choices=["zscore", "unitnorm", "none"], default="zscore",
                    help="per-particle normalization before SVD (see AMBIGUITY 3 in "
                         "the module docstring); 'none' reproduces the degenerate "
                         "collapse pathology found during validation")
    ap.add_argument("--apix", type=float, default=13.329)
    ap.add_argument("--out", required=True, help="output predictions CSV")
    ap.add_argument("--class-avgs-dir", default=None,
                    help="if set, write per-cluster mean-volume MRCs here")
    args = ap.parse_args()

    plist = load_particle_list(args.labels, args.data, args.glob)
    N = len(plist)
    if N == 0:
        sys.exit(f"No particles found under {args.data}")
    print(f"[protomo_classify_py] {N} particles | k={args.k} | clsfact={args.clsfact} | "
          f"lowpass={args.lowpass} | highpass={args.highpass}")

    mask = read_mrc(args.mask)
    mask = central_crop(mask, args.msa_imgsize)
    box_shape = mask.shape
    active = mask > args.mask_thresh
    print(f"  mask (post-crop {box_shape}): {int(active.sum())} active voxels "
          f"(thresh={args.mask_thresh})")

    H = make_bandpass_3d(box_shape, args.lowpass, args.highpass)

    # ---- per-particle: crop -> soft-mask multiply -> bandpass filter -> extract ----
    # Mask BEFORE filter (not filter-then-mask): the soft apodized mask tapers the
    # volume toward zero well inside the box before the FFT, avoiding box-boundary
    # ringing under the documented near-step highpass. See AMBIGUITY 3.
    vols = []       # cropped, unfiltered/unmasked (kept for optional class averages)
    feats = []
    for name, path in plist:
        v = central_crop(read_mrc(path), args.msa_imgsize)
        vols.append(v)
        vf = bandpass_real(v * mask, H)
        feats.append(vf[active])
    X = np.stack(feats).astype(np.float64)
    print(f"  feature matrix: {X.shape[0]} x {X.shape[1]} "
          f"(mask-then-bandpass, active-voxel vectors, normalize={args.normalize})")
    X = normalize_rows(X, args.normalize)

    # ---- SVD/MSA ----
    coords = svd_msa_coords(X, args.nfact)
    print(f"  SVD: {coords.shape[1]} factors retained (of requested {args.nfact})")

    factor_idx = parse_factor_range(args.clsfact, coords.shape[1])
    coords_sel = coords[:, factor_idx]
    print(f"  CLSFACT {args.clsfact} -> columns {[i + 1 for i in factor_idx]}")

    # ---- Ward-linkage HAC ----
    Z = linkage(coords_sel, method="ward")
    labels = fcluster(Z, args.k, criterion="maxclust")  # already 1-based

    # ---- write predictions CSV (file,pred_label) ----
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "pred_label"])
        for (name, _), lab in zip(plist, labels):
            w.writerow([name, int(lab)])
    counts = {c: int((labels == c).sum()) for c in sorted(set(labels))}
    print(f"  wrote {args.out}  clusters: {counts}")

    # ---- optional per-cluster class averages (from cropped, unfiltered vols) ----
    if args.class_avgs_dir:
        os.makedirs(args.class_avgs_dir, exist_ok=True)
        for c in sorted(set(labels)):
            mean_v = np.mean([vols[i] for i in range(N) if labels[i] == c], axis=0)
            outp = os.path.join(args.class_avgs_dir, f"class{c}_avg.mrc")
            write_mrc(outp, mean_v, args.apix)
            print(f"  class {c} average -> {outp}")


if __name__ == "__main__":
    main()
