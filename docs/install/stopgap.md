
# Installing STOPGAP

**Tier D — licensed/compiled, guided only.** Unlike every other package `stw`
supports, STOPGAP has no confirmed public download page or pip/conda
package — it's obtained directly from its developers as a private archive.
This page describes the layout `stw` expects once you have it, not where to
get it; ask the STOPGAP developers directly for access.

## Expected layout

A working STOPGAP install (this is what `stw` was validated against) looks
like:

```
<stopgap_home>/
├── sg_toolbox/            # MATLAB function library (source, not compiled)
└── exec/
    ├── lib/
    │   ├── stopgap                    # compiled MCR binary
    │   ├── stopgap_parser              # compiled MCR binary
    │   ├── sg_toolbox                  # compiled MCR binary
    │   ├── stopgap_config.sh           # sourced by stopgap_parser.sh
    │   ├── stopgap_config_local.sh     # sourced by stopgap_mpi_slurm.sh (local runs)
    │   └── stopgap_config_slurm.sh     # sourced by stopgap_mpi_slurm.sh (SLURM runs)
    └── bin/
        ├── stopgap_parser.sh
        ├── stopgap_pca_parser.sh
        ├── stopgap_mpi_slurm.sh
        └── ...
```

`stw` looks for this at `~/Research/STA/packages/STOPGAP` by default —
override with `package_options.stopgap.stopgap_home`.

## Other requirements

1. **MATLAB** with `matlab` on `PATH`. Unlike Dynamo, STOPGAP's classification
   path does **not** need the Parallel Computing Toolbox — its parallelism is
   OS-level MPI, not MATLAB's `parpool`/`parfor` (confirmed by reading every
   `.m` script the PCA path touches). MATLAB is still needed to run three
   plain sequential glue scripts and to supply the MCR binaries' runtime
   libraries.
2. **OpenMPI** (`mpirun`/`mpiexec`). On RHEL/Fedora, the `openmpi` RPM
   installs these at `/usr/lib64/openmpi/bin/` **without** putting them on
   `PATH` by default — `stw`'s own MPI check knows to look there too, so
   `stw check-env` reports this correctly even if `which mpiexec` comes up
   empty in your shell.

Verify with:

```console
stw check-env --package stopgap
```

## A real, machine-specific gotcha: the vendored MATLAB runtime path

The compiled binaries' wrapper scripts
(`exec/lib/stopgap_config.sh`/`stopgap_config_local.sh`/`stopgap_config_slurm.sh`)
hardcode a `matlabRoot` path — whatever MATLAB install the archive's original
publisher (or whoever configured your copy) pointed at. If that path doesn't
exist on the machine actually running `stw`, these scripts don't fail; they
just silently prepend a directory the dynamic linker skips, harmlessly. `stw`
doesn't rely on that being correct: it always exports its own
`LD_LIBRARY_PATH` (built from `package_options.stopgap.matlab_root`, default
`~/Applications/matlab`) *before* invoking any STOPGAP binary. The vendored
scripts' own `export LD_LIBRARY_PATH=...:$LD_LIBRARY_PATH` form *appends*
rather than replaces, so both survive and the correct one is still found —
you do not need to edit these vendored scripts yourself, just make sure
`matlab_root` points at your own MATLAB (or MATLAB Runtime) install.

## What `stw` actually does with it

`stw`'s STOPGAP adapter drives STOPGAP's real CC-matrix PCA pipeline —
never reimplements it:

