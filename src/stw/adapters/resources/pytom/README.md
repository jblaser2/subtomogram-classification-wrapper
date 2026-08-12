# Vendored PyTom pipeline scripts

`auto_focus_classify_nofrm.py` is real PyTom source (its own iterative
auto-focus/difference-map classifier), vendored **verbatim, untouched** —
`stw` drives it, never reimplements it. It runs inside a conda env named
`pytom_env` via `mpirun`.

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
