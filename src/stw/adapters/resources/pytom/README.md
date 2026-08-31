# Vendored PyTom pipeline scripts

`auto_focus_classify_nofrm.py` is real PyTom source (its own iterative
auto-focus/difference-map classifier) — `stw` drives it, never reimplements
it. It runs inside a conda env named `pytom_env` via `mpirun`. One small
compatibility shim is applied (search `stw compatibility shim` in the file):
`classify()`'s first line calls `ParticleList.pickle()`, which in current
`pytom.basic.structures` assumes every particle already has a `Score` and
raises `AttributeError` on a `None` one — but particle lists built by
`generate_particle_list.py` for pre-aligned input never set one. The shim
just gives each particle an explicit zero `FRMScore` first (semantically a
no-op; `FRMScore`'s own default is 0) before `classify()` runs. Discovered
during Docker-image validation: a fresh `pip install` of PyTom's current
upstream HEAD hits this immediately on any freshly-generated particle list,
so the fix is required for any install newer than whatever commit was
originally used, not specific to this project's own vendored copy.

`generate_particle_list.py` builds PyTom's ParticleList XML from a directory
of pre-aligned MRC particles (identity rotation/shift, since `stw` assumes
pre-aligned input) with a real `SingleTiltWedge` per PyTom's own wedge model.
Vendored from the STA benchmark project with one small patch: the original
hardcoded `*.mrc` as its glob, which could silently pick up unrelated MRC
files in the same directory; `stw`'s copy adds a `--pattern` argument
(defaulting to `*.mrc` for backward compatibility) so it always matches
exactly the particle set the user configured.

`convert_mask.py` is new (not from STA, which did this inline) — converts an
arbitrary MRC mask into PyTom's `.em` format via `pytom.lib.pytom_volume`.

`-a` (noalign) is mandatory here: this machine's PyTom build has no compiled
`_swig_frm` extension, so its alignment search is unavailable regardless —
matching `stw`'s own pre-aligned-input-only stance anyway.

## `stw align` (FRM alignment) scripts

Three more files here drive PyTom's *own* FRM (Fast Rotational Matching)
alignment — `stw`'s `align` feature, not the classification adapter above.
Requires `scripts/compile_pytom_frm.sh` to have been run once (see
`docs/install/pytom.md`'s FRM section); the classification adapter never
needs this, since it always runs `-a`/noalign.

- `build_frm_job.py` — builds a real `FRMJob` XML (PyTom's own
  `Reference`/`Mask`/`SampleInformation`/`FRMJob.toXMLFile()`), never
  hand-rolled XML.
- `frm_align_runner.py` — runs PyTom's own real `pytom/bin/FRMAlignment.py`
  under `mpirun`. A real, separate cross-version break from the one above:
  `FRMAlignment.py` still does `import pytom_mpi` and (inside
  `retrieve_res_vols`/`create_average`) `from pytom_volume import ...` —
  pre-refactor flat module names only resolvable today via
  `pytom.lib.pytom_mpi`/`pytom.lib.pytom_volume`/`pytom.lib.pytom_numpy`/
  `pytom.lib.pytom_fftplan`/`pytom.lib.pytom_freqweight`. This wrapper
  aliases all five into `sys.modules` before running `FRMAlignment`'s own
  `__main__` via `runpy`, rather than patching PyTom's own source.
- `apply_frm_poses.py` — `FRMAlignment.py` itself only ever *averages* the
  aligned stack; it never writes individual aligned particles back out. This
  reads the final `aligned_pl_iterN.xml` and writes each particle's own real
  `getTransformedVolume()` (PyTom's cubic-spline pose application via
  `transformSpline` — never reimplemented) as a new MRC, plus a CSV of the
  recovered per-particle poses/scores for provenance.

Verified end-to-end on a real, deliberately roughly-misaligned copy of the
tiny test fixture (small random rotation + shift applied per particle):
FRM alignment ran 4 real iterations with real FSC-based resolution
tracking, and the realigned average's sharpness (voxel std) recovered from
0.136 (rough) to 0.165 — close to the truly-pre-aligned fixture's own 0.168.
