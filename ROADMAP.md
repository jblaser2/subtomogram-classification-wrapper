# Roadmap

Full architecture rationale lives in the project's design plan (author's local notes); this
file tracks the public milestone sequence.

- **M0 — scaffolding + generalized core.** Config/spec types, mask primitives (sphere +
  cylinder), generic class-averaging, cross-package comparison math, the
  requirements/capabilities framework, `stw check-env`/`list`/`init`. *Done when CI is green
  with unit tests and no external cryoET software installed.*
- **M1 — end-to-end with HAC Baseline only.** Locks the `Adapter` contract before a second
  package is added. *Done when `stw run` on a tiny fixture produces predictions, class
  averages, a comparison report, and a run report; `--dry-run`/`--resume` work; a broken job
  doesn't abort the batch.*
- **M2 — preview mode.** Three lightweight, dependency-free Python ports (approximating
  Dynamo/PyTom/ProTomo) wired up as adapters — a multi-method demo that needs zero native
  installs.
- **M3 — EMAN2**, the first real native pilot (conda-installable, no GPU/MATLAB/license).
- **M4 — PyTom** + a Tier A/B Docker image bundling every conda-installable package.
- **M5 — v0.1 release**: PyPI + conda-forge, docs site, `docs/limitations.md` finalized.
- **M6+ — remaining packages**, one workstream each: RELION → PEET → STOPGAP → Dynamo →
  ProTomo → DISCA (kept out of any `--all` default given its runtime).
- **M7 — GUI**, deferred until after v0.1, built on the same core library (`RunConfig`'s
  JSON Schema, the requirements/capabilities report, JSONL progress events).

## Package install tiers

| Tier | Meaning | Packages |
|---|---|---|
| A | Vendored, always available | HAC Baseline, preview-mode ports |
| B | `stw install <pkg>` automates a conda env | EMAN2, PyTom, DISCA, RELION (CPU) |
| C | Detected, not auto-installed (no license needed, but no conda path) | PEET, ProTomo |
| D | MATLAB-licensed and/or per-machine compile step | Dynamo, STOPGAP |

TomoFlow and OPUS-TOMO are intentionally out of scope — both are too slow for a "quick"
comparison tool.
