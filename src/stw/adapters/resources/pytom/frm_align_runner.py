#!/usr/bin/env python3
"""
frm_align_runner.py

Runs PyTom's own real pytom/bin/FRMAlignment.py under mpirun -- never
reimplements FRM alignment, just works around a real cross-version break:
FRMAlignment.py does `import pytom_mpi` and (deep inside its own
`retrieve_res_vols`/`create_average`) `from pytom_volume import ...`
(pre-refactor flat module names), which only resolve today via
pytom.lib.pytom_mpi/pytom.lib.pytom_volume/pytom.lib.pytom_numpy/
pytom.lib.pytom_fftplan/pytom.lib.pytom_freqweight. Aliasing all five into
sys.modules before running FRMAlignment's own __main__ block via runpy
avoids needing to patch PyTom's own source.

Usage (must run under mpirun/mpiexec, not directly -- FRMWorker requires
at least 2 ranks, rank 0 coordinates, the rest do the actual FRM search):
    mpiexec -np N python frm_align_runner.py -j job.xml -v
"""
import os
import runpy
import sys

import pytom.lib.pytom_fftplan as pytom_fftplan
import pytom.lib.pytom_freqweight as pytom_freqweight
import pytom.lib.pytom_mpi as pytom_mpi
import pytom.lib.pytom_numpy as pytom_numpy
import pytom.lib.pytom_volume as pytom_volume

sys.modules["pytom_mpi"] = pytom_mpi
sys.modules["pytom_volume"] = pytom_volume
sys.modules["pytom_numpy"] = pytom_numpy
sys.modules["pytom_fftplan"] = pytom_fftplan
sys.modules["pytom_freqweight"] = pytom_freqweight

if __name__ == "__main__":
    import pytom

    frm_alignment_path = os.path.join(os.path.dirname(pytom.__file__), "bin", "FRMAlignment.py")
    sys.argv[0] = frm_alignment_path
    runpy.run_path(frm_alignment_path, run_name="__main__")
