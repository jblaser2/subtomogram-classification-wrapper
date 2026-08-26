"""
HAC Baseline — a generic, package-independent classification control:
Pearson cross-correlation distance on masked voxels (no PCA/embedding step) +
Ward-linkage hierarchical clustering. Ported from STA's
`packages/hac_baseline/scripts/run_hac_baseline.py`.

This is Tier A (vendored, zero external dependencies beyond stw's own numpy/
scipy/mrcfile) and the first Adapter implementation — it locks the contract
in M1 before any package requiring an install is added.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import cophenet, fcluster, linkage
from scipy.spatial.distance import squareform

from stw.adapters.base import Adapter, PlannedStep
from stw.averaging import class_averages
from stw.capabilities import Capabilities
from stw.io.mrc import load_mrc, save_mrc
from stw.io.predictions import write_predictions
from stw.progress import NullSink, ProgressSink
from stw.requirements import InstallTier
from stw.results import PackageResult
from stw.spec import Job, MaskKind, WedgeKind


class HACBaselineAdapter(Adapter):
    name = "hac"
    display_name = "HAC Baseline"
    tier = InstallTier.A_VENDORED
    algorithm = "Correlation distance + Ward-HAC — a generic, package-independent control."
    requirements = ()  # numpy/scipy/mrcfile are stw's own core dependencies
    steps = ("load", "distance_matrix", "cluster", "class_averages")
    capabilities = Capabilities(
        mask_kinds=frozenset({MaskKind.NONE, MaskKind.SPHERE, MaskKind.CYLINDER, MaskKind.FILE, MaskKind.AUTO}),
        wedge=frozenset({WedgeKind.NONE}),
        deterministic=True,
        seed_semantics="none",  # Ward linkage has no RNG at all
        gpu="unused",
        emits_native_class_averages=True,
        min_particles=4,
    )

    def plan(self, job: Job) -> list[PlannedStep]:
        return [
            PlannedStep(name=s, argv=["<in-process>", self.name, s], cached=False) for s in self.steps
        ]

    def run(self, job: Job, progress: ProgressSink | None = None) -> PackageResult:
        sink = progress or NullSink()
        sink.start_job(self.name, list(self.steps))
        start = time.time()
        try:
            labels, n_per_class = self._classify(job, sink)
            write_predictions(job.predictions_csv, labels)

            sink.step(self.name, "class_averages", 4, len(self.steps))
            averages, counts = class_averages(job.particles.particle_dir, labels)
            avg_dir = job.workdir / "class_averages"
            avg_paths = {}
            for cls, vol in averages.items():
                path = avg_dir / f"class_{cls:02d}.mrc"
                save_mrc(path, vol, pixel_size=job.particles.pixel_size)
                avg_paths[cls] = path

            elapsed = time.time() - start
            sink.finish_job(self.name, ok=True, message=f"{elapsed:.1f}s")
            return PackageResult(
                package=self.name, k=job.k, seed=job.seed, status="ok",
                predictions=job.predictions_csv, labels=labels,
                class_averages=avg_paths, n_per_class=counts, elapsed_sec=elapsed,
            )
        except Exception as e:
            sink.finish_job(self.name, ok=False, message=str(e))
            return PackageResult(package=self.name, k=job.k, seed=job.seed, status="failed", error=str(e))

    def _classify(self, job: Job, sink: ProgressSink) -> tuple[dict[str, int], dict[int, int]]:
        sink.step(self.name, "load", 1, len(self.steps))
        files = list(job.particles.files)
        if job.mask_path is not None:
            mask = load_mrc(job.mask_path) > 0.5
        else:
            mask = np.ones((job.particles.box,) * 3, dtype=bool)

        vectors = np.empty((len(files), int(mask.sum())), dtype=np.float64)
        for i, name in enumerate(files):
            vol = load_mrc(job.particles.path_for(name))
            vectors[i] = vol[mask]

        cache_path = job.cache_dir / f"ccmatrix_{job.mask_spec.cache_key()}.npy"
        sink.step(self.name, "distance_matrix", 2, len(self.steps))
        if cache_path.exists():
            cc = np.load(cache_path)
        else:
            cc = np.corrcoef(vectors)
            job.cache_dir.mkdir(parents=True, exist_ok=True)
            np.save(cache_path, cc)

        dist = 1.0 - cc
        np.fill_diagonal(dist, 0.0)
        dist = (dist + dist.T) / 2.0
        condensed = squareform(dist, checks=False)

        sink.step(self.name, "cluster", 3, len(self.steps))
        z = linkage(condensed, method="ward")
        coph_corr, _ = cophenet(z, condensed)
        (job.workdir / "cophenetic_correlation.txt").parent.mkdir(parents=True, exist_ok=True)
        Path(job.workdir / "cophenetic_correlation.txt").write_text(f"{coph_corr:.6f}\n")

        raw_labels = fcluster(z, t=job.k, criterion="maxclust")
        labels = {name: int(lab) for name, lab in zip(files, raw_labels)}
        n_per_class = {c: int((raw_labels == c).sum()) for c in sorted(set(raw_labels))}
        return labels, n_per_class
