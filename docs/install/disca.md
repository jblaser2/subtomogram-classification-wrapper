
# Installing DISCA

**Tier B — conda-automatable.** No license needed, and no from-source compile
trickery like PyTom/RELION — DISCA (from the `aitom` toolkit, Xu Lab) is a
pip-installable PyTorch model.

```console
conda env create -f envs/disca.yml -n disca
```

`envs/disca.yml` pins a CUDA 12.8 PyTorch wheel; edit the index URL for a
different CUDA version, or drop it entirely for CPU-only (works, but see the
runtime note below — DISCA is genuinely impractical on CPU beyond a tiny
fixture).

A GPU is **optional but strongly recommended**: `stw check-env` reports a
missing GPU as a *degraded* note, not a hard failure, since DISCA's own code
falls back to CPU automatically (`torch.device('cuda:0') if
torch.cuda.is_available() else torch.device('cpu')`).

Verify with:

```console
conda run -n disca python -c "import torch; print(torch.cuda.is_available())"
stw check-env --package disca
```

## What `stw` actually does with it

`stw`'s DISCA adapter drives the real training/classification loop
(`torch_disca_run.py`, vendored from `aitom` — a YOPO CNN feature extractor +
Gaussian-mixture E-step, iterated) inside the `disca` conda env — never
reimplements it. Input packaging (masking + Fourier-cropping to DISCA's own
32³ working regime + per-particle standardization) is pure numpy/mrcfile
logic done in-process, no conda env needed for that part — the same
"prep needs zero package bindings" pattern already used for RELION/PEET.

**Always passes `DISCA_FIX_CHANNELS=1`, not left as an opt-in toggle.** The
vendored script's original behavior puts the channel axis last
(`np.expand_dims(v, -1)`), which `Conv3d` silently reads as the spatial
box-size axis becoming the channel count — this only avoided crashing by
coincidence at box=32 (its first conv layer hardcodes `in_channels=32` unless
the fix is set, which correctly switches it to `in_channels=1`). Since `stw`
doesn't force every particle set to exactly 32³, the fix is required for
correctness at any other box size, not just an improvement.

**Genuinely unseeded**: DISCA's own training loop never seeds
torch/numpy/CUDA RNGs. `seed` here is a run index in name only — even two
runs at the *same* `job.seed` produce different results, unlike EMAN2/PEET's
run-index convention (a deterministic algorithm, index only for bookkeeping).
Only the mask-dependent input packaging is cached across `(k, seed)`; every
classification run is a fresh, independent training run.

**Real runtime**: ~65-70s end to end for `stw`'s own 32-particle, 24³-box
test fixture on a single consumer GPU — but the source benchmark project
reports **2.5-4.7 hours per seed** at real dataset scale (500-800 particles,
box 80-96). `stw` does not shorten DISCA's own iteration count
(`Config.M = 80`) to make this faster. **This is the one adapter that should
never be part of a default/`--all` package set** given that cost.

**A real, honestly-documented finding, not a plumbing bug**: on `stw`'s own
easy test fixture, DISCA lands at consistently near-chance ARI across
independent runs (verified directly: three separate runs scored 0.033,
-0.031, and -0.012), despite each one completing correctly (non-degenerate
splits, real decreasing training loss). DISCA is designed for large-scale
*de novo* structural discovery across thousands of particles, not
fine-grained classification of a handful of pre-aligned ones from a single
known complex — a heavily overparameterized CNN (~1360-channel bottleneck)
trained on 32 samples is expected to struggle, and the source project's own
extensive results (T4P, T3SS_conf) show DISCA frequently locking onto a
contrast/intensity axis rather than the true structural one even at hundreds
of real particles.
