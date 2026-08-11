#!/usr/bin/env python3
"""
Generate the tiny, committed synthetic fixture used by unit/integration tests
and `stw selftest --native`. Two classes with a real, deliberately easy
structural difference (a bright blob at a different location per class) plus
noise — small enough (24^3 box, 32 particles) that the whole repo's fixture
directory stays well under 1 MB, but real enough that HAC/PyTom/EMAN2-style
methods should all recover a non-degenerate split.

Usage: python3 tests/fixtures/make_fixture.py
"""
import csv
from pathlib import Path

import mrcfile
import numpy as np

OUT = Path(__file__).parent / "tiny"
BOX = 24
N_PER_CLASS = 16
PIXEL_SIZE = 5.0
RNG_SEED = 42


def _blob(center, box=BOX, sigma=2.5):
    grid = np.mgrid[0:box, 0:box, 0:box]
    d2 = sum((g - c) ** 2 for g, c in zip(grid, center, strict=True))
    return np.exp(-d2 / (2 * sigma**2))


def main() -> None:
    rng = np.random.default_rng(RNG_SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    base = _blob((12, 12, 12), sigma=4.0)  # shared "body" every particle has
    class_feature = {
        1: _blob((8, 12, 12), sigma=2.0),
        2: _blob((16, 12, 12), sigma=2.0),
    }

    rows = []
    for cls, feature in class_feature.items():
        for i in range(N_PER_CLASS):
            noise = rng.normal(0, 0.15, size=(BOX, BOX, BOX)).astype(np.float32)
            vol = (base + 0.8 * feature + noise).astype(np.float32)
            name = f"particle_c{cls}_{i:03d}.mrc"
            with mrcfile.new(OUT / name, overwrite=True) as m:
                m.set_data(vol)
                m.voxel_size = PIXEL_SIZE
            rows.append((name, cls))

    rng.shuffle(rows)
    with (OUT / "ground_truth.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["particle", "label"])
        w.writerows(rows)

    print(f"wrote {len(rows)} particles + ground_truth.csv to {OUT}")


if __name__ == "__main__":
    main()
