"""
`pyproject.toml`'s `version` and `src/stw/__init__.py`'s `__version__` are two
independent strings -- this project doesn't use a git-tag-derived versioning
scheme (e.g. hatch-vcs), so nothing enforces them staying in sync except this
test. A drift here is silent: `stw --version` and every run_report.json's
`stw_version` field would quietly report the wrong version.
"""
from pathlib import Path

import tomllib

import stw

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_init_version_matches_pyproject_version():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert stw.__version__ == pyproject["project"]["version"]
