#!/usr/bin/env python3
"""
Stack 672 MRC particles → particles.hdf + ptcls.lst + initial_ref.hdf
Run from: /home/ejl62/src/eman2_project/
"""
from EMAN2 import *
import glob, os

PARTICLES_DIR = os.environ.get("EMAN2_PARTICLES_DIR", "/home/ejl62/src/particles")
APIX = float(os.environ.get("EMAN2_APIX", "13.328"))
GLOB_PATTERN = os.environ.get("EMAN2_GLOB", "aligned_tom*.mrc")

mrc_files = sorted(glob.glob(os.path.join(PARTICLES_DIR, GLOB_PATTERN)))
if not mrc_files:
    print(f"ERROR: No aligned_tom*.mrc files found in {PARTICLES_DIR}")
    sys.exit(1)
print(f"Found {len(mrc_files)} MRC files")

# Stack into particles.hdf
out_hdf = "particles.hdf"
if os.path.exists(out_hdf):
    os.remove(out_hdf)

for i, f in enumerate(mrc_files):
    e = EMData(f)
    e["apix_x"] = e["apix_y"] = e["apix_z"] = APIX
    e["source_path"] = f
    e["source_n"] = i
    e.write_image(out_hdf, i)
    if (i + 1) % 100 == 0:
        print(f"  {i+1}/{len(mrc_files)}")

print(f"Wrote {len(mrc_files)} particles → {out_hdf}")

# Create LST particle list
lst_path = "ptcls.lst"
lst = LSXFile(lst_path, False)
for i in range(len(mrc_files)):
    lst.write(-1, i, out_hdf)
lst.close()
print(f"Wrote particle list → {lst_path}")

# Compute simple average as initial reference
print("Computing initial reference (simple average)...")
avgr = Averagers.get("mean")
for i in range(len(mrc_files)):
    avgr.add_image(EMData(out_hdf, i))
avg = avgr.finish()
avg["apix_x"] = avg["apix_y"] = avg["apix_z"] = APIX
avg.write_image("initial_ref.hdf", 0)
print("Wrote initial_ref.hdf")
print("\nData ingestion complete.")
