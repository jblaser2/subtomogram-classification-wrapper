# Installing EMAN2

**Tier B — conda-automatable.** No GPU, no MATLAB, no license.

```console
conda env create -f envs/eman2.yml -n eman2
```

(or, equivalently: `conda create -n eman2 -c cryoem -c conda-forge "eman-dev==2.99.72=nogui*"`)

`stw` looks for a conda env literally named `eman2` under `~/conda-envs/eman2` or
`~/miniforge3/envs/eman2` by default (see `stw.requirements._check_conda_env`).
If your EMAN2 env has a different name or lives elsewhere, point `stw` at it
with `package_options.eman2.conda_env: <name>` (or the environment variable
noted in `stw check-env`'s output).

Verify with:

```console
conda run -n eman2 python3 -c "import EMAN2; print('ok')"
stw check-env --package eman2
```

## What `stw` actually does with it

`stw`'s EMAN2 adapter drives EMAN2's own tools
(`e2spt_average.py`, `e2refine_postprocess.py`, `e2spt_pcasplit.py`) — it
never reimplements the algorithm. One real, one-time patch is applied to the
*installed* `e2spt_pcasplit.py` (idempotent, backs up the original first):
replacing a deprecated `np.int` reference that otherwise crashes on any numpy
released after ~2023. See `src/stw/adapters/resources/eman2/README.md` for
the full patch rationale.

Like every adapter in this project's v0.1, EMAN2 here assumes **pre-aligned**
input (identity poses, no orientation search) and runs with missing-wedge
fill off — see [`../limitations.md`](../limitations.md).
