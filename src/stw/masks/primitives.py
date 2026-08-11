"""
Generic, dataset-agnostic mask-shape builders.

`build_sphere` is a direct port of the helper in STA's
`scripts/data_prep/make_diff_sphere_mask.py`. `build_cylinder` is new — no
generic, parametrized cylinder-mask builder existed anywhere in that codebase
(cylinder masks there were one-off, unargparsed, per-dataset scripts) — but it
shares the same soft cosine-edge falloff so the two mask kinds behave
consistently for every downstream package.
"""
from __future__ import annotations

import numpy as np

Shape = tuple[int, int, int]
Vec3 = tuple[float, float, float]

_AXIS_INDEX = {"z": 0, "y": 1, "x": 2}


def cosine_edge(distance: np.ndarray, radius: float, edge: float) -> np.ndarray:
    """1.0 inside `radius`, 0.0 beyond `radius + edge`, cosine ramp between."""
    mask = np.ones_like(distance, dtype=np.float32)
    mask[distance > radius + edge] = 0.0
    ramp = (distance > radius) & (distance <= radius + edge)
    if edge > 0:
        mask[ramp] = 0.5 * (1 + np.cos(np.pi * (distance[ramp] - radius) / edge))
    else:
        mask[distance > radius] = 0.0
    return mask


def build_sphere(shape: Shape, center: Vec3, radius: float, edge: float = 3.0) -> np.ndarray:
    """A soft-edged sphere mask. `center` and coordinates are (z, y, x) voxels."""
    gz, gy, gx = np.mgrid[0 : shape[0], 0 : shape[1], 0 : shape[2]]
    d = np.sqrt((gz - center[0]) ** 2 + (gy - center[1]) ** 2 + (gx - center[2]) ** 2)
    return cosine_edge(d, radius, edge)


def build_cylinder(
    shape: Shape,
    center: Vec3,
    radius: float,
    half_height: float,
    axis: str = "z",
    edge: float = 3.0,
) -> np.ndarray:
    """A soft-edged cylinder mask: a disc of `radius` extruded +/- `half_height`
    along `axis`. Both the radial and axial edges get the same cosine falloff,
    combined by multiplication so the corners (where both ramps are active)
    still taper smoothly rather than getting a hard corner.
    """
    if axis not in _AXIS_INDEX:
        raise ValueError(f"axis must be one of x/y/z, got {axis!r}")
    axis_idx = _AXIS_INDEX[axis]
    radial_idx = [i for i in range(3) if i != axis_idx]

    gz, gy, gx = np.mgrid[0 : shape[0], 0 : shape[1], 0 : shape[2]]
    coords = [gz, gy, gx]

    radial_d = np.sqrt(
        (coords[radial_idx[0]] - center[radial_idx[0]]) ** 2
        + (coords[radial_idx[1]] - center[radial_idx[1]]) ** 2
    )
    axial_d = np.abs(coords[axis_idx] - center[axis_idx])

    radial_mask = cosine_edge(radial_d, radius, edge)
    axial_mask = cosine_edge(axial_d, half_height, edge)
    return (radial_mask * axial_mask).astype(np.float32)


def box_center(shape: Shape) -> Vec3:
    return (shape[0] / 2.0 - 0.5, shape[1] / 2.0 - 0.5, shape[2] / 2.0 - 0.5)
