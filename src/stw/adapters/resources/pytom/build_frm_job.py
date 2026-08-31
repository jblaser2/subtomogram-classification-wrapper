#!/usr/bin/env python3
"""
build_frm_job.py

Builds a real PyTom FRMJob XML from a particle list XML, a reference density,
and an alignment mask -- pure PyTom object construction (Reference/Mask/
SampleInformation/FRMJob.toXMLFile()), never hand-rolled XML.

A compatibility shim is required before importing pytom.bin.FRMAlignment:
that module (unlike the rest of PyTom's basic.* API) still does
`import pytom_mpi` -- a pre-refactor flat module name only resolvable today
via pytom.lib.pytom_mpi. Aliasing it into sys.modules first avoids needing
to patch PyTom's own source (same real cross-version break class as the
classification adapter's Score shim, see resources/pytom/README.md).

Usage:
    python build_frm_job.py \
        --particle_list particle_list.xml --reference ref.em --mask mask.em \
        --pixel_size 5.0 --peak_offset 6 --bw_low 4 --bw_high 8 --freq 6 \
        --max_iter 4 --destination dest_dir --output frm_job.xml
"""
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Build a PyTom FRMJob XML.")
    parser.add_argument("--particle_list", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--mask", required=True)
    parser.add_argument("--pixel_size", type=float, required=True)
    parser.add_argument("--peak_offset", type=int, required=True)
    parser.add_argument("--bw_low", type=int, required=True)
    parser.add_argument("--bw_high", type=int, required=True)
    parser.add_argument("--freq", type=int, required=True)
    parser.add_argument("--max_iter", type=int, required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    import pytom.lib.pytom_mpi as pytom_mpi

    sys.modules["pytom_mpi"] = pytom_mpi

    from pytom.basic.structures import Mask, ParticleList, Reference, SampleInformation
    from pytom.bin.FRMAlignment import FRMJob
    from pytom.lib.pytom_volume import read as read_vol

    pl = ParticleList()
    pl.fromXMLFile(args.particle_list)

    # particleDiameter is used by PyTom only for a display/sanity check, not the
    # search itself -- derive it from the mask's own box rather than asking the
    # caller for a value that has no other use in this pipeline.
    diameter = read_vol(args.mask).size_x() * args.pixel_size

    os.makedirs(args.destination, exist_ok=True)

    job = FRMJob(
        pl=pl,
        ref=Reference(args.reference),
        mask=Mask(args.mask),
        peak_offset=args.peak_offset,
        sample_info=SampleInformation(pixelSize=args.pixel_size, particleDiameter=diameter),
        bw_range=[args.bw_low, args.bw_high],
        freq=args.freq,
        dest=args.destination,
        max_iter=args.max_iter,
        binning=1,
    )
    job.toXMLFile(args.output)
    print(f"wrote {args.output} ({len(pl)} particles, {args.max_iter} max iterations)")


if __name__ == "__main__":
    main()