1. `build_inputs_generic.m` (a small `stw`-authored driver over real
   `sg_toolbox` calls — STOPGAP itself ships no "arbitrary particle
   directory in" driver) writes a motivelist + `subtomo_N.mrc` symlinks.
2. `build_wedgelist.m` (unmodified from the source project) writes a
   tilt-range wedgelist.
3. The mask is copied into STOPGAP's `mask/` and `masks/` directories, and a
   global average reference is built in-process (no extra conda env needed).
4. `build_pca_aux.m` (unmodified) writes the bandpass filter list — always
   deleting any prior `filter_list.star` first, since STOPGAP's own filter
   appender only ever appends, and a stale duplicate entry can hang a later
   step.
5. Three compiled MCR binaries — `rot_vol` (rigid pre-rotation),
   `calc_ccmat` (pairwise CC matrix), `calc_pca_ccmat` (eigendecomposition) —
   run via `mpiexec`, producing `pca/eigenval_1.csv` (one row per particle).

Steps 1–5 are deterministic and seed-independent, so they run once per
particle set + mask (cached, shared across every `k`/seed). Only the final
clustering — plain `sklearn.cluster.KMeans` on the top eigen-projection
columns, done in Python — depends on `(k, seed)`. `seed` is a **genuine,
reproducible seed** here (`random_state=seed`), like Dynamo/ProTomo, unlike
EMAN2/PEET's run-index pseudo-seed.

**Real, tilt-range wedge support** (unlike Dynamo, which models no wedge at
all): set `wedge.kind: uniform` with `tilt_min`/`tilt_max` in your config to
have those reach STOPGAP's own wedgelist. Leaving `wedge.kind: none` (the
default) assumes a full ±90° range — i.e. no missing-wedge weighting. CTF and
exposure weighting are always off (`calc_ctf=0`/`calc_exp=0`) — this
dataset-agnostic pipeline has no per-tomogram defocus/dose metadata to weight
with. `package_options.stopgap.tilt_step` (default 3.0°) controls the
wedgelist's tilt sampling density.

**A real, honestly-documented finding from validating this adapter**: unlike
Dynamo (where a single eigencomponent column recovers `stw`'s own test
fixture's true split at ARI=1.0), no single column or small column subset
examined for STOPGAP's embedding on that same fixture gets close to a clean
separation — the best found (column 3 alone) reaches only ARI~0.29. This was
checked directly, not assumed: the embedding pipeline was independently
verified structurally correct (a 32×10 `pca/eigenval_1.csv`, one row per
particle, in the fixture's canonical sorted-file order) before concluding
this is a property of the method on this particular fixture — plausibly
STOPGAP's real-space masked CC-matrix comparison responding differently than
Dynamo's eigenvolume decomposition to this synthetic contrast, not a port
bug. The blind default stays `PC_TOP=10` (the source project's own promoted
default, up from STOPGAP's native 3-column default); if a real run looks
chance-level, try `package_options.stopgap.pc_cols` (comma-separated,
1-indexed, same convention as Dynamo's `pc_cols`).

**A real, shared reliability finding**: `matlab -batch` (used to run the
three `.m` glue scripts above) has the same rare (~1 in 8 invocations,
observed while building the Dynamo adapter) segfault-on-exit risk in an
unrelated telemetry module (`libmwddux.so`) already documented for Dynamo —
always *after* the real computation completes. This adapter checks for each
step's expected output file rather than trusting that subprocess's return
code. The three MCR-compiled binaries dispatched via `mpiexec` are standalone
executables, not `matlab -batch`, and showed no equivalent flakiness during
validation — their exit codes are trusted directly, with
`pca/eigenval_1.csv` existing checked as the final overall gate regardless.

STOPGAP also ships a multi-reference-alignment (MRA) classifier and a native
HAC clustering mode. Neither is ported here: the source benchmark project
tested both extensively and found MRA suffers an unresolved "attractor"
problem (particles essentially never leave their starting class) plus a
separate registration/banding artifact, and native HAC never beat the
CC-matrix-PCA+k-means baseline. CC-matrix PCA is the only method ported.

Worker count for the three `mpiexec` steps is capped by the mask's
active-voxel fraction (4/8/16 workers) — the same OOM-prevention fix already
applied to Dynamo/PyTom's worker counts, since a wide-open mask makes each
MPI rank's per-particle working set much larger.
