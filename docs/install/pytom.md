# Installing PyTom

**Tier B — conda-automatable, but the most fragile automated path of the
Tier B packages.** No GPU required (CPU-only classification, GPU optional),
no MATLAB, no license — but PyTom itself isn't on PyPI and doesn't build a
usable `pip` wheel: its `setup.py` generates three launcher scripts
(`pytom/bin/{pytom,ipytom,pytomGUI}`) via a C++ compile step wired into a
*custom* `install` command that only the legacy `python setup.py install`
invocation actually runs — any `pip install` (even `--no-build-isolation`)
skips it and fails with `pytom/bin/pytom: No such file or directory`.

```console
conda env create -f envs/pytom.yml -n pytom_env
git clone --depth 1 https://github.com/SBC-Utrecht/PyTom.git /tmp/PyTom
cd /tmp/PyTom
conda run -n pytom_env python setup.py install --prefix "$(conda info --envs | grep pytom_env | awk '{print $NF}')"
cd - && rm -rf /tmp/PyTom
```

Two non-obvious things have to be right for this to actually succeed (both
already baked into `envs/pytom.yml` / `docker/Dockerfile.tier-ab`, spelled
out here since getting either wrong produces a confusing failure):

1. **The compiler must be pinned to gcc/g++ 12, not whatever's current.**
   PyTom's C extensions are SWIG-generated wrappers predating Python 3's C
   API (e.g. calls to `PyString_Check`/`PyInt_Check`, which don't exist in
   Python 3) and contain a couple of genuine ISO C violations (an
   incompatible function-pointer assignment in a bundled NFFT demo).
   Pre-GCC-14 toolchains only *warn* about these; GCC 14+ promotes them to
   hard errors by default, and the whole build fails outright (worse: it
   fails *silently past* `pytom/bin/pytom`, `ipytom`, `pytomGUI` never being
   generated, producing the confusing `pytom/bin/pytom: No such file or
   directory` error instead of a compiler error pointing at the real cause).
   Verified clean end-to-end with `gcc=12`/`gxx=12` pinned; conda-forge's
   current default (`gcc-15.2.0` as of this writing) fails.
2. **Always invoke through `conda run -n pytom_env ...`, never a bare
   interpreter path** (e.g. `/path/to/envs/pytom_env/bin/python setup.py
   install`). The compile step shells out to `swig`/the compiler by bare
   name; only `conda run` (or an actual `conda activate`) puts this env's
   `bin/` on `PATH` for those subprocess calls. A bare interpreter path only
   selects the *interpreter*, not the environment's `PATH` — and the failure
   mode is the same confusing "missing bin/pytom" error, not an obvious
   "swig: command not found."

With both of those right, the build is clean — no errors, not even the usual
"some C extension failed to compile" noise.

Note the other pin in `envs/pytom.yml`: PyTom (as validated here) needs
**`numpy<2`** — its classifier does a numeric version comparison that breaks
on numpy 2.x if not pinned.

Verify with:

```console
conda run -n pytom_env python3 -c "import pytom; print('ok')"
conda run -n pytom_env mpirun --version
stw check-env --package pytom
```

`stw` looks for a conda env literally named `pytom_env` (not `pytom`) under
`~/conda-envs/pytom_env` or `~/miniforge3/envs/pytom_env` by default. Point
it elsewhere with `package_options.pytom.conda_env`.

## The `_swig_frm` caveat (classification doesn't need it; `stw align` does)

Many PyTom builds — including the one this classification adapter was
validated against — don't have a compiled `_swig_frm` extension (PyTom's
FRM alignment-search module). `stw`'s **classification** adapter always
passes `-a` (no-align) regardless, since it assumes pre-aligned input
project-wide anyway (see [`../limitations.md`](../limitations.md)) — so this
is a non-issue for classification specifically.

**`stw align`** (see [`../align.md`](../align.md)) is the one place this
extension actually matters — it drives PyTom's real FRM alignment search,
which needs it compiled. This is a real compile, not a config flag (PyTom's
own installer just silently disables this piece rather than failing, on any
modern gcc): run

```console
scripts/compile_pytom_frm.sh
```

once against your `pytom_env`. See [`../align.md`](../align.md) for what
this actually gets you and its real limitations.

## What `stw` actually does with it

`stw`'s PyTom adapter drives real PyTom's own `auto_focus_classify_nofrm.py`
(an iterative reference-pair difference-map classifier, run via `mpirun`) —
it never reimplements the algorithm, beyond one small compatibility shim for
a real cross-version break (see `src/stw/adapters/resources/pytom/README.md`).
Unlike every other adapter in this
project at this stage, PyTom has a **real, working missing-wedge
pass-through**: setting `wedge.kind: uniform` with `tilt_min`/`tilt_max` in
your config bakes a real `SingleTiltWedge` into PyTom's particle-list XML.
Leaving wedge unset means PyTom runs assuming full (0-degree missing-wedge)
coverage — `stw` does not silently assume a specific tilt geometry you never
stated.
