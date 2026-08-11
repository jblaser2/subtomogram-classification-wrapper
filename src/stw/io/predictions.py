"""
The one predictions-CSV schema every adapter writes: `particle,class_int,class_name`.

STA had two competing conventions (adapters wrote `file,pred_label`; the
eval/FSC/comparison layer consumed `particle,class_int[,class_name]`) bridged
by a whole intermediate layer of `standardize_*.py`/`extract_*_classes.py`
scripts. Collapsing to one schema here deletes that layer entirely — every
`Adapter.collect()` returns a `dict[str, int]` and this module is the only
place that touches the file format.
"""
from __future__ import annotations

import csv
from pathlib import Path


def write_predictions(path: str | Path, labels: dict[str, int], class_names: dict[int, str] | None = None) -> None:
    class_names = class_names or {}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["particle", "class_int", "class_name"])
        for particle, cls in sorted(labels.items()):
            w.writerow([particle, cls, class_names.get(cls, f"class_{cls}")])


def read_predictions(path: str | Path) -> dict[str, int]:
    with Path(path).open() as f:
        reader = csv.DictReader(f)
        return {row["particle"]: int(row["class_int"]) for row in reader}


def read_legacy_predictions(path: str | Path) -> dict[str, int]:
    """Reads the `file,pred_label` schema STA's vendored preview-mode scripts
    still write natively (that project's own original convention, predating
    the `particle,class_int,class_name` schema above). Adapters that shell out
    to a vendored script use this to bridge into the one schema everything
    else in `stw` uses — the same kind of bridging STA needed a whole
    `standardize_*.py` layer for, kept here to exactly one function."""
    with Path(path).open() as f:
        reader = csv.DictReader(f)
        return {row["file"]: int(row["pred_label"]) for row in reader}
