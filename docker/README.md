# Tier A/B container image

Bundles HAC Baseline, the three `mode: preview` ports, EMAN2, PyTom, and
DISCA into one image — every package that doesn't need a MATLAB license or a
per-machine compile step. This is the "quick and easy" path for that half of
the package set: no conda wrangling, no C-toolchain pinning, just `docker
run`/`podman run`.

## Build

```console
docker build -f docker/Dockerfile.tier-ab -t stw:tier-ab .
# or, rootless, no daemon required:
podman build -f docker/Dockerfile.tier-ab -t stw:tier-ab .
```

Slow step is PyTom (~5-10 min, genuinely compiles C/C++ extensions); DISCA
adds a few more minutes downloading its CUDA PyTorch wheel.

## Running DISCA with a GPU

DISCA falls back to CPU automatically if no GPU is visible inside the
container (verified: ARI-honest, non-degenerate, just ~19x slower — see
below) — but for anything beyond a toy fixture you want the GPU passed
through. That requires the NVIDIA Container Toolkit configured on the host
(`nvidia-ctk`), which this reference machine doesn't have installed — the
CPU-fallback path is what's actually been verified end-to-end here:

```console
# Docker, with the NVIDIA Container Toolkit installed:
docker run --rm --gpus all -v "$PWD/my_particles:/data" stw:tier-ab run /data/config.yaml
# Podman, with the NVIDIA CDI spec generated (nvidia-ctk cdi generate):
podman run --rm --device nvidia.com/gpu=all -v "$PWD/my_particles:/data:Z" stw:tier-ab run /data/config.yaml
```

Without either flag, `stw check-env`'s `gpu: nvidia-smi` check for DISCA
reports a *degraded* note (not a hard failure), matching how the adapter
itself behaves.

## Run

```console
docker run --rm -v "$PWD/my_particles:/data" stw:tier-ab run /data/config.yaml
# rootless / SELinux-enforcing hosts (RHEL, Fedora): add :Z to the mount
podman run --rm -v "$PWD/my_particles:/data:Z" stw:tier-ab run /data/config.yaml
```

`config.yaml`'s `particles:`/`out_dir:` paths must point *inside* the
container (i.e. under `/data`, matching whatever you mounted there).

## Verified

Built and run end-to-end with Podman on 2026-08-13 (rootless, on a machine
without Docker installed — see the two gotchas below if you hit them
elsewhere): `stw list`/`check-env` correctly found both conda envs, and a
real 3-package run (HAC + EMAN2 + PyTom) against the tiny fixture scored
ARI=1.0 against ground truth for all three, with full 32/32 cross-package
agreement.

Two non-obvious fixes were needed to get here, both already baked into this
Dockerfile/the adapter code (not something you need to redo):
- **PyTom's C extensions need gcc/g++ pinned to 12** (not conda-forge's
  current default) — see `envs/pytom.yml` for why.
- **PyTom's `mpirun` call needs `--allow-run-as-root`** — OpenMPI refuses to
  run as root at all otherwise, and a container's default user is root
  unless the image sets up a dedicated one (this one doesn't, to keep things
  simple). `stw`'s PyTom adapter already adds this flag automatically when
  running as root (a no-op otherwise) — see `_mpirun_prefix()` in
  `src/stw/adapters/pytom.py`.

**DISCA added and re-verified on 2026-08-14** (same rootless Podman setup;
this machine has no NVIDIA Container Toolkit, so only the CPU-fallback path
was tested here — see "Running DISCA with a GPU" above for what a GPU host
needs): `stw check-env` correctly found the `disca` conda env installed and
reported the missing GPU as a *degraded* note, not a failure. A real run
against the tiny fixture on CPU completed successfully (`returncode=0`,
non-degenerate 21/11 split) in **~20.5 minutes** — versus ~65-70s on a real
GPU (about 19x slower) — confirming the adapter's documented CPU fallback is
real, just as impractical as advertised beyond a toy-sized job.

## Rootless Podman on a restricted/managed machine

If `podman build`/`run` fail with subuid/subgid or cgroup/dbus errors on a
shared machine where you can't get root to configure `/etc/subuid`, this
combination of flags worked around it (not needed on a normal single-user
Linux box with proper rootless Podman setup, i.e. `/etc/subuid`/`/etc/subgid`
entries for your user):

```console
export XDG_RUNTIME_DIR=/some/writable/dir   # if /run/user/<uid> isn't writable
podman --storage-opt overlay.ignore_chown_errors=true \
       --cgroup-manager=cgroupfs --events-backend=file \
       build --security-opt seccomp=unconfined --security-opt label=disable \
       -f docker/Dockerfile.tier-ab -t stw:tier-ab .
```
