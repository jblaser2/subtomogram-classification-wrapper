#!/usr/bin/env python3
"""
dynamo_classify_py.py -- a pure-Python port of Dynamo's classification step (dpkpca).

WHY THIS EXISTS
---------------
Dynamo is a MATLAB package. Its subtomogram classifier ("dpkpca") is the reference
result for the T4P benchmark and the best synthetic-data result of any package
(FM_easy dalign+dpkpca ARI=0.985). To make that classifier usable without a MATLAB
license -- and as a first data point in porting the benchmark's packages to Python
(the field's ML/data-science lingua franca) -- this script reimplements JUST the
classification step in numpy / scipy / scikit-learn / mrcfile. Dynamo's full
alignment engine (`dalign`) is deliberately NOT ported; classification consumes
already-aligned particles (or applies poses from a Dynamo `.tbl`).

WHAT DYNAMO'S dpkpca ACTUALLY DOES  (verified against the MATLAB source at
/home/jblaser2/Research/dynamo/matlab/src/+dpkmath/+pca/)
--------------------------------------------------------------------------
The project drivers (packages/dynamo/FM_easy/scripts/dynamo_dalign_dpkpca.m,
dynamo_easy_pair_pca.m) run these steps, in order:

  1. prealign     apply the .tbl pose to each particle: shift first, THEN inverse
                  Z-X-Z Euler rotation (-fliplr(euler)), THEN a soft spherical taper
                  (suppresses rotation corner artifacts), then
                  F = fftn(vol) .* bandpass  (band = spherical shell 0.05..0.45
                  of Nyquist, 2-px soft edge). Also caches each particle's rotated
                  missing-wedge indicator. This step is NOT an alignment SEARCH --
                  it just applies existing poses. Getting the rotation axis (Z-X-Z,
                  not the more common Z-Y-Z) and the shift/rotate order wrong here
                  silently scrambles poses -- verified and fixed during validation,
                  see packages/dynamo/python_port/README.md.
  2. ccmatrix     for every pair (i,j): filter BOTH particles to the intersection
                  of their missing wedges, W = wedge_i * wedge_j * bandpass;
                  p1 = real(ifftn(F_i*W)), p2 = real(ifftn(F_j*W));
                  cc(i,j) = masked real-space Pearson(p1, p2).  This wedge
                  intersection IS the entire missing-wedge compensation.
  3. eigentable   eigs(CC, nEigs=50, 'LM'); the EIGENVECTORS of the N x N CC
                  (Gram) matrix are the per-particle coordinates (classical-MDS /
                  kernel-PCA style -- NOT a projection onto eigenvolumes).
  4. (eigenvolumes -- visualization only, not needed for class labels)

  Then the runner clusters OUTSIDE Dynamo:
      kmeans(E(:,1:10), k, 'Replicates',20, 'MaxIter',500), rng(42).

TWO MODES
---------
  --method cc   (default, faithful): the CC-matrix / Gram eigendecomposition above.
                When per-particle wedges are identical (the common case for
                pre-aligned synthetic sets -- FM_easy's constrained pool is
                ~common-mode wedge) W is constant, and the whole pairwise loop
                collapses to a single normalized matrix multiply (fast path).
                Pass --tbl AND --tilt-range to enable true per-particle
                wedge-intersection compensation (slower O(N^2) path).
  --method pca  (idiomatic, the "usability" demo): stack masked+bandpassed
                in-mask vectors -> mean-center -> sklearn PCA -> k-means. Drops the
                wedge intersection; reads like any scikit-learn clustering script.

OUTPUT
------
A predictions CSV with columns `file,pred_label` (basename, 1-based int cluster id)
-- the exact contract of scripts/eval/score_synthetic.py, so results plug straight
into the benchmark scorer. (Dynamo's own .m wrote `tag,pred_label`; we key on file.)

USAGE
-----
  conda run -n relion-5.0 python3 packages/dynamo/python_port/dynamo_classify_py.py \
      --labels <dir>/labels.csv --data <dir> \
      --mask <mask.mrc> --k 2 --out <preds.csv> [--method cc|pca]

Reuses the FFT / pose primitives established in scripts/data_prep/align_fm_easy.py.
"""
import os
import csv
import sys
import glob
import argparse
import numpy as np
import mrcfile
from scipy.ndimage import affine_transform


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


