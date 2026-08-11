#!/usr/bin/env python3
"""
pytom_classify_py.py -- a pure-Python/numpy port of PyTom's auto-focus classifier
(`auto_focus_classify_nofrm.py`), for the no-alignment (`-a`/noalign) mode this
benchmark always runs in.

WHY THIS EXISTS
---------------
PyTom's classifier depends on the compiled `pytom` package (SWIG C++ extensions,
MPI, optionally CUDA). This project's `_swig_frm` build is absent, so every run in
this benchmark already passes `-a` (noalign=True) -- see
`scripts/run/adapters/pytom.py`. That means the FRM-alignment code paths
(`frm_align`, anything gated by `align=True`) are dead code here and were NOT
ported. This script reimplements only the code paths actually exercised by this
project's configuration, in numpy/scipy, with **no `import pytom.*`** -- runnable
in any plain Python env with numpy/scipy/mrcfile. Follows the same pattern as
`packages/dynamo/python_port/dynamo_classify_py.py` (read that file's docstring
and README for the sibling-port precedent this mirrors).

WHAT THE REAL ALGORITHM ACTUALLY DOES (verified against the ground-truth source,
not paraphrased) -- read alongside `packages/PyTom/T4P/scripts/auto_focus_classify_nofrm.py`
and the compiled math it calls into (`~/Research/pytom/pytom/pytomc/libs/libtomc/src/tom/
FreqWeight.cpp`, `.../volume_fcn.cpp`, `basic/correlation.py`, `basic/normalise.py`):
---------------------------------------------------------------------------------
This project's configuration (`-a`, no `--sig`, no `--dispersion`, no `--noise`,
no `--external`, no `--resume`, `settings["fixed_frequency"]=True` hardcoded in the
CLI parser) collapses the general algorithm to something much simpler than the
~1076-line source suggests:

  * Particles are pre-aligned (Rotation=(0,0,0), Shift=(0,0,0) baked into the XML by
    `generate_particle_list.py`) and never move -- so `getTransformedVolume()` is
    always just the raw voxel data, and the wedge/rotation-dependent code always
    applies the SAME fixed wedge orientation to every particle and every reference.
  * `settings["fixed_frequency"]=True` is hardcoded in the CLI parser (not exposed
    as a flag) -- the gold-standard-FSC "resolution" computed each iteration inside
    `calculate_averages` is thrown away every time; every class always scores at the
    single fixed `-f` frequency. We never implement the FSC/`determine_resolution`
    machinery because of this.
  * `settings["dispersion"]` is never set by this project's adapter -- the small-
    class deletion / `split_topn_classes` machinery in `classify()` is dead code
    here (n=0 every iteration) and is NOT ported.
  * `sigma` (`--sig`) is never set -- the "only count density beyond sigma"
    branch in `calculate_difference_map` is skipped (`if sigma is None: pass`)
    and NOT ported.
  * With `align=False`, `calculate_difference_map`'s two returned difference maps
    (`dmap1`, `dmap2`) are numerically IDENTICAL (no register-back transform
    happens) -- so there is exactly one difference/focus map per class PAIR, used
    symmetrically. `calculate_scores`'s pre-voting pass (`score_noalign_proxy`) only
    ever writes back the particle's own (always-identity) shift/rotation and is a
    no-op for label assignment -- NOT ported (voting recomputes its own scores via
    `focus_score` anyway).
  * The reference/class-average pipeline (`paverage` + `calculate_averages`)
    divides the accumulated Fourier sum by the accumulated wedge-coverage sum
    per Fourier voxel. Because every particle carries the identical fixed wedge
    (identity rotation, always), that coverage sum is a hard step function (N
    inside the sampled region, 0 in the missing wedge) -- so the division reduces
    exactly to: **class average = fixed_wedge_filter(arithmetic_mean(members))**.
    This is the one place we take a well-justified shortcut (see "Known
    approximations" below) rather than re-deriving PyTom's exact 0/0 handling in
    `complexDiv`.

That leaves exactly four real numerical building blocks, each transcribed from its
C++ source (not guessed):

  1. **Fourier low-pass** (`tom::FreqWeight_Bandpass`, `FreqWeight.cpp:1350-1547`):
     radius = Euclidean distance (in PIXELS, not Nyquist fraction) from the DC
     bin on the centered/fftshift grid. weight=1 for radius<band; for
     band<radius<=band+3*smooth, weight=exp(-0.5*((radius-band)/smooth)**2)
     (Gaussian roll-off); else 0. `smooth=0` (used for every `focus_score`/
     `distance` call, which pass only `(vol, freq)`) means a perfectly hard
     cutoff -- no roll-off at all. `smooth=freq/10` (reference construction) or
     `box/40` (difference-map post-filter) gives the soft edge.
  2. **Fixed single-axis wedge** (`tom::FreqWeight_SingleAxisWedge`,
     `FreqWeight.cpp` `init_wedge_volume`, default `tiltAxis='Y'` per
     `SingleTiltWedge.__init__`): sampled (=1) iff |kz|~0 OR
     arctan(|kx|/|kz|) >= wedge_angle_rad -- a double-cone of half-angle
     `wedge_angle` (deg, default 30 = +/-60 deg tilt range) missing around the Z
     (beam) axis, constant along Y (the tilt axis). No smoothing (`SingleTiltWedge`
     default `smooth=0.0`).
  3. **mean0std1** (`basic/normalise.py`): `(v - v.mean()) / v.std()` over the
     WHOLE volume, unmasked.
  4. **nxcc / masked normalized cross-correlation** (`basic/correlation.py`
     `nxcc` -> `normaliseUnderMask`): weighted mean/std computed only over the
     mask footprint (`p = mask.sum()`; works identically for a soft/continuous
     mask, e.g. FM_easy's Gaussian-tapered cylinder, or a hard 0/1 mask, e.g.
     T4P's v2 cylinder -- both this project's real masks are used as-is).

The **difference/focus map** construction (`calculate_difference_map`, no-align
branch) reduces algebraically: with avg=(lv1+lv2)/2, `var1=(avg-lv1)**2` and
`var2=(avg-lv2)**2` are literally equal (`avg-lv1 = (lv2-lv1)/2 = -(avg-lv2)`), so
`std_map = sqrt(var1+var2) = |lv1-lv2|/sqrt(2)` -- i.e. the "difference map" IS
just the (focus-masked, mean0std1-normalized, lowpass-filtered) absolute
difference between the two class references, scaled by 1/sqrt(2), then
binarized at a percentile-style threshold (`limit()`, transcribed exactly from
`tom::limit`'s `<=`/`>=` replacement semantics in `volume_fcn.cpp:553-574`) and
lowpass-smoothed again.

**k-means++-style seeding** (`initialize()`): unseeded (`np.random.choice` with
no seed) -- this project's own memory confirms real PyTom's run-to-run swing is
~0.05-0.07 ARI from this alone (see `pytom-classifier-nondeterminism` memory /
`packages/PyTom/README.md`). This port reproduces that: no seeding by default.
An optional `--seed` flag (NOT part of the original algorithm/CLI) is added for
reproducible testing -- off by default to match real PyTom's behavior.

**Iterative classification** (`classify()`, no-align branch): for every unordered
pair of class labels, build one difference map from their current references;
score every particle against every reference via masked nxcc using the relevant
pair's difference map (`focus_score`); each pairwise comparison casts one vote for
whichever reference scored higher (ties go to the second name in the pair, per
the literal `if s1>s2: votes[c1] else: votes[c2]` -- transcribed as-is); the label
with the most votes wins (first-index-wins on a tie, per the literal
`if v>peak: peak=v; new_label=c` loop over an insertion-ordered dict, where only
pairwise WINNERS ever get a dict entry). Recompute class averages, repeat until
<0.5% of labels change or `niteration` iterations elapse.

OUTPUT
------
`file,pred_label` CSV (basename, 1-based cluster id) -- the exact contract of
`scripts/eval/score_synthetic.py`.

USAGE
-----
  conda run -n relion-5.0 python3 packages/PyTom/python_port/pytom_classify_py.py \\
      --labels <dir>/labels.csv --data <dir> --mask <focus_mask.mrc> \\
      --k 2 --frequency 20 --niter 15 --threshold 0.4 --wedge-angle 30 \\
      --out <preds.csv> [--seed 1]

See `packages/PyTom/python_port/README.md` for exact fidelity, known
approximations, and validated benchmark numbers (FM_easy ARI-vs-GT, T4P
agreement-vs-real-PyTom).
"""
import os
import csv
import sys
import glob
import argparse
import itertools

