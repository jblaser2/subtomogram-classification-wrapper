# conda-forge recipe (draft, not submitted)

`meta.yaml` is a draft recipe for a future conda-forge submission — nothing
has been submitted or published. Needs, in order:

1. A real PyPI release (see `../../docs/publishing.md`) — conda-forge builds
   from the published sdist, not GitHub directly.
2. Fill in `source.sha256` with that release's real sdist hash.
3. Fork `github.com/conda-forge/staged-recipes`, add this file at
   `recipes/subtomogram-classification-wrapper/meta.yaml`, open a PR.
4. Ongoing maintenance afterward (conda-forge expects the recipe maintainer
   to keep the recipe in sync with new releases) — a real commitment, not a
   one-time submission.

See https://conda-forge.org/docs/maintainer/adding_pkgs.html for the full
process.