# ------------------------------------------------------------ Fourier primitives
def make_bandpass(box, lo, hi, edge_px=2.0):
    """Centered (fftshift'ed) spherical-shell band-pass, soft cosine edge.

    Matches Dynamo setBand([lo, hi, 2]): shell between radii lo..hi as fractions of
    Nyquist, with a 2-pixel soft edge. Returned already fftshift'ed to the corner so
    it multiplies fftn(v) output directly (as in align_fm_easy.py's bp()).
    """
    c = box // 2
    ax = (np.arange(box) - c) / box            # normalized freq, 0.5 = Nyquist
    KZ, KY, KX = np.meshgrid(ax, ax, ax, indexing="ij")
    KR = np.sqrt(KX ** 2 + KY ** 2 + KZ ** 2)  # 0..~0.87
    ew = edge_px / box                          # soft-edge width in norm-freq units
    # smooth high-pass * smooth low-pass via raised-cosine ramps
    hp = np.clip((KR - lo) / ew + 0.5, 0.0, 1.0)
    lp = np.clip((hi - KR) / ew + 0.5, 0.0, 1.0)
    shell = (hp * lp).astype(np.float32)
    return np.fft.ifftshift(shell)              # -> corner-centered


def bandpass_real(vol, bp_corner):
    """Return real-space band-passed volume (bp_corner is corner-centered)."""
    return np.real(np.fft.ifftn(np.fft.fftn(vol) * bp_corner)).astype(np.float32)


def fftn_bp(vol, bp_corner):
    """Return the band-passed Fourier transform (corner-centered), for the CC path.

    complex64 (not the fftn default complex128): halves the memory/compute cost of
    the O(N^2) pairwise ccmatrix loop, which matters at N~500 particles x 96^3.
    """
    return (np.fft.fftn(vol) * bp_corner).astype(np.complex64)


# ------------------------------------------------------------- pose (prealign)
def dynamo_euler2matrix(tdrot, tilt, narot):
    """Exact transcription of dynamo_euler2matrix.m (Z-X-Z intrinsic, NOT Z-Y-Z).

    Angles in degrees. Verified against the installed Dynamo source at
    ~/Research/dynamo/matlab/src/dynamo_euler2matrix.m -- Dynamo's middle
    rotation axis is X, and getting this wrong (composing Rz@Ry@Rz) silently
    scrambles poses (average of "aligned" particles washes out to noise).
    """
    td, na, ti = np.radians(tdrot), np.radians(narot), np.radians(tilt)
    ctd, cna, cti = np.cos(td), np.cos(na), np.cos(ti)
    std, sna, sti = np.sin(td), np.sin(na), np.sin(ti)
    m = np.empty((3, 3))
    m[0, 0] = ctd * cna - std * cti * sna
    m[0, 1] = -cna * std - ctd * cti * sna
    m[0, 2] = sna * sti
    m[1, 0] = ctd * sna + cna * std * cti
    m[1, 1] = ctd * cna * cti - std * sna
    m[1, 2] = -cna * sti
    m[2, 0] = std * sti
    m[2, 1] = ctd * sti
    m[2, 2] = cti
    return m


def euler_zyz_to_matrix(narot, tilt, tdrot):
    """Rotation matrix for scipy affine_transform, from table eulers (tdrot,tilt,narot).

    Dynamo's prealign applies the INVERSE pose as -fliplr(euler) = [-narot,-tilt,-tdrot]
    fed through the SAME dynamo_euler2matrix formula (per its docstring: this triplet
    IS the inverse rotation in the same parameterization). dynamo_euler2matrix's
    physical convention is "m*p = rotated position of point p" (output = m @ input);
    scipy's affine_transform 'matrix' parameter instead maps output coords to input
    coords, i.e. wants the inverse mapping -- so we pass m.T (m is orthogonal).
    """
    m = dynamo_euler2matrix(-narot, -tilt, -tdrot)
    return m.T


