from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tiny_fixture_dir() -> Path:
    d = FIXTURES_DIR / "tiny"
    if not (d / "ground_truth.csv").exists():
        pytest.skip("tiny fixture not generated — run tests/fixtures/make_fixture.py")
    return d
