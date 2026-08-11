# Quickstart

```console
pip install -e ".[dev,viz]"      # from a clone, during early development
stw init                          # writes stw_config.yaml
```

Edit `stw_config.yaml`:

```yaml
particles: ./subtomos       # a directory of same-box-size, same-pixel-size .mrc particles
pattern: "*.mrc"
k: 2
mask:
  kind: auto                 # or sphere / cylinder / file / none — see config-reference.md
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

- `<package>/k<k>/seed<NN>/predictions.csv` — `particle,class_int,class_name`
- `<package>/k<k>/seed<NN>/class_averages/*.mrc` — one averaged volume per class
- `comparison/cross_package.png` — cross-package agreement matrix (needs >= 2 successful packages)
- `run_report.json` / `summary.md` — everything above plus preflight results, warnings, and timing