def make_taper(box, decay=3.0):
    """Soft spherical taper (mirrors Dynamo's sphereSmooth in smoothShiftRot).

    Without this, affine_transform's constant-fill corners (unavoidable extrapolation
    when rotating a cube) contaminate the ensemble average / ccmatrix with a strong,
    non-structural bias -- verified by direct comparison against a known-good aligned
    average: the untapered result washes out to a near-uniform blob.
    """
    ax = np.arange(box) - (box / 2.0 - 0.5)
    Z, Y, X = np.meshgrid(ax, ax, ax, indexing="ij")
    R = np.sqrt(X ** 2 + Y ** 2 + Z ** 2)
    return np.clip((box / 2.0 - 1 - R) / decay + 0.5, 0.0, 1.0).astype(np.float32)


def apply_pose(vol, R, shift, taper=None):
    """Shift (Fourier phase shift) THEN rotate about center (per dynamo_shift_rot.m:
    'shifts and then rotates a volume, in this order'), then apply the soft spherical
    taper to suppress rotation corner artifacts."""
    box = vol.shape[0]
    z = np.fft.fftfreq(box)
    ph = np.exp(-2j * np.pi * (shift[0] * z[:, None, None] +
                               shift[1] * z[None, :, None] +
                               shift[2] * z[None, None, :]))
    vs = np.real(np.fft.ifftn(np.fft.fftn(vol) * ph)).astype(np.float32)
    cn = np.array(vol.shape) / 2.0 - 0.5
    vr = affine_transform(vs, R, offset=cn - R @ cn, order=3,
                          mode="constant", cval=float(np.min(vol)))
    return (vr * taper).astype(np.float32) if taper is not None else vr


def read_tbl(path):
    """Dynamo table -> dict tag -> (shift[3], euler[3]) (cols 4-6, 7-9)."""
    out = {}
    for line in open(path):
        p = line.split()
        if len(p) < 9:
            continue
        tag = int(float(p[0]))
        shift = np.array([float(p[3]), float(p[4]), float(p[5])])
        euler = np.array([float(p[6]), float(p[7]), float(p[8])])  # tdrot tilt narot
        out[tag] = (shift, euler)
    return out


# --------------------------------------------------------- missing-wedge model
def make_wedge_centered(box, tilt_min, tilt_max):
    """Binary Fourier sampling indicator (centered) for a single-axis tilt series.

    Tilt axis = Y. A frequency (kx,ky,kz) is sampled if the angle of its (kx,kz)
    projection from the kz (beam) axis falls within [tilt_min, tilt_max]. The
    unsampled double cone about kx is the missing wedge.
    """
    c = box // 2
    ax = np.arange(box) - c
    KZ, KY, KX = np.meshgrid(ax, ax, ax, indexing="ij")
    ang = np.degrees(np.arctan2(np.abs(KX), np.abs(KZ) + 1e-9))  # 0 along beam(kz)
    samp = (ang <= max(abs(tilt_min), abs(tilt_max))).astype(np.float32)
    samp[(KX == 0) & (KZ == 0)] = 1.0
    return samp


# ------------------------------------------------------------------ CC matrix
def masked_pearson_matrix(vecs):
    """Fast path: rows already masked/bandpassed; return N x N Pearson CC (diag=1)."""
    X = vecs - vecs.mean(axis=1, keepdims=True)
    n = np.linalg.norm(X, axis=1, keepdims=True)
    Xn = X / (n + 1e-12)
    CC = Xn @ Xn.T
    np.fill_diagonal(CC, 1.0)
    return CC


def pearson3d(a, b, m):
    """Masked real-space Pearson correlation over boolean mask m."""
    x = a[m]; y = b[m]
    x = x - x.mean(); y = y - y.mean()
    d = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / d) if d > 0 else np.nan


