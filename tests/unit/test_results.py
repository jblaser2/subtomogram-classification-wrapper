"""Regression test for a real bug found via the GUI: PackageResult.to_dict()
stringified class_averages' keys but left n_per_class's keys as int, so a
caller keying off both together (the GUI's class-average panel renderer) saw
a mismatch and always fell back to a "?" particle count."""
from pathlib import Path

from stw.results import PackageResult


def test_to_dict_class_averages_and_n_per_class_share_key_type():
    result = PackageResult(
        package="hac", k=2, seed=1, status="ok",
        class_averages={1: Path("class_01.mrc"), 2: Path("class_02.mrc")},
        n_per_class={1: 16, 2: 16},
    )
    d = result.to_dict()
    assert set(d["class_averages"].keys()) == set(d["n_per_class"].keys()) == {"1", "2"}
    assert d["n_per_class"]["1"] == 16
    assert d["n_per_class"]["2"] == 16
