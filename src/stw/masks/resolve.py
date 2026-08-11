"""
Resolve a MaskSpec (what the user asked for) against a ParticleSet into ONE
concrete mask MRC on disk, cached by content hash so every package in a run
shares the identical mask file (and so re-running the same config is free).
"""
from __future__ import annotations

from pathlib import Path

from stw.io.mrc import load_mrc, save_mrc
from stw.masks.auto import auto_sphere_mask
from stw.masks.primitives import box_center, build_cylinder, build_sphere
from stw.masks.qc import mask_summary, render_mask_overlay
from stw.spec import MaskKind, MaskSpec, ParticleSet


def resolve_mask(
    mask_spec: MaskSpec, particles: ParticleSet, cache_dir: str | Path, *, render_qc: bool = True
) -> Path | None:
    """Returns the path to a cached mask MRC, or None for kind=none.

    A sibling `<name>.summary.json`-worthy dict is returned by `mask_summary()`
    for callers that want it (the orchestrator logs it into provenance); a QC
    overlay PNG is written alongside the mask when `render_qc=True` and the
    `viz` extra is available.
    """
    if mask_spec.kind == MaskKind.NONE:
        return None

    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    key = mask_spec.cache_key()
    mask_path = cache / f"mask_{key}.mrc"
    if mask_path.exists():
        return mask_path

    box = particles.box
    shape = (box, box, box)

    if mask_spec.kind == MaskKind.FILE:
        assert mask_spec.path is not None
        mask = load_mrc(mask_spec.path)
    elif mask_spec.kind == MaskKind.SPHERE:
        center = mask_spec.center or box_center(shape)
        assert mask_spec.radius is not None
        mask = build_sphere(shape, center, mask_spec.radius, mask_spec.edge)
    elif mask_spec.kind == MaskKind.CYLINDER:
        center = mask_spec.center or box_center(shape)
        assert mask_spec.radius is not None and mask_spec.half_height is not None
        mask = build_cylinder(
            shape, center, mask_spec.radius, mask_spec.half_height, mask_spec.axis, mask_spec.edge
        )
    elif mask_spec.kind == MaskKind.AUTO:
        mask, _center, _radius = auto_sphere_mask(particles)
    else:  # pragma: no cover - exhaustive above
        raise ValueError(f"unknown mask kind: {mask_spec.kind}")

    save_mrc(mask_path, mask, pixel_size=particles.pixel_size)

    if render_qc:
        try:
            from stw.averaging import global_average

            avg = global_average(particles.particle_dir, list(particles.files))
            render_mask_overlay(
                avg,
                mask,
                mask_path.with_suffix(".overlay.png"),
                title=f"{mask_spec.kind} mask, {mask_summary(mask)['box_fraction']*100:.1f}% of box",
            )
        except ImportError:
            pass  # matplotlib (the `viz` extra) not installed — QC overlay is optional

    return mask_path
