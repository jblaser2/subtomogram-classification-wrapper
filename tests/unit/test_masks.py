import numpy as np
import pytest

from stw.masks.primitives import box_center, build_cylinder, build_sphere, cosine_edge
from stw.masks.stats import mask_active_frac


def test_sphere_is_analytically_correct_volume():
    shape = (41, 41, 41)
    center = (20, 20, 20)
    radius = 10.0
    mask = build_sphere(shape, center, radius, edge=0.0)
    active = (mask > 0.5).sum()
    expected = (4 / 3) * np.pi * radius**3
    assert abs(active - expected) / expected < 0.05


def test_sphere_edge_is_monotonic_falloff():
    shape = (41, 41, 41)
    center = box_center(shape)
    mask = build_sphere(shape, center, radius=8.0, edge=4.0)
    line = mask[int(center[0]), int(center[1]), int(center[2]) :]
    diffs = np.diff(line)
    assert np.all(diffs <= 1e-6)  # monotonically non-increasing outward


def test_sphere_contained_in_box():
    shape = (20, 20, 20)
    mask = build_sphere(shape, box_center(shape), radius=100.0, edge=1.0)
    assert mask.shape == shape
    assert np.all(mask >= 0.0) and np.all(mask <= 1.0)


def test_cylinder_is_analytically_correct_volume():
    shape = (41, 41, 41)
    center = (20, 20, 20)
    radius, half_height = 8.0, 6.0
    mask = build_cylinder(shape, center, radius, half_height, axis="z", edge=0.0)
    active = (mask > 0.5).sum()
    expected = np.pi * radius**2 * (2 * half_height)
    # Inclusive integer boundaries (distance <= radius/half_height) bias the
    # discrete count high relative to the continuum formula; the bias scales
    # with 1/(2*half_height), so a modest half_height needs a looser tolerance
    # than the sphere test above.
    assert abs(active - expected) / expected < 0.15


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_cylinder_respects_axis(axis):
    shape = (31, 31, 31)
    center = box_center(shape)
    mask = build_cylinder(shape, center, radius=5.0, half_height=3.0, axis=axis, edge=1.0)
    assert mask.shape == shape
    assert mask.max() > 0.9


def test_cylinder_rejects_bad_axis():
    with pytest.raises(ValueError):
        build_cylinder((10, 10, 10), (5, 5, 5), 3.0, 3.0, axis="w")


def test_cosine_edge_bounds():
    d = np.linspace(0, 20, 100)
    edge = cosine_edge(d, radius=10.0, edge=5.0)
    assert edge.min() >= 0.0 and edge.max() <= 1.0
    assert np.all(edge[d <= 10.0] == 1.0)
    assert np.all(edge[d > 15.0] == 0.0)


def test_mask_active_frac(tmp_path):
    import mrcfile

    mask = np.zeros((10, 10, 10), dtype=np.float32)
    mask[:5] = 1.0
    path = tmp_path / "mask.mrc"
    with mrcfile.new(path, overwrite=True) as m:
        m.set_data(mask)
    assert mask_active_frac(path) == pytest.approx(0.5)
