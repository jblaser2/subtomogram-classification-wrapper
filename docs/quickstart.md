# Quickstart

```console
pip install -e ".[dev,viz]"      # from a clone, during early development
stw init                          # writes stw_config.yaml
```

## What to point it at

Put your subtomograms in **one directory**, all as `.mrc` files, all the **same box size**
and **same pixel size**, and **already aligned** (rough or fine — see
`alignment_state` below; `unaligned` particles are rejected outright, since every
adapter wired up so far applies existing poses rather than searching for new ones).
That directory is the `particles:` path in the config below — nothing else to prepare.

Edit `stw_config.yaml`:

```yaml
particles: ./subtomos       # a directory of same-box-size, same-pixel-size .mrc particles
pattern: "*.mrc"
k: 2
mask:
  kind: auto                 # or sphere / cylinder / file / none — see docs/mask-design.md
alignment_state: fine        # most packages here require pre-aligned input, see docs/limitations.md
packages: [hac]              # which registered adapters to run — `stw list` shows all of them
out_dir: ./stw_out
```

```console
stw check-env                 # see what's installed, and what each package needs if it isn't
stw run stw_config.yaml --dry-run   # preview the exact steps every package would run
stw run stw_config.yaml
```

Outputs land in `out_dir`:

- `<package>/k<k>/seed<NN>/predictions.csv` — the actual class assignments: `particle,class_int,class_name`
- `<package>/k<k>/seed<NN>/class_averages/*.mrc` — one averaged volume per class
- `<package>/k<k>/seed<NN>/run.log` (+ `.timing.json`) — that job's own subprocess log and wall-clock time
- `<package>/_cache/<particle-set fingerprint>/` — expensive intermediate artifacts shared across
  every `k`/seed for that package and particle set (native-format conversions, prep steps,
  embeddings) — safe to delete to reclaim disk; everything in it is recomputed on the next run
  that needs it. The fingerprint subdirectory (a hash of the particle directory/pattern/file
  list/box/pixel size) means reusing the same `out_dir` for a *different* dataset never reuses
  the wrong one's cached prep — each dataset gets its own subdirectory automatically.
- `_cache/<particle-set fingerprint>/mask_<hash>.mrc` (+ `.overlay.png`) — the one resolved mask
  every package in the run shares
- `comparison/cross_package.png` — cross-package agreement matrix (needs >= 2 successful packages)
- `run_report.json` / `summary.md` — everything above plus preflight results, warnings, and timing,
  in one place
