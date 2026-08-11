# Native package tests (manual only — never run in CI)

These are structural-invariant checks against real, installed packages (not
exact-label checks — several packages here are stochastic or unseeded). They
require MATLAB, GPUs, or conda envs CI will never have, so they are never run
automatically.

Once a real package adapter lands (M3+), add it to `manifest.yaml` and run:

```console
stw selftest --native
```

`selftest` auto-skips any package whose `stw check-env` fails, so the same
command is safe on any machine — it doubles as an install-status report.

Nothing to run yet: as of this commit only the HAC Baseline adapter (Tier A,
no external dependencies) exists, and it's already covered by
`tests/integration/test_run_hac_end_to_end.py`, which *does* run in CI.
