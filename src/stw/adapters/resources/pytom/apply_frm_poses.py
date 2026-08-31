#!/usr/bin/env python3
"""
apply_frm_poses.py

Reads a PyTom FRMAlignment output ParticleList (the highest-numbered
aligned_pl_iterN.xml) and writes each particle's own real
getTransformedVolume() (PyTom's cubic-spline pose application via
transformSpline -- never reimplemented) as a new MRC in an output
directory, plus a CSV of the recovered per-particle poses/scores for
provenance (FRMAlignment.py itself only ever averages the aligned stack;
it never writes individual aligned copies back out).

Usage:
    python apply_frm_poses.py --particle_list aligned_pl_iter3.xml \
        --output_dir aligned_particles/ --poses_csv poses.csv --pixel_size 5.0
"""
import argparse
import csv
from pathlib import Path

import mrcfile
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--particle_list", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--poses_csv", required=True)
    parser.add_argument("--pixel_size", type=float, required=True)
    args = parser.parse_args()

    from pytom.basic.structures import ParticleList
    from pytom.lib.pytom_numpy import vol2npy

    pl = ParticleList()
    pl.fromXMLFile(args.particle_list)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for p in pl:
        vol = p.getTransformedVolume()
        arr = np.array(vol2npy(vol), copy=True).astype(np.float32)
        fname = Path(p.getFilename()).name
        with mrcfile.new(out_dir / fname, overwrite=True) as m:
            m.set_data(arr)
            m.voxel_size = args.pixel_size
        shift = p.getShift()
        rot = p.getRotation()
        rows.append({
            "particle": fname,
            "shift_x": shift[0], "shift_y": shift[1], "shift_z": shift[2],
            "rot_z1": rot[0], "rot_x": rot[1], "rot_z2": rot[2],
            "score": p.getScoreValue(),
        })

    with open(args.poses_csv, "w", newline="") as f:
        fieldnames = list(rows[0].keys()) if rows else [
            "particle", "shift_x", "shift_y", "shift_z", "rot_z1", "rot_x", "rot_z2", "score",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    if not rows:
        raise SystemExit(f"no particles found in {args.particle_list}")
    print(f"wrote {len(rows)} aligned particles to {out_dir}")


if __name__ == "__main__":
    main()
