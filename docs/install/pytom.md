# Installing PyTom

**Tier B — conda-automatable, but the most fragile automated path of the
Tier B packages.** No GPU required (CPU-only classification, GPU optional),
no MATLAB, no license — but PyTom itself installs via `pip` inside a conda
env that supplies its compiled-extension build toolchain (OpenMPI, Boost,
FFTW, SWIG, a C/C++ compiler), so the install genuinely compiles native code.

```console
conda env create -f envs/pytom.yml -n pytom_env
```

Note the pin: PyTom (as validated here) needs **`numpy<2`** — its classifier
does a numeric version comparison that breaks on numpy 2.x if not pinned.

Verify with:

```console
conda run -n pytom_env python3 -c "import pytom; print('ok')"
conda run -n pytom_env mpirun --version
stw check-env --package pytom
```

`stw` looks for a conda env literally named `pytom_env` (not `pytom`) under
`~/conda-envs/pytom_env` or `~/miniforge3/envs/pytom_env` by default. Point
it elsewhere with `package_options.pytom.conda_env`.

## The `_swig_frm` caveat

Many PyTom builds — including the one this adapter was validated against —
don't have a compiled `_swig_frm` extension (PyTom's FRM alignment-search
module). `stw` always passes `-a` (no-align) regardless, since it assumes
pre-aligned input project-wide anyway (see [`../limitations.md`](../limitations.md)) —
so this is a non-issue for `stw`'s use of PyTom specifically, but if you use
this same conda env for PyTom's own alignment tools outside `stw`, be aware
it may not be available.

## What `stw` actually does with it

`stw`'s PyTom adapter drives real PyTom's own `auto_focus_classify_nofrm.py`
(an iterative reference-pair difference-map classifier, run via `mpirun`) —
it never reimplements the algorithm. Unlike every other adapter in this
project at this stage, PyTom has a **real, working missing-wedge
pass-through**: setting `wedge.kind: uniform` with `tilt_min`/`tilt_max` in
your config bakes a real `SingleTiltWedge` into PyTom's particle-list XML.
Leaving wedge unset means PyTom runs assuming full (0-degree missing-wedge)
coverage — `stw` does not silently assume a specific tilt geometry you never
stated.