def _cc_row(i):
    """Worker: compute CC(i, j) for all j > i. Reads arrays from _CC_CTX (set by
    the parent before forking the pool -- fork shares them copy-on-write, so no
    per-task pickling of the 542 x 96^3 Fourier/wedge arrays)."""
    fbp, wedges, bp_corner, maskbool, N = (
        _CC_CTX["fbp"], _CC_CTX["wedges"], _CC_CTX["bp_corner"],
        _CC_CTX["maskbool"], _CC_CTX["N"])
    row = np.zeros(N, dtype=np.float32)
    for j in range(i + 1, N):
        W = bp_corner
        if wedges[i] is not None:
            W = wedges[i] * wedges[j] * bp_corner
        p1 = np.real(np.fft.ifftn(fbp[i] * W))
        p2 = np.real(np.fft.ifftn(fbp[j] * W))
        cc = pearson3d(p1, p2, maskbool)
        row[j] = -1.0 if np.isnan(cc) else cc
    return i, row


_CC_CTX = {}


def cc_matrix_wedged(fbp, wedges, bp_corner, maskbool, nproc=None):
    """Faithful O(N^2) wedge-compensated CC matrix, parallelized over rows.

    fbp[i]   = band-passed Fourier transform of particle i (corner-centered)
    wedges[i]= that particle's rotated wedge indicator (corner-centered) or None

    Mirrors Dynamo's own MATLAB ccmatrix step, which parallelizes the same
    pairwise loop over a parpool (16 workers in this project's runs).
    """
    import multiprocessing as mp

    N = len(fbp)
    CC = np.eye(N, dtype=np.float32)
    nproc = nproc or max(1, mp.cpu_count() - 4)
    _CC_CTX.update(fbp=fbp, wedges=wedges, bp_corner=bp_corner,
                   maskbool=maskbool, N=N)
    print(f"  ccmatrix: {N}x{N} pairwise wedge-compensated Pearson, "
          f"{nproc} processes", flush=True)
    done = 0
    with mp.get_context("fork").Pool(nproc) as pool:
        for i, row in pool.imap_unordered(_cc_row, range(N), chunksize=1):
            CC[i, i + 1:] = row[i + 1:]
            CC[i + 1:, i] = row[i + 1:]
            done += 1
            if done % 50 == 0:
                print(f"  ccmatrix rows done: {done}/{N}", flush=True)
    return CC


# ------------------------------------------------------------------ clustering
def eig_coords(CC, neig):
    """Top-`neig` eigenvectors of the CC matrix (largest eigenvalues) = coords."""
    neig = min(neig, CC.shape[0])
    vals, vecs = np.linalg.eigh(CC)          # ascending
    order = np.argsort(vals)[::-1][:neig]    # largest magnitude first
    return vecs[:, order]


def kmeans_labels(coords, k):
    from sklearn.cluster import KMeans
    km = KMeans(n_clusters=k, n_init=20, max_iter=500, random_state=42)
    return km.fit_predict(coords) + 1        # 1-based to match Dynamo convention


