#!/usr/bin/env python3
"""
Patch e2spt_pcasplit.py in the active conda env. Safe to run multiple times —
each patch checks before applying.

Patch 1 (np.int):  replace the deprecated np.int with np.int64.

Patch 2 (wedgefill): the active (numpy) preprocessing path in e2spt_pcasplit.py
    never implemented missing-wedge fill — the reference-based fill the author
    intended exists only in a commented-out real-space block, so the
    --nowedgefill flag was a no-op. This patch re-activates that behaviour in
    the active path: before masking each particle we fill its missing wedge from
    the consensus reference (mask.wedgefill, fillsource = threed_XX.hdf FFT),
    gated on --nowedgefill. With the flag set, behaviour is unchanged.

Patch 3 (per-particle normalization): the script's own contrast normalization
    (`avg=np.sum(data,axis=0)/w` then a single global `std=np.std(abs(dv))`) is
    computed once across ALL particles+voxels -- no per-particle mean/std
    removal ever happens, so particle-to-particle contrast/brightness scale
    differences survive straight into the PCA input. Gated behind env var
    EMAN2_PERPARTICLE_NORM=1 (default off, existing behaviour unchanged): when
    set, z-scores each particle's real-space array (mean=0, std=1) right after
    masking, before the FFT/PCA step.
"""
import shutil
import os
import sys

script_path = shutil.which("e2spt_pcasplit.py")
if script_path is None:
    print("ERROR: e2spt_pcasplit.py not found on PATH. Is the eman2 conda env active?")
    sys.exit(1)

with open(script_path, "r") as f:
    content = f.read()

orig = content
backup = script_path + ".bak"


def ensure_backup():
    if not os.path.exists(backup):
        shutil.copy2(script_path, backup)
        print(f"Backup: {backup}")


# ---- Patch 1: np.int -> np.int64 ----
if "r = r.astype(np.int)" in content:
    ensure_backup()
    content = content.replace("r = r.astype(np.int)", "r = r.astype(np.int64)")
    print("Patched: np.int -> np.int64")
else:
    print("np.int patch: already applied / not needed")

# ---- Patch 2: enable reference-based wedge fill ----
if "#WEDGEFILL_PATCH" in content:
    print("wedgefill patch: already applied")
else:
    # 2a. Precompute the reference FFT once, just before the particle loop.
    loop_anchor = "\t#n=EMUtil.get_image_count(pname)\n\tfor i in irange.tolist():"
    loop_repl = (
        "\t#n=EMUtil.get_image_count(pname)\n"
        "\trefft = threed.do_fft() if not options.nowedgefill else None  #WEDGEFILL_PATCH\n"
        "\tfor i in irange.tolist():"
    )

    # 2b. Fill the missing wedge from the reference before masking each particle.
    body_anchor = (
        "\t\te=EMData(pname, i)\n"
        "\t\te.transform(xf)\n"
        "\t\te.mult(msk)"
    )
    body_repl = (
        "\t\te=EMData(pname, i)\n"
        "\t\te.transform(xf)\n"
        "\t\tif not options.nowedgefill:  #WEDGEFILL_PATCH\n"
        "\t\t\teft=e.do_fft()\n"
        "\t\t\teft.process_inplace(\"mask.wedgefill\",{\"fillsource\":refft, \"thresh_sigma\":0.0})\n"
        "\t\t\te=eft.do_ift()\n"
        "\t\te.mult(msk)"
    )

    if loop_anchor not in content:
        print("ERROR: could not find loop anchor for wedgefill patch. Aborting patch 2.")
        sys.exit(1)
    if body_anchor not in content:
        print("ERROR: could not find body anchor for wedgefill patch. Aborting patch 2.")
        sys.exit(1)

    ensure_backup()
    content = content.replace(loop_anchor, loop_repl)
    content = content.replace(body_anchor, body_repl)
    print("Patched: enabled reference-based mask.wedgefill (gated on --nowedgefill)")

# ---- Patch 3: per-particle normalization (env EMAN2_PERPARTICLE_NORM=1) ----
if "#PERPARTICLE_NORM_PATCH" in content:
    print("per-particle-norm patch: already applied")
else:
    norm_anchor = "\t\ten=e.numpy().copy()\n"
    norm_repl = (
        "\t\ten=e.numpy().copy()\n"
        "\t\tif os.environ.get('EMAN2_PERPARTICLE_NORM')=='1':  #PERPARTICLE_NORM_PATCH\n"
        "\t\t\ten=(en-en.mean())/(en.std()+1e-8)\n"
    )
    if norm_anchor not in content:
        print("ERROR: could not find anchor for per-particle-norm patch. Aborting patch 3.")
        sys.exit(1)
    ensure_backup()
    content = content.replace(norm_anchor, norm_repl)
    print("Patched: added per-particle normalization (gated on EMAN2_PERPARTICLE_NORM=1)")

if content != orig:
    with open(script_path, "w") as f:
        f.write(content)
    print(f"Wrote: {script_path}")
else:
    print(f"No changes: {script_path}")
