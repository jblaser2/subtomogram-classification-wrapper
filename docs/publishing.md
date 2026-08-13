# Publishing a release (PyPI)

Not automated — this is a deliberate hand-off. Publishing claims the package
name permanently and is visible to the world under your account, so it
should be a decision you make explicitly, not something CI does silently.

## Prep already done (verified 2026-08-13)

- Package name **`subtomogram-classification-wrapper`** confirmed available
  on PyPI (checked via `pypi.org/pypi/<name>/json` returning 404).
- `python -m build` produces a clean sdist + wheel; `twine check dist/*`
  passes on both.
- Installed the built wheel into a fresh venv and ran a real classification
  (HAC Baseline against the tiny fixture) successfully — the package is
  genuinely installable and functional, not just metadata-valid.

## To actually publish

**Option A — manual, one-time (simplest):**

```console
python -m build                       # if dist/ isn't already up to date
twine check dist/*                    # should print PASSED for both files
twine upload dist/*                   # prompts for your PyPI credentials/API token
```

Use a scoped API token (pypi.org → Account settings → API tokens), not your
account password — `twine upload -u __token__ -p <your-token> dist/*` or let
`twine` prompt.

**Option B — GitHub Actions trusted publishing (recommended for repeat
releases, no stored secret):** `.github/workflows/release.yml` is already
wired up to publish automatically whenever you push a tag matching `v*`, but
it will only succeed once you configure PyPI's "trusted publisher" for this
exact repo/workflow:

1. Create the project on PyPI first (Option A, once) — trusted publishing
   for a *new* project name can also be pre-registered without publishing
   anything yet, via PyPI → "Publishing" → "Add a pending publisher", if you
   prefer to skip the manual first upload entirely.
2. On the PyPI project's page → Publishing → add a trusted publisher:
   - Owner: `jblaser2`, repo: `subtomogram-classification-wrapper`
   - Workflow filename: `release.yml`
   - Environment name: `pypi` (matches what the workflow declares)
3. Push a tag: `git tag v0.1.0 && git push origin v0.1.0`.

Until that trusted-publisher configuration exists, the publish job in
`release.yml` will simply fail (safely — it can't accidentally publish
without it), and the build+check job still runs and reports pass/fail on
every tag push either way.

## Versioning

Bump `version` in `pyproject.toml` before tagging — this project doesn't yet
use a git-tag-derived versioning scheme (e.g. `hatch-vcs`), so the two must
be kept in sync manually for now.