import numpy as np
import mrcfile


# --------------------------------------------------------------------------- I/O
def read_mrc(path):
    return np.asarray(mrcfile.open(path, permissive=True).data, dtype=np.float32)


def load_particle_list(labels, data, glob_pat):
    """Return [(basename, abspath), ...] -- prefer labels.csv order, else sorted glob.

    Matches `generate_particle_list.py`'s `sorted(glob.glob(...))` particle order
    (see this file's docstring on why that order matters for `initialize()`'s
    first, deterministic seed class).
    """
    if labels and os.path.exists(labels):
        names = [r["file"] for r in csv.DictReader(open(labels))]
        return [(n, os.path.join(data, n)) for n in names]
    files = sorted(glob.glob(os.path.join(data, glob_pat)))
    return [(os.path.basename(f), f) for f in files]


# ------------------------------------------------------------ Fourier primitives
def _centered_grid(box):
    ax = np.arange(box) - box // 2
    return np.meshgrid(ax, ax, ax, indexing="ij")  # (Z, Y, X)


def lowpass_mask_corner(box, band, smooth):
    """Corner-order (fftshift'ed-to-origin) low-pass weight, exact transcription
    of `tom::FreqWeight_Bandpass::init_bandpass_volume` (FreqWeight.cpp:1350-1460)
    with lowestFrequency=0 (the only case PyTom's `lowpassFilter()` ever uses).

    `band`/`smooth` are in PIXELS (radius on the centered frequency grid), NOT
    fractions of Nyquist -- matching the C++ `radius = sqrt(x^2+y^2+z^2)` in raw
    grid-index units.
    """
    Z, Y, X = _centered_grid(box)
    r = np.sqrt((Z ** 2 + Y ** 2 + X ** 2).astype(np.float64))
    m = np.zeros(r.shape, dtype=np.float32)
    m[r < band] = 1.0
    if smooth > 0:
        zone = (r > band) & (r <= band + 3 * smooth)
        dist = (r[zone] - band) / smooth
        m[zone] = np.exp(-0.5 * dist ** 2).astype(np.float32)
    return np.fft.ifftshift(m)


