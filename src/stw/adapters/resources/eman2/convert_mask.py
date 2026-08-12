#!/usr/bin/env python
"""Convert an arbitrary MRC volume (e.g. an stw-resolved mask) into EMAN2's
own HDF format via an EMData round-trip.

Usage: convert_mask.py <src.mrc> <dst.hdf>
"""
import sys

from EMAN2 import EMData


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    EMData(src).write_image(dst, 0)


if __name__ == "__main__":
    main()
