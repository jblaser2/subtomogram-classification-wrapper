# Roadmap

Full architecture rationale lives in the project's design plan (author's local notes); this
file tracks the public milestone sequence.

- [x] **M0 — scaffolding + generalized core.** Config/spec types, mask primitives (sphere +
  cylinder), generic class-averaging, cross-package comparison math, the
  requirements/capabilities framework, `stw check-env`/`list`/`init`. CI green with unit tests
  and no external cryoET software installed.
- [x] **M1 — end-to-end with HAC Baseline only.** Locks the `Adapter` contract before a second
  package is added. `stw run` on the tiny fixture produces predictions, class averages, a
  comparison report, and a run report; `--dry-run`/resume-via-cache work; a broken/incompatible
  job doesn't abort the batch.
- [x] **M2 — preview mode.** Three lightweight, dependency-free Python ports (approximating
  Dynamo/PyTom/ProTomo — `dynamo-preview`/`pytom-preview`/`protomo-preview`) wired up as
  adapters. A 4-method comparison (with HAC Baseline) runs end to end and in CI with zero
  native installs. `mode: preview` in a config auto-resolves a bare package name (`dynamo`) to
  its `-preview` variant; `mode: native` never does, so this stays forward-compatible once a
  real native adapter for the same name lands. Each preview adapter surfaces its measured
  fidelity/limitations as a `check-env` note and a run-time warning — see the module docstrings
  in `src/stw/adapters/preview/`.
- [x] **M3 — EMAN2**, the first real native pilot (conda-installable, no GPU/MATLAB/license).
  Wraps EMAN2's own `e2spt_average.py`/`e2refine_postprocess.py`/`e2spt_pcasplit.py` (never
  reimplements the algorithm); a cached multi-step prep (patch → ingest → consensus average →
  postprocess → mask convert, shared across every k/seed) precedes a per-run classify step.
  Verified end-to-end against a real installed `eman2` conda env: k=2 recovers the fixture's
  true split exactly (ARI=1.0), k=3 gives a non-degenerate split, and a cached second run is
  ~2.4x faster than the first. `seed` here is a run index (EMAN2's own CLI exposes no
  `random_state`), matching the same caveat already documented for `pytom-preview`.
- [x] **M4 — PyTom**, real (not preview): drives real `auto_focus_classify_nofrm.py` via
  `mpirun` inside a `pytom_env` conda env, an iterative reference-pair difference-map
  classifier. The first adapter with a genuinely working missing-wedge pass-through —
  `wedge.kind: uniform` bakes a real `SingleTiltWedge` into PyTom's particle-list XML,
  verified by round-tripping two different tilt-range configs to two distinct correctly-angled
  cached XMLs. Verified end-to-end against a real installed `pytom_env`: k=2 recovers the
  fixture's true split exactly (ARI=1.0). Caught and fixed a real caching bug along the way
  (in both this adapter and EMAN2's): the native-format mask conversion was cached by
  existence only, not keyed to the mask's own content hash, so changing masks across runs
  sharing an `out_dir` would have silently reused a stale converted mask. Still missing a
  Tier A/B Docker image bundling every conda-installable package — folded into M5.
- **M5 — v0.1 release prep: done; actual publishing is your call, not automated.**
  - [x] **Tier A/B Docker/Podman image** (`docker/Dockerfile.tier-ab`) bundling HAC Baseline,
    all 3 preview adapters, EMAN2, and PyTom. Built AND run end-to-end with Podman (rootless,
    no daemon) — a real 3-package classification against the tiny fixture scored ARI=1.0 for
    all three against ground truth, full cross-package agreement. Needed two real fixes beyond
    the native install docs: PyTom's C extensions need gcc/g++ pinned to 12 (not conda-forge's
    current default), and PyTom's `mpirun` call needs `--allow-run-as-root` (a container's
    default user is root; the adapter now adds this automatically, a no-op elsewhere). See
    `docker/README.md`.
  - [x] **PyPI packaging prepped, not published.** Package name
    `subtomogram-classification-wrapper` confirmed available; `python -m build` + `twine check`
    both pass; the built wheel was installed into a clean venv and ran a real classification
    successfully. Actual `twine upload` deliberately left to you — see `docs/publishing.md` for
    the exact command and a GitHub Actions trusted-publishing workflow
    (`.github/workflows/release.yml`) that's wired up but inert until you configure PyPI's
    trusted-publisher settings for this repo.
  - [x] **conda-forge recipe drafted, not submitted.** `packaging/conda-forge/meta.yaml` is
    ready to file once a real PyPI release exists (submission is a PR to
    `conda-forge/staged-recipes` plus ongoing maintainership — see
    `packaging/conda-forge/README.md`).
  - [x] **Docs site built, not deployed.** `mkdocs.yml` + `docs/` build cleanly
    (`mkdocs build --strict`, verified locally) and `.github/workflows/docs.yml` will
    auto-publish to GitHub Pages on every push to `main` once Pages is enabled for this repo
    (Settings → Pages → Source: GitHub Actions — a one-time click only you can do).
  - [x] `docs/limitations.md` finalized: added a "native installs are genuinely fragile"
    section documenting the real EMAN2/PyTom install gotchas found while building the Docker
    image, and corrected two stale claims (DISCA has no adapter yet; there's no `stw install`
    CLI command — Tier B means "a checked-in `envs/*.yml`," not a built subcommand).
- **M6+ — remaining packages**, one workstream each: RELION → PEET → STOPGAP → Dynamo →
  ProTomo → DISCA (kept out of any `--all` default given its runtime).
- **M7 — GUI**, deferred until after v0.1, built on the same core library (`RunConfig`'s
  JSON Schema, the requirements/capabilities report, JSONL progress events).

## Package install tiers

| Tier | Meaning | Packages |
|---|---|---|
| A | Vendored, always available | HAC Baseline, preview-mode ports |
| B | A conda env from a checked-in `envs/<pkg>.yml` sets it up (`conda env create -f envs/<pkg>.yml -n <pkg>`, per that package's own `docs/install/<pkg>.md` — no dedicated `stw install` CLI command exists yet) | EMAN2, PyTom, DISCA, RELION (CPU) |
| C | Detected, not auto-installed (no license needed, but no conda path) | PEET, ProTomo |
| D | MATLAB-licensed and/or per-machine compile step | Dynamo, STOPGAP |

TomoFlow and OPUS-TOMO are intentionally out of scope — both are too slow for a "quick"
comparison tool.
