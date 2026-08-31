from __future__ import annotations

from pathlib import Path

import typer

from stw.spec import MaskKind, MaskSpec, ParticleSet


def build_mask(
    particles: Path = typer.Option(..., help="Directory of particle MRCs"),
    pattern: str = typer.Option("*.mrc", help="Glob pattern for particle files"),
    kind: MaskKind = typer.Option(MaskKind.AUTO, help="none | sphere | cylinder | file | auto"),
    radius: float = typer.Option(None, help="sphere/cylinder radius, voxels"),
    half_height: float = typer.Option(None, help="cylinder half-height, voxels"),
    axis: str = typer.Option("z", help="cylinder axis: x | y | z"),
    edge: float = typer.Option(3.0, help="soft cosine edge width, voxels"),
    out: Path = typer.Option(Path("mask.mrc"), help="Output mask MRC path"),
) -> None:
    """Build (and QC-render) a mask against a real particle set, standalone —
    useful for previewing a mask before committing to a full `stw run`."""
    ps = ParticleSet.discover(particles, pattern)
    spec = MaskSpec(kind=kind, radius=radius, half_height=half_height, axis=axis, edge=edge)

    from stw.masks.resolve import resolve_mask

    # ps.fingerprint(): the same out.parent/.stw_mask_cache dir could otherwise be reused
    # across two different `stw mask` calls for different datasets (same reasoning as
    # orchestrator.run_config()'s cache_dir/cache_root).
    mask_path = resolve_mask(spec, ps, out.parent / ".stw_mask_cache" / ps.fingerprint())
    if mask_path is None:
        typer.echo("mask kind=none — nothing to write")
        raise typer.Exit(code=0)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(mask_path.read_bytes())
    overlay = mask_path.with_suffix(".overlay.png")
    typer.echo(f"wrote {out}")
    if overlay.exists():
        typer.echo(f"QC overlay: {overlay}")
