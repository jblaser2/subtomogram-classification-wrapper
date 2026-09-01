"""
Blind, label-free "auto" mask: a soft sphere over the density envelope of the
global average — no ground truth or class assignments needed. Ported from the
`--mode global` path of STA's `make_diff_sphere_mask.py`, which was the
oracle-free half of that script (the other half required GT labels and is
deliberately not carried into this tool — a general user has no labels yet).
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import center_of_mass, gaussian_filter

from stw.averaging import global_average
from stw.masks.primitives import Shape, Vec3, box_center, build_sphere
from stw.spec import ParticleSet


def _znorm(v: np.ndarray) -> np.ndarray:
    s = v.std()
    return (v - v.mean()) / s if s > 0 else v - v.mean()


def auto_sphere_mask(
    particles: ParticleSet,
    *,
    center_mode: str = "box",
    percentile: float = 90.0,
    smooth: float = 2.0,
    enclose: float = 0.90,
    pad: float = 4.0,
    edge: float = 3.0,
    avg: np.ndarray | None = None,
) -> tuple[np.ndarray, Vec3, float]:
    """Build a blind sphere mask centered on (or near) the box center, sized to
    enclose most of the particle's density envelope.

    `center_mode="box"` assumes aligned input (the common case here); `"com"`
    centers on the envelope's center of mass instead, useful for `rough`-aligned
    input where a box-centered mask risks clipping real signal.

    `avg`: pass an already-computed global average to skip re-streaming every
    particle off disk (e.g. a caller that already has one cached).
    """
    if avg is None:
        avg = global_average(particles.particle_dir, list(particles.files))
    box = avg.shape[0]
    shape: Shape = (box, box, box)
    display = _znorm(avg)
    envelope = gaussian_filter(np.abs(display - np.median(display)), smooth)

    thr = np.percentile(envelope, percentile)
    blob = envelope >= thr

    center: Vec3
    if center_mode == "com":
        center = tuple(center_of_mass(envelope * blob))  # type: ignore[assignment]
    else:
        center = box_center(shape)

    gz, gy, gx = np.mgrid[0:box, 0:box, 0:box]
    d = np.sqrt((gz - center[0]) ** 2 + (gy - center[1]) ** 2 + (gx - center[2]) ** 2)
    w = (envelope * blob).ravel()
    order = np.argsort(d.ravel())
    cw = np.cumsum(w[order])
    cutoff = enclose * cw[-1] if cw[-1] > 0 else 0.0
    radius = float(d.ravel()[order][np.searchsorted(cw, cutoff)]) + pad

    max_r = box / 2.0 - edge
    radius = min(radius, max_r)

    mask = build_sphere(shape, center, radius, edge)
    return mask, center, radius
