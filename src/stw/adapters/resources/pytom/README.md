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
