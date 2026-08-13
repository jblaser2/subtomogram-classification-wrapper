
# Installing Dynamo

**Tier D — licensed/compiled, guided only.** Dynamo itself has no license
requirement, but its classification method (`dpkpca`) is a MATLAB toolbox
(`.m` scripts + compiled MEX) that hard-requires **MATLAB's Parallel
Computing Toolbox (PCT)** — there is no CPU-only fallback that avoids it.

1. Install [Dynamo](https://www.dynamo-em.org/) somewhere, e.g.
   `~/Research/dynamo`. It ships its own `dynamo_activate.m` that sets up
   MATLAB's path — `stw` looks for it at
   `~/Research/dynamo/dynamo_activate.m` by default; override with
   `package_options.dynamo.dynamo_activate`.
2. Have MATLAB with the **Parallel Computing Toolbox** licensed and `matlab`
   on `PATH`.

Verify with:

```console
matlab -nodisplay -batch "disp(license('test','Distrib_Computing_Toolbox'))"  # should print 1
stw check-env --package dynamo
```

## What `stw` actually does with it

`stw`'s Dynamo adapter drives the real `dpkpca` embedding
(`dpkpca.new` → `.unfold()` → `prealign` → `ccmatrix` → `eigentable` →
`eigenvolumes` → `getEigencomponents()`) — never reimplements it. The
embedding is deterministic and seed-independent, so it's computed once per
particle set + mask (cached, shared across every `k`/seed); only the final
clustering — a plain `sklearn.cluster.KMeans` on the top eigencomponent
columns, done in Python, not MATLAB — depends on `(k, seed)`. `seed` is a
**genuine, reproducible seed** here (`random_state=seed`), unlike EMAN2/PEET's
run-index pseudo-seed.

**A real, honestly-documented finding from validating this adapter**: on
`stw`'s own easy synthetic test fixture, k-means on the blind
top-10-eigencomponent default (matching the source project's own long-used
production setting) lands at near-chance ARI, even though the true
class-separating signal is cleanly present in the embedding (verified
directly — a single eigencomponent column alone correlates at ARI=1.0 with
ground truth). Ten mostly-noise dimensions are enough to pull unstandardized
k-means to a different local optimum on a small sample. This is not a
plumbing bug — it's the same "blind PC/factor selection is often not the
discriminating axis" property already well established for
ProTomo/STOPGAP/Dynamo throughout the source benchmark project this tool grew
out of. If a real run looks chance-level, try
`package_options.dynamo.pc_cols` (a comma-separated, 1-indexed column list,
e.g. `"1,2"`) — the same tuning knob used there.

**A second real, machine-specific finding**: `matlab -nodisplay -batch`
occasionally (observed roughly 1 in 8 invocations) segfaults in an unrelated
telemetry/entitlement module (`libmwddux.so`) on process exit — *after* the
real computation has already completed and its output is flushed. This
adapter never trusts the embedding subprocess's exit code alone; it checks
for `eigencomponents.csv` actually existing as the real success signal. The
same flakiness was found in `stw`'s own `MATLAB_TOOLBOX` requirement checker
(a license check can crash before or after printing its answer) and fixed
there too — it now reads only the first stdout line and retries once.

Parpool worker count is capped based on the mask's active-voxel fraction
(2/4/8 workers) rather than left at Dynamo's own default (`cores='*'`, one
worker per CPU core) — a real fix for a machine-crashing bug found in the
source project: each worker holds a full per-particle vector sized by the
mask's active-voxel count, and a wide-open mask with the naive default
worker count drove system RAM from 11GB to 58GB in under a minute.
Missing-wedge weighting is not modeled (identity-pose `.tbl` rows carry no
wedge/CTF info).