# ----------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="dir of subtomogram .mrc files")
    ap.add_argument("--labels", default=None,
                    help="labels.csv (file[,label]); else glob --data")
    ap.add_argument("--glob", default="subtomo_*.mrc", help="glob if no labels.csv")
    ap.add_argument("--mask", required=True, help="classification mask .mrc")
    ap.add_argument("--method", choices=["cc", "pca"], default="cc")
    ap.add_argument("--k", type=int, default=2, help="number of clusters")
    ap.add_argument("--ncomp", type=int, default=10, help="components for k-means")
    ap.add_argument("--neig", type=int, default=50, help="eigenvectors to extract")
    ap.add_argument("--band", type=float, nargs=2, default=[0.05, 0.45],
                    metavar=("LO", "HI"))
    ap.add_argument("--tbl", default=None, help="Dynamo .tbl poses (prealign)")
    ap.add_argument("--tilt-range", type=float, nargs=2, default=None,
                    metavar=("MIN", "MAX"),
                    help="enable true per-particle wedge (needs --tbl)")
    ap.add_argument("--apix", type=float, default=13.329)
    ap.add_argument("--nproc", type=int, default=None,
                    help="worker processes for the wedge-compensated ccmatrix "
                         "(default: cpu_count-4)")
    ap.add_argument("--out", required=True, help="output predictions CSV")
    ap.add_argument("--class-avgs-dir", default=None,
                    help="if set, write per-cluster mean-volume MRCs here")
    args = ap.parse_args()

    plist = load_particle_list(args.labels, args.data, args.glob)
    N = len(plist)
    if N == 0:
        sys.exit(f"No particles found under {args.data}")
    print(f"[dynamo_classify_py] {N} particles | method={args.method} | "
          f"k={args.k} | band={args.band}")

    mask = read_mrc(args.mask)
    box = mask.shape[0]
    maskbool = mask > 0.05
    print(f"  mask: {int(maskbool.sum())} active voxels in {box}^3 box")

    bp_corner = make_bandpass(box, args.band[0], args.band[1])

    poses = read_tbl(args.tbl) if args.tbl else None
    use_wedge = args.tilt_range is not None and poses is not None
    if args.tilt_range is not None and poses is None:
        print("  [warn] --tilt-range ignored without --tbl (all wedges identical "
              "-> common-wedge fast path)")

    # ---- prealign: load, apply poses, soft-mask, band-pass ----
    taper = make_taper(box) if poses is not None else None
    vols = []
    for idx, (name, path) in enumerate(plist):
        v = read_mrc(path)
        if poses is not None:
            tag = idx + 1
            if tag in poses:
                shift, euler = poses[tag]
                R = euler_zyz_to_matrix(euler[2], euler[1], euler[0])
                v = apply_pose(v, R, -shift, taper=taper)
        vols.append(v)
    print("  prealign done")

    if args.method == "pca":
        # ---- idiomatic sklearn path ----
        from sklearn.decomposition import PCA
        X = np.stack([bandpass_real(v, bp_corner)[maskbool] for v in vols])
        X = X - X.mean(axis=0)
        npc = min(args.neig, X.shape[0], X.shape[1])
        coords = PCA(n_components=npc, svd_solver="randomized",
                     random_state=0).fit_transform(X)
        coords = coords[:, :args.ncomp]
    else:
        # ---- faithful CC-matrix path ----
        if use_wedge:
            print("  ccmatrix: per-particle wedge-compensated (O(N^2), slower)")
            fbp = [fftn_bp(v, bp_corner) for v in vols]
            base_wedge = make_wedge_centered(box, *args.tilt_range)
            wedges = []
            for idx in range(N):
                tag = idx + 1
                if poses and tag in poses:
                    _, euler = poses[tag]
                    R = euler_zyz_to_matrix(euler[2], euler[1], euler[0])
                    cn = np.array(base_wedge.shape) / 2.0 - 0.5
                    w = affine_transform(base_wedge, R, offset=cn - R @ cn,
                                         order=1, mode="constant")
                    wedges.append(np.fft.ifftshift(w))
                else:
                    wedges.append(np.fft.ifftshift(base_wedge))
            CC = cc_matrix_wedged(fbp, wedges, bp_corner, maskbool, nproc=args.nproc)
        else:
            print("  ccmatrix: common-wedge fast path (normalized matrix multiply)")
            vecs = np.stack([bandpass_real(v, bp_corner)[maskbool] for v in vols])
            CC = masked_pearson_matrix(vecs)
        coords = eig_coords(CC, args.neig)[:, :args.ncomp]

    labels = kmeans_labels(coords, args.k)

    # ---- write predictions CSV (file,pred_label) ----
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "pred_label"])
        for (name, _), lab in zip(plist, labels):
            w.writerow([name, int(lab)])
    counts = {c: int((labels == c).sum()) for c in sorted(set(labels))}
    print(f"  wrote {args.out}  clusters: {counts}")

    # ---- optional per-cluster class averages ----
    if args.class_avgs_dir:
        os.makedirs(args.class_avgs_dir, exist_ok=True)
        for c in sorted(set(labels)):
            mean_v = np.mean([vols[i] for i in range(N) if labels[i] == c], axis=0)
            outp = os.path.join(args.class_avgs_dir, f"class{c}_avg.mrc")
            write_mrc(outp, mean_v, args.apix)
            print(f"  class {c} average -> {outp}")


if __name__ == "__main__":
    main()
