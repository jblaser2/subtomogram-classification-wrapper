# Docker / Podman image

!!! info
    This page summarizes `docker/README.md` in the repo, which is the
    authoritative, always-current source for exact commands.

Bundles HAC Baseline, all three `mode: preview` adapters, EMAN2, PyTom, and
DISCA into one image — every package that doesn't need a MATLAB license or a
per-machine compile step (Tier C/D: PEET, ProTomo, Dynamo, STOPGAP — see
[limitations](limitations.md) for why those can't be containerized).

```console
docker build -f docker/Dockerfile.tier-ab -t stw:tier-ab .
docker run --rm -v "$PWD/my_particles:/data" stw:tier-ab run /data/config.yaml
```

Podman (rootless, no daemon) works identically — substitute `podman` for
`docker` above, adding `:Z` to the volume mount on SELinux-enforcing hosts
(RHEL, Fedora).

DISCA falls back to CPU automatically if no GPU is passed through (add
`--gpus all` for Docker or `--device nvidia.com/gpu=all` for Podman if the
host has the NVIDIA Container Toolkit configured) — CPU works but is
genuinely slow, see Verified below.

## Verified

Built and run end-to-end with Podman on 2026-08-13: a real 3-package run
(HAC + EMAN2 + PyTom) against the tiny test fixture scored ARI=1.0 against
ground truth for all three, with full cross-package agreement. Two
non-obvious fixes were needed to get there — both already baked into the
Dockerfile and the PyTom adapter itself, not something you need to redo:

- PyTom's C extensions need **gcc/g++ pinned to 12** (conda-forge's current
  default promotes some of PyTom's old SWIG-generated code to hard compile
  errors).
- PyTom's `mpirun` call needs **`--allow-run-as-root`** — OpenMPI refuses to
  run as root at all otherwise, and a container's default user is root. The
  adapter adds this automatically when needed (a no-op otherwise).

**DISCA added and re-verified 2026-08-14** (CPU-fallback path only — this
reference machine has no NVIDIA Container Toolkit): `stw check-env` found the
`disca` conda env and reported the missing GPU as a degraded note, not a
failure; a real run against the tiny fixture completed successfully on CPU
(non-degenerate split) in ~20.5 minutes — about 19x slower than the ~65-70s
a real GPU takes on the same fixture. Confirms the documented CPU fallback is
real, not just a code path that's never been exercised.

See `docker/README.md` for the full explanation and a rootless-Podman
troubleshooting recipe for restricted/managed machines.
