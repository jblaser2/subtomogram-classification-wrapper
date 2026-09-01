# Config reference

`stw run <config.yaml>` reads a `RunConfig` (see `src/stw/config.py`). Run
`stw init --schema` for the full, always-current JSON Schema. Summary:

| Field | Type | Default | Notes |
|---|---|---|---|
| `particles` | path | required | Directory of same-box-size, same-pixel-size MRC particles |
| `pattern` | str | `*.mrc` | Glob within `particles` |
| `pixel_size` | float \| null | auto-detected | Required if MRC headers don't agree, are missing, or are left at 1.0 Å/px |
| `subsample` | int \| null | `null` | Caps particle count via a random, seeded draw — see `ParticleSet.subsample()`. Useful for a real-world download with tens of thousands of particles, where classifying everything with every package isn't practical for a first pass |
| `subsample_seed` | int | `0` | Seeds the draw above, for a reproducible subset |
| `k` | int \| list[int] | `2` | One or more class counts to run |
| `mask.kind` | `none`\|`sphere`\|`cylinder`\|`file`\|`auto` | `auto` | `auto` = blind density-envelope sphere, no labels needed — see `docs/mask-design.md` |
| `mask.radius`, `mask.half_height`, `mask.axis`, `mask.center`, `mask.edge` | — | — | Required fields depend on `mask.kind` — see `MaskConfig` and `docs/mask-design.md` |
| `wedge.kind` | `none`\|`uniform`\|`per_particle` | `none` | See `docs/limitations.md` — most adapters ignore this today |
| `alignment_state` | `unaligned`\|`rough`\|`fine` | `fine` | See `docs/limitations.md` — `unaligned` is a hard error for every current adapter |
| `packages` | list[str] | required | Names from `stw list` |
| `mode` | `native`\|`preview` | `native` | `preview` uses lightweight approximations where available (not yet wired up) |
| `seeds` | int \| list[int] | `1` | An int N runs seeds 1..N |
| `out_dir` | path | `./stw_out` | |
| `package_options` | dict | `{}` | Per-package extra knobs, namespaced by package name |
| `jobs` | int | `1` | Parallel job slots (not yet enforced by the orchestrator) |
| `on_missing_requirement` | `skip`\|`fail` | `skip` | `fail` aborts the whole run instead of recording one package as skipped |
| `ground_truth` | path \| null | `null` | Enables ARI/AMI/V-measure scoring against known labels (self-tests, power users) |
