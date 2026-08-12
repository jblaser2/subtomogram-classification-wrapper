#!/usr/bin/env python
"""Write a particle_parms_NN.json with identity orientations.

The subvolumes in this dataset are already aligned at Euler angles (0,0,0),
so no subtomogram alignment search is performed. This script fabricates the
metadata file that e2spt_average.py / e2spt_pcasplit.py expect, giving every
particle an identity xform.align3d (no rotation, no shift) and score 0.

Usage:
    make_identity_parms.py <input.lst> <output_parms.json>
"""
import sys
from EMAN2 import LSXFile, js_open_dict, Transform


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    lst_path = sys.argv[1]
    out_json = sys.argv[2]

    lst = LSXFile(lst_path, True)
    n = lst.n
    lst.close()

    # Identity transform: particles are already in the common (0,0,0) frame.
    ident = Transform()

    js = js_open_dict(out_json)
    for i in range(n):
        key = "('{}', {})".format(lst_path, i)
        js.setval(key, {
            "xform.align3d": ident,
            "score": 0.0,
            "coverage": 1.0,
        }, True)
    js.sync()
    js.close()
    print("Wrote {} identity entries to {}".format(n, out_json))


if __name__ == "__main__":
    main()