def wedge_mask_corner(box, wedge_angle_deg):
    """Corner-order fixed single-axis-wedge indicator, exact transcription of
    `tom::FreqWeight_SingleAxisWedge::init_wedge_volume` (FreqWeight.cpp, the
    cutoff_radius==0 branch) with `tiltAxis='Y'` (SingleTiltWedge's default) and
    identity rotation (this project's particles are always pre-aligned, i.e.
    Rotation=(0,0,0) -- `w.apply(v, rotation.invert())` never actually rotates
    the wedge). Array axis order (Z,Y,X) matches mrcfile's (nz,ny,nx) convention;
    missing region is a double-cone of half-angle `wedge_angle_deg` around Z
    (beam axis), constant along Y (tilt axis) -- see this file's module
    docstring for the full derivation from the C++ source.
    """
    Z, Y, X = _centered_grid(box)
    absZ = np.abs(Z).astype(np.float64)
    absX = np.abs(X).astype(np.float64)
    tan_angle = np.tan(np.radians(wedge_angle_deg))
    sampled = (absZ < 1e-4) | (tan_angle <= (absX / np.maximum(absZ, 1e-12)))
    return np.fft.ifftshift(sampled.astype(np.float32))


def fft_filter(vol, mask_corner):
    return np.real(np.fft.ifftn(np.fft.fftn(vol) * mask_corner)).astype(np.float32)


