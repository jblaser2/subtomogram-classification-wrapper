"""Rendering for the cross-package comparison — ported from the plotting half
of STA's `gen_cross_pkg_correlation.py` (`plot_combined_matrix`,
`draw_ari_legend`, `plot_consensus`), unchanged in spirit, generalized to an
arbitrary `list[PackageLabels]`. Requires the `viz` extra (matplotlib)."""
from __future__ import annotations

from pathlib import Path

from stw.compare.matrix import (
    CombinedMatrix,
    PackageLabels,
    build_combined_matrix,
    consensus_scores,
)


def render_comparison_figure(
    packages: list[PackageLabels], out_png: str | Path, warnings: dict[str, list[str]] | None = None
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    combined = build_combined_matrix(packages)
    n_pairs = len(packages) * (len(packages) - 1) // 2
    show_ari_panel = n_pairs <= 10
    n_combined = combined.matrix.shape[0]

    mat_w = max(6.0, n_combined * 0.95)
    width_ratios = [mat_w] + ([2.6] if show_ari_panel else []) + [3.2]
    fig, panel_axes = plt.subplots(
        1,
        len(width_ratios),
        figsize=(sum(width_ratios) + 1.5, max(6.5, n_combined * 0.85)),
        gridspec_kw={"width_ratios": width_ratios, "wspace": 0.45},
    )
    mat_ax = panel_axes[0]
    cons_ax = panel_axes[-1]

    fig.suptitle(
        f"Cross-Package Particle Agreement ({len(packages)} methods)",
        fontsize=15,
        fontweight="bold",
        y=1.02,
    )
    caption = (
        "Each cell: % of the row package's particles that landed in that column's "
        "class for the column package (raw count below)."
    )
    if warnings:
        flagged = [f"{name}: {'; '.join(msgs)}" for name, msgs in warnings.items() if msgs]
        if flagged:
            caption += "  |  " + "  ·  ".join(flagged)
    fig.text(0.5, 0.975, caption, fontsize=9.5, ha="center", style="italic", color="#444444", wrap=True)

    im_ref = _plot_combined_matrix(mat_ax, combined)
    if show_ari_panel:
        _draw_ari_legend(panel_axes[1], combined.ari_lookup)
    _plot_consensus(cons_ax, packages)

    plt.tight_layout(rect=[0, 0, 0.95, 0.94])
    if im_ref is not None:
        cbar_ax = fig.add_axes((0.97, 0.15, 0.015, 0.7))
        cbar = fig.colorbar(im_ref, cax=cbar_ax)
        cbar.set_label("% of row package's particles\n(row-normalized)", fontsize=10)
        cbar.ax.tick_params(labelsize=9)

    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(out_png), dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_combined_matrix(ax, combined: CombinedMatrix):
    import matplotlib.pyplot as plt
    import numpy as np

    mat, counts = combined.matrix, combined.counts
    n = mat.shape[0]

    cmap = plt.cm.Blues.copy()
    cmap.set_bad("#e7e7e7")
    im = ax.imshow(np.ma.masked_invalid(mat), vmin=0, vmax=1, cmap=cmap, aspect="equal")

    ax.set_xticks(range(n))
    ax.set_xticklabels(combined.tick_labels, fontsize=9, rotation=45, ha="right")
    ax.set_yticks(range(n))
    ax.set_yticklabels(combined.tick_labels, fontsize=9)

    ax.set_xticks(np.arange(-0.5, n, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.2)
    ax.tick_params(which="minor", length=0)
    for start, _ in combined.block_bounds[1:]:
        ax.axhline(start - 0.5, color="black", linewidth=1.6)
        ax.axvline(start - 0.5, color="black", linewidth=1.6)
    for spine in ax.spines.values():
        spine.set_linewidth(1.6)

    small_grid = n <= 8
    pct_fs, raw_fs, self_fs = (14, 8, 9) if small_grid else (8, 6, 7)
    for i in range(n):
        for j in range(n):
            if np.isnan(mat[i, j]):
                if counts[i, j] > 0:
                    ax.text(
                        j, i, f"n={counts[i, j]}", ha="center", va="center",
                        fontsize=self_fs, color="#666666", style="italic",
                    )
                continue
            pct, raw = mat[i, j], counts[i, j]
            color = "white" if pct > 0.55 else "#08306b"
            ax.text(
                j, i - (0.14 if small_grid else 0.1), f"{pct:.0%}",
                ha="center", va="center", fontsize=pct_fs, fontweight="bold", color=color,
            )
            ax.text(
                j, i + (0.26 if small_grid else 0.22), f"{raw}",
                ha="center", va="center", fontsize=raw_fs, color=color,
            )

    ax.set_title(
        "Gray diagonal blocks = each package vs. itself (class-size reference only)",
        fontsize=9, style="italic", color="#444444", pad=10,
    )
    return im


def _draw_ari_legend(ax, ari_lookup: dict[tuple[str, str], tuple[float, int]]) -> None:
    ax.axis("off")
    if not ari_lookup:
        return
    lines = [
        f"{a} x {b}\nARI = {v:.2f}  (n={n_shared})" for (a, b), (v, n_shared) in ari_lookup.items()
    ]
    ax.text(0.0, 1.0, "Pairwise ARI", fontsize=11, fontweight="bold", va="top", ha="left",
            transform=ax.transAxes)
    ax.text(0.0, 0.90, "\n\n".join(lines), fontsize=9.5, va="top", ha="left", linespacing=1.8,
            transform=ax.transAxes,
            bbox={"boxstyle": "round", "facecolor": "#f7f7f7", "edgecolor": "#cccccc"})


def _plot_consensus(ax, packages: list[PackageLabels]) -> None:
    result = consensus_scores(packages)
    n = result["n_shared"]
    if n == 0:
        ax.text(0.5, 0.5, "No common particles", transform=ax.transAxes, ha="center", va="center")
        return

    import matplotlib.pyplot as plt
    import numpy as np

    n_pkgs = len(packages)
    counts = [result["counts"].get(v, 0) for v in range(1, n_pkgs + 1)]
    colors = plt.cm.Blues(np.linspace(0.35, 0.9, len(counts)))
    bars = ax.bar(range(1, n_pkgs + 1), counts, color=colors, edgecolor="white", linewidth=0.5)

    for bar, cnt in zip(bars, counts):
        if cnt > 0:
            pct = 100 * cnt / n
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + n * 0.015,
                    f"{cnt}\n({pct:.0f}%)", ha="center", va="bottom", fontsize=10, fontweight="bold")

    crowded = n_pkgs > 6
    ax.set_xticks(range(1, n_pkgs + 1))
    ax.set_xticklabels([f"{v}/{n_pkgs}" for v in range(1, n_pkgs + 1)],
                        fontsize=9 if crowded else 11, fontweight="bold",
                        rotation=45 if crowded else 0, ha="right" if crowded else "center")
    ax.set_xlabel(f"# methods agreeing with {result['reference']}", fontsize=11, labelpad=6)
    ax.set_ylabel("# particles", fontsize=11)
    ax.set_ylim(0, max(counts) * 1.22 if max(counts) else 1)
    ax.set_title(
        f"Per-particle consensus\n(n={n} shared; {result['n_full_agreement']} = "
        f"{100 * result['n_full_agreement'] / n:.0f}% fully agree)",
        fontsize=11, pad=8,
    )
    ax.tick_params(axis="y", labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
