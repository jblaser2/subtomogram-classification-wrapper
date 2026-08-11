"""Top-level comparison entry point the orchestrator calls after every package
finishes: builds the agreement matrix + consensus scores, optionally renders
the figure, and packages it as one JSON-serializable report."""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from stw.compare.matrix import PackageLabels, consensus_scores
from stw.compare.metrics import pairwise_ari


@dataclass
class ComparisonReport:
    package_names: list[str]
    pairwise_ari: dict[str, dict] = field(default_factory=dict)  # "A|B" -> {ari, n_shared}
    consensus: dict = field(default_factory=dict)
    figure_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "package_names": self.package_names,
            "pairwise_ari": self.pairwise_ari,
            "consensus": self.consensus,
            "figure_path": str(self.figure_path) if self.figure_path else None,
        }


def build_comparison(
    packages: list[PackageLabels],
    *,
    out_png: str | Path | None = None,
    warnings: dict[str, list[str]] | None = None,
) -> ComparisonReport:
    if len(packages) < 2:
        raise ValueError("comparison needs at least 2 successful packages to compare")

    pairwise: dict[str, dict] = {}
    for a, b in combinations(packages, 2):
        score, n_shared = pairwise_ari(a.labels, b.labels)
        pairwise[f"{a.name}|{b.name}"] = {"ari": score, "n_shared": n_shared}

    consensus = consensus_scores(packages)

    figure_path: Path | None = None
    if out_png is not None:
        try:
            from stw.compare.figure import render_comparison_figure

            render_comparison_figure(packages, out_png, warnings=warnings)
            figure_path = Path(out_png)
        except ImportError:
            pass  # matplotlib (the `viz` extra) not installed — numeric report still built

    return ComparisonReport(
        package_names=[p.name for p in packages],
        pairwise_ari=pairwise,
        consensus=consensus,
        figure_path=figure_path,
    )