# ---------------------------------------------------------------- normalization
def mean0std1(v):
    """Whole-volume (unmasked) mean-0/std-1 normalization -- `basic/normalise.py`."""
    std = v.std()
    return (v - v.mean()) / (std if std > 1e-12 else 1.0)


def nxcc_masked(a, b, mask, eps=1e-12):
    """Masked normalized cross-correlation, transcribed from `basic/correlation.py`
    `nxcc` -> `normaliseUnderMask` -> `meanUnderMask`/`stdUnderMask`. Works for a
    continuous-valued (soft) mask exactly like a binary one -- `p=mask.sum()` is a
    weighted count either way, matching how PyTom's own real masks are used here
    (FM_easy's cylinder is Gaussian-tapered; T4P's v2 cylinder is hard 0/1)."""
    p = float(mask.sum())
    if p <= eps:
        return 0.0
    meanA = float((a * mask).sum()) / p
    meanB = float((b * mask).sum()) / p
    stdA = np.sqrt(max(float(((a ** 2) * mask).sum()) / p - meanA ** 2, eps))
    stdB = np.sqrt(max(float(((b ** 2) * mask).sum()) / p - meanB ** 2, eps))
    a_n = (a - meanA) / stdA
    b_n = (b - meanB) / stdB
    return float((a_n * b_n * mask).sum()) / p


