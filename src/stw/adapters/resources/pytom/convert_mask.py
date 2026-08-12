#!/usr/bin/env python
"""Convert an arbitrary MRC volume (e.g. an stw-resolved mask) into PyTom's
own .em format via a pytom_volume read/write round-trip.

Usage: convert_mask.py <src.mrc> <dst.em>
"""
import sys

from pytom.lib.pytom_volume import read


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    read(src).write(dst)


if __name__ == "__main__":
    main()
