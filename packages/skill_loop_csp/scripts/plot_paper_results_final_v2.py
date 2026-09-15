"""Plot the actual-data scaffold × SPP factorial result."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_results_extension_v3"
DATA = OUT / "MAIN_PAPER_FIGURE_DATA.csv"


def main() -> None:
    with DATA.open(encoding="utf-8-sig", newline="") as handle:
        data = list(csv.DictReader(handle))
    labels = [row["composition"] for row in data]
    x = np.arange(len(data))
    strict = np.array([row["cohort"] == "STRICT_PRIMARY" for row in data])
    colors = np.where(strict, "#276FBF", "#9C6ADE")
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.9), constrained_layout=True)

    width = 0.35
    axes[0].bar(x - width / 2, [int(row["tight_feasible_count"]) for row in data], width, label="Tight", color="#737373")
    axes[0].bar(x + width / 2, [int(row["loose_feasible_count"]) for row in data], width, label="Loose", color=colors)
    axes[0].set_ylabel("Feasible structures")
    axes[0].set_title("A  Search-space freedom", loc="left", fontweight="bold")
    axes[0].set_ylim(0, 2.45)
    axes[0].set_yticks([0, 1, 2])
    axes[0].legend(frameon=False, ncol=2, fontsize=8)

    correct = [int(row["correct_reference_rank"]) for row in data]
    perturbed = [int(row["perturbed_reference_rank"]) for row in data]
    axes[1].plot(x, correct, "o-", color="#137A70", label="Correct SPP", linewidth=1.5)
    axes[1].plot(x, perturbed, "s--", color="#B35C00", label="Perturbed SPP", linewidth=1.3)
    axes[1].set_ylabel("Reference role rank (lower is better)")
    axes[1].set_title("B  Objective effect", loc="left", fontweight="bold")
    axes[1].set_ylim(0.75, 2.25)
    axes[1].set_yticks([1, 2])
    axes[1].legend(frameon=False, fontsize=8)

    metrics = ["correct_reference_match", "correct_SCA_topology_PASS", "correct_relaxed_reference_match"]
    metric_labels = ["Initial reference", "SCA topology", "Relaxed reference"]
    for yi, (metric, label) in enumerate(zip(metrics, metric_labels)):
        values = np.array([row[metric] == "True" for row in data])
        axes[2].scatter(x[values], np.full(values.sum(), yi), marker="o", s=55, color=colors[values], edgecolor="black", linewidth=0.4)
        axes[2].scatter(x[~values], np.full((~values).sum(), yi), marker="x", s=55, color="#B3261E", linewidth=1.5)
    axes[2].set_yticks(range(3), metric_labels)
    axes[2].set_ylim(-0.6, 2.6)
    axes[2].set_title("C  Selected-candidate quality", loc="left", fontweight="bold")

    for ax in axes:
        ax.set_xticks(x, labels, rotation=45, ha="right", fontsize=8)
        ax.grid(axis="y", linewidth=0.45, alpha=0.35)
        ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.5, -0.02, "Blue: strict target-excluded cohort; purple: supplemented pair-coverage cohort", ha="center", fontsize=8)
    figure_dir = OUT / "03_scaffold_spp"
    fig.savefig(figure_dir / "SCAFFOLD_SPP_MAIN_RESULT.png", dpi=350, bbox_inches="tight")
    fig.savefig(figure_dir / "SCAFFOLD_SPP_MAIN_RESULT.pdf", bbox_inches="tight")
    fig.savefig(figure_dir / "SCAFFOLD_SPP_MAIN_RESULT.svg", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
