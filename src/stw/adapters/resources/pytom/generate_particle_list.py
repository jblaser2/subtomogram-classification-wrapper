#!/usr/bin/env python3
"""
generate_particle_list.py

Generate a PyTom ParticleList XML from pre-aligned T4P subtomograms.

Particles are assumed to be pre-aligned: the alignment transformation has already
been applied to the MRC volumes themselves. Rotation=(0,0,0) and Shift=(0,0,0)
are written into the XML accordingly.

The --wedge_angle is the MISSING wedge half-angle (the gap from 90° to the max
tilt angle). For a ±60° tilt range, data is missing from 60°-90° on each side:
missing wedge half-angle = 90° - 60° = 30° (the default).

Usage:
    python generate_particle_list.py \\
        --input_dir /path/to/subtomos_mrc \\
        --output particle_list.xml \\
        [--wedge_angle 30] \\
        [--pytom_dir /path/to/pytom]
"""

import os
import sys
import argparse
import glob


def main():
    parser = argparse.ArgumentParser(
        description="Generate a PyTom ParticleList XML from pre-aligned MRC subtomograms.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument(
        '--input_dir', required=True,
        help='Directory containing .mrc subtomogram files')
    parser.add_argument(
        '--output', required=True,
        help='Output XML filename (e.g. particle_list.xml)')
    parser.add_argument(
        '--pattern', default='*.mrc',
        # stw addition: the original hardcoded '*.mrc' silently ingests every MRC in
        # input_dir, including files that don't belong to this particle set (e.g. a
        # leftover mask copy) if the caller's actual glob is narrower. Defaults to the
        # same '*.mrc' for backward compatibility with any existing caller.
        help='Glob pattern within --input_dir (default: *.mrc)')
    parser.add_argument(
        '--wedge_angle', type=float, default=30.0,
        help='Missing wedge half-angle in degrees. '
             'Default 30 = ±60 deg tilt range. '
             'Formula: missing_wedge_angle = 90 - max_tilt_angle')
    parser.add_argument(
        '--pytom_dir', default=None,
        help='Path to PyTom repo root if not installed on PYTHONPATH '
             '(e.g. /home/user/Research/pytom)')
    args = parser.parse_args()

    if args.pytom_dir:
        sys.path.insert(0, os.path.abspath(args.pytom_dir))

    try:
        from pytom.basic.structures import ParticleList, Particle, SingleTiltWedge
    except ImportError as e:
        print(f"ERROR: Cannot import PyTom: {e}")
        print("Make sure PyTom is installed or supply --pytom_dir.")
        sys.exit(1)

    input_dir = os.path.abspath(args.input_dir)
    mrc_files = sorted(glob.glob(os.path.join(input_dir, args.pattern)))

    if not mrc_files:
        print(f"ERROR: No .mrc files found in: {input_dir}")
        sys.exit(1)

    print(f"Found {len(mrc_files)} MRC files in: {input_dir}")
    print(f"Building ParticleList...")

    wedge = SingleTiltWedge(args.wedge_angle)
    pl = ParticleList()

    for fpath in mrc_files:
        p = Particle(fpath)
        pl.append(p)

    pl.setWedgeAllParticles(wedge)
    pl.toXMLFile(args.output)

    print(f"\nDone.")
    print(f"  Output XML      : {args.output}")
    print(f"  Total particles : {len(pl)}")
    print(f"  Wedge angle     : {args.wedge_angle} deg  "
          f"(assumes +/-{90 - args.wedge_angle:.0f} deg tilt range)")
    print(f"  Rotation        : (0, 0, 0) -- pre-aligned volumes")
    print(f"  Shift           : (0, 0, 0) -- pre-aligned volumes")


if __name__ == '__main__':
    main()