# ------------------------------------------------------------------ difference map
def calculate_difference_map(ref1, ref2, freq, fmask, threshold):
    """No-align branch of `calculate_difference_map` (`auto_focus_classify_nofrm.py`
    lines 34-115), algebraically simplified (see module docstring): the STD map
    is exactly |lv1-lv2|/sqrt(2) once both references are lowpass-filtered
    (soft edge, smooth=freq/10), mean0std1-normalized, and focus-masked.
    """
    box = ref1.shape[0]
    lv1 = fft_filter(ref1, lowpass_mask_corner(box, freq, freq / 10.0))
    lv2 = fft_filter(ref2, lowpass_mask_corner(box, freq, freq / 10.0))
    lv1 = mean0std1(lv1) * fmask
    lv2 = mean0std1(lv2) * fmask
    std_map = np.abs(lv1 - lv2) / np.sqrt(2.0)
    std_map = std_map * fmask  # faithful no-op (already zero outside fmask)

    mv = float(std_map.mean())
    mx = float(std_map.max())
    thr = mv + (mx - mv) * threshold
    # tom::limit(std_map, thr, 0, thr, 1, True, True): v<=thr -> 0, v>thr -> 1
    binmap = np.where(std_map > thr, 1.0, 0.0).astype(np.float32)

    dmap = fft_filter(binmap, lowpass_mask_corner(box, box // 4, box / 40.0))
    # tom::limit(dmap, 0.5, 0, 1, 1, True, True): v<=0.5 -> 0, v>=1 -> 1
    dmap = np.where(dmap <= 0.5, 0.0, np.where(dmap >= 1.0, 1.0, dmap)).astype(np.float32)
    return dmap


# --------------------------------------------------------------- reference build
def make_reference(members, wedge_corner, freq):
    """class average = fixed_wedge_filter(arithmetic_mean(members)), then soft
    low-pass at `freq` (smooth=freq/10) -- see module docstring, "Known
    approximations" in the README, for why this replaces PyTom's Fourier-domain
    wedge-coverage division exactly under this project's always-identity-pose
    configuration."""
    raw_mean = members.mean(axis=0)
    box = raw_mean.shape[0]
    wedged = fft_filter(raw_mean, wedge_corner)
    return fft_filter(wedged, lowpass_mask_corner(box, freq, freq / 10.0))


# ----------------------------------------------------------------------- k-means++
def initialize(particles, prep, fmask, wedge_corner, hard_lp, k, freq, rng):
    """`initialize()` (auto_focus_classify_nofrm.py lines 758-816): first class =
    mean of the first `kn=N//K` particles in list order (a no-op after
    `pl.sortByScore()`, since every fresh particle has an identical default score
    -- Python's stable sort preserves the original glob/labels-csv order, see
    module docstring). Remaining classes: k-means++-style weighted sampling by
    CC-distance from existing centroids, drawing `kn` particles at once via
    `np.random.choice(..., p=distances)` (unseeded in the original; `rng` here is
    `np.random` itself by default, or a seeded `Generator`-like object if
    `--seed` was passed -- see CLI).
    """
    N = len(particles)
    kn = N // k

    refs = {0: make_reference(particles[:kn], wedge_corner, freq)}
    for c in range(1, k):
        distances = np.full(N, 4.0, dtype=np.float64)
        for _, ref in refs.items():
            ref_b = fft_filter(ref, hard_lp)
            d = np.array([2.0 * (1.0 - nxcc_masked(prep[i], ref_b, fmask))
                          for i in range(N)])
            distances = np.minimum(distances, d)
        distances = distances / distances.sum()
        idx = rng.choice(N, kn, replace=False, p=distances)
        refs[c] = make_reference(particles[idx], wedge_corner, freq)
    return refs


# ----------------------------------------------------------------------- main
def classify(particles, fmask, wedge_corner, k, freq, niter, threshold, rng,
             verbose=True):
    """`classify()`'s no-align branch, reduced to what this project's config
    actually exercises (`fixed_frequency=True`, no dispersion/noise/sigma/
    external/resume -- see module docstring)."""
    N = len(particles)
    box = particles.shape[1]
    hard_lp = wedge_corner * lowpass_mask_corner(box, freq, 0.0)  # wedge + hard cutoff
    prep = np.stack([fft_filter(v, hard_lp) for v in particles])  # "a" in focus_score

    refs = initialize(particles, prep, fmask, wedge_corner, hard_lp, k, freq, rng)
    class_labels = sorted(refs.keys())

    labels = np.full(N, -1, dtype=int)
    prev_labels = np.full(N, -999, dtype=int)

    for it in range(niter):
        if len(class_labels) < 2:
            break

        ref_b = {c: fft_filter(refs[c], hard_lp) for c in class_labels}
        dmaps = {}
        for c1, c2 in itertools.combinations(class_labels, 2):
            dmaps[(c1, c2)] = calculate_difference_map(refs[c1], refs[c2], freq,
                                                        fmask, threshold)

        new_labels = np.empty(N, dtype=int)
        for i in range(N):
            votes = {}
            for c1, c2 in itertools.combinations(class_labels, 2):
                dm = dmaps[(c1, c2)]
                s1 = nxcc_masked(prep[i], ref_b[c1], dm)
                s2 = nxcc_masked(prep[i], ref_b[c2], dm)
                if s1 > s2:
                    votes[c1] = votes.get(c1, 0) + 1
                else:
                    votes[c2] = votes.get(c2, 0) + 1
            peak = 0
            new_label = class_labels[0]
            for c, v in votes.items():
                if v > peak:
                    peak = v
                    new_label = c
            new_labels[i] = new_label

        counts = {c: int((new_labels == c).sum()) for c in class_labels}
        if verbose:
            print(f"  it{it}: {counts}", flush=True)

        new_refs = {}
        for c in class_labels:
            members = particles[new_labels == c]
            if len(members) == 0:
                print(f"  [warn] class {c} lost all members at it{it}; "
                      f"keeping stale reference (deviation from real PyTom, "
                      f"which would crash on `assert len(pp) > 3`)")
                new_refs[c] = refs[c]
            else:
                new_refs[c] = make_reference(members, wedge_corner, freq)
        refs = new_refs

        changed_frac = float(np.mean(new_labels != prev_labels))
        prev_labels = new_labels
        labels = new_labels
        if changed_frac < 0.005:
            if verbose:
                print(f"  converged at it{it} ({changed_frac:.4f} changed)")
            break

    return labels


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="dir of subtomogram .mrc files")
    ap.add_argument("--labels", default=None,
                    help="labels.csv (file[,label]); else glob --data")
    ap.add_argument("--glob", default="subtomo_*.mrc", help="glob if no labels.csv")
    ap.add_argument("--mask", required=True,
                    help="focus/classification mask .mrc (plays both the -c "
                         "focus-mask and -m alignment-mask roles of the real "
                         "CLI, matching every real run this project makes -- "
                         "the alignment mask is unused anyway once -a/noalign "
                         "is set, since the FRM-align branch it's used in never "
                         "runs)")
    ap.add_argument("--k", type=int, default=2, help="-k: number of clusters")
    ap.add_argument("--frequency", type=int, default=20,
                    help="-f: max scoring/lowpass frequency, in pixels")
    ap.add_argument("--niter", type=int, default=15, help="-i: iterations")
    ap.add_argument("--threshold", type=float, default=0.4,
                    help="-t: STD-map threshold for the focus/difference mask")
    ap.add_argument("--wedge-angle", type=float, default=30.0,
                    help="missing-wedge half-angle in degrees (matches "
                         "generate_particle_list.py's --wedge_angle default; "
                         "30 = +/-60 deg tilt range)")
    ap.add_argument("--seed", type=int, default=None,
                    help="NOT part of the original algorithm/CLI -- real PyTom's "
                         "initialize() calls np.random.choice() unseeded (see "
                         "pytom-classifier-nondeterminism memory: ~0.05-0.07 ARI "
                         "run-to-run swing). Off by default to match that "
                         "behavior; pass a value for reproducible testing.")
    ap.add_argument("--out", required=True, help="output predictions CSV")
    ap.add_argument("--class-avgs-dir", default=None,
                    help="if set, write per-cluster mean-volume MRCs here")
    ap.add_argument("--apix", type=float, default=None)
    args = ap.parse_args()

    plist = load_particle_list(args.labels, args.data, args.glob)
    N = len(plist)
    if N == 0:
        sys.exit(f"No particles found under {args.data}")
    print(f"[pytom_classify_py] {N} particles | k={args.k} | freq={args.frequency} | "
          f"niter={args.niter} | threshold={args.threshold} | "
          f"wedge_angle={args.wedge_angle} | seed={args.seed}")

    mask = read_mrc(args.mask)
    box = mask.shape[0]
    particles = np.stack([read_mrc(p) for _, p in plist]).astype(np.float32)
    if particles.shape[1] != box:
        sys.exit(f"Mask box {box} != particle box {particles.shape[1]}")

    wedge_corner = wedge_mask_corner(box, args.wedge_angle)
    rng = np.random.default_rng(args.seed) if args.seed is not None else np.random

    labels = classify(particles, mask, wedge_corner, args.k, args.frequency,
                      args.niter, args.threshold, rng)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "pred_label"])
        for (name, _), lab in zip(plist, labels):
            w.writerow([name, int(lab) + 1])  # 1-based, matches sibling ports
    counts = {int(c) + 1: int((labels == c).sum()) for c in sorted(set(labels))}
    print(f"  wrote {args.out}  clusters: {counts}")

    if args.class_avgs_dir:
        os.makedirs(args.class_avgs_dir, exist_ok=True)
        for c in sorted(set(labels)):
            mean_v = particles[labels == c].mean(axis=0)
            outp = os.path.join(args.class_avgs_dir, f"class{c + 1}_avg.mrc")
            with mrcfile.new(outp, overwrite=True) as m:
                m.set_data(mean_v.astype(np.float32))
                if args.apix:
                    m.voxel_size = args.apix
            print(f"  class {c + 1} average -> {outp}")


if __name__ == "__main__":
    main()
