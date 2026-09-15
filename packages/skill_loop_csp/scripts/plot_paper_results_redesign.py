"""Render actual-data figures for PAPER-RESULTS-REDESIGN-1."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_results_final_redesign"
FIG = OUT / "figures"


def rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_data(name: str, data: list[dict[str, object]]) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    with (FIG / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(data)


def save(fig, stem: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "pdf", "svg"):
        kwargs = {"dpi": 320} if suffix == "png" else {}
        fig.savefig(FIG / f"{stem}.{suffix}", bbox_inches="tight", **kwargs)
    plt.close(fig)


def short(case_id: str) -> str:
    return case_id.replace("RDX-", "").replace("CSPB", "CsPb").replace("CSSN", "CsSn")


def figure_a() -> None:
    audits = rows(OUT / "02_rediscovery" / "SPP_CASE_AUDIT.csv")
    labels = [r["formula"] for r in audits]
    coverage = [int(r["available_pair_count"]) / int(r["required_pair_count"]) for r in audits]
    write_data("figure_a_data.csv", [{"case_id": r["case_id"], "formula": r["formula"], "available_pairs": r["available_pair_count"], "required_pairs": r["required_pair_count"], "coverage_fraction": value, "production_quality": r["spp_pot_quality_status"], "valid_for_ranking": r["valid_for_ranking"], "candidate_selected": False} for r, value in zip(audits, coverage)])
    fig, ax = plt.subplots(figsize=(8.2, 4.6), constrained_layout=True)
    bars = ax.barh(np.arange(len(labels)), coverage, color="#4c78a8", edgecolor="#294861", linewidth=0.7)
    for bar, row in zip(bars, audits):
        ax.text(min(bar.get_width() + 0.015, 0.94), bar.get_y() + bar.get_height()/2,
                f"{row['available_pair_count']}/{row['required_pair_count']}", va="center", fontsize=8)
    ax.axvline(1.0, color="#222222", linewidth=1.0, linestyle="--", label="complete-pair gate")
    ax.set_yticks(np.arange(len(labels)), labels)
    ax.invert_yaxis(); ax.set_xlim(0, 1.08)
    ax.set_xlabel("Required-pair coverage fraction")
    ax.set_title("Prospective held-out recovery: evidence gate outcome", loc="left", weight="bold")
    ax.grid(axis="x", color="#d9d9d9", linewidth=0.6)
    ax.text(0.01, -0.16, "0/8 production-valid SPPs; no candidate selected, generated, or relaxed.",
            transform=ax.transAxes, fontsize=9, color="#8c2d2d")
    save(fig, "figure_a_held_out_recovery")


def figure_b() -> None:
    dof = rows(OUT / "03_factorial" / "SCAFFOLD_DOF.csv")
    sca = [r for r in rows(OUT / "04_sca" / "SCA_INITIAL.csv") if r["structure_role"] == "FACTORIAL_ALTERNATIVE"]
    case_ids = list(dict.fromkeys(r["case_id"] for r in dof))
    tight = [int(next(r["feasible_assignment_count"] for r in dof if r["case_id"] == cid and r["scaffold_type"] == "TIGHT")) for cid in case_ids]
    loose = [int(next(r["feasible_assignment_count"] for r in dof if r["case_id"] == cid and r["scaffold_type"] == "LOOSE")) for cid in case_ids]
    write_data("figure_b_data.csv", [{"case_id": cid, "tight_feasible": t, "loose_feasible": l, "correct_spp_reference_rank": "NA_INVALID_SPP", "perturbed_spp_reference_rank": "NA_INVALID_SPP", "enumerated_SCA_PASS": sum(r["case_id"] == cid and r["topology"] == "PASS" for r in sca), "enumerated_SCA_PARTIAL": sum(r["case_id"] == cid and r["topology"] == "PARTIAL" for r in sca)} for cid, t, l in zip(case_ids, tight, loose)])
    fig, axes = plt.subplots(1, 3, figsize=(12.4, 4.2), constrained_layout=True)
    x = np.arange(len(case_ids)); width = 0.38
    axes[0].bar(x-width/2, tight, width, label="Tight", color="#72b7b2")
    axes[0].bar(x+width/2, loose, width, label="Loose", color="#f2a541")
    axes[0].set_xticks(x, [short(cid) for cid in case_ids], rotation=55, ha="right", fontsize=7)
    axes[0].set_ylabel("Distinct feasible structures"); axes[0].set_title("A  Scaffold degrees of freedom", loc="left", weight="bold")
    axes[0].set_ylim(0, 2.6); axes[0].legend(frameon=False, fontsize=8); axes[0].grid(axis="y", color="#dddddd", linewidth=0.6)
    axes[1].set_xlim(0, 1); axes[1].set_ylim(0, 1); axes[1].axis("off")
    axes[1].set_title("B  Within-space reference rank", loc="left", weight="bold")
    axes[1].text(0.5, 0.58, "Not estimable", ha="center", va="center", fontsize=16, weight="bold")
    axes[1].text(0.5, 0.40, "0/8 SPPs passed the\nproduction ranking gate", ha="center", va="center", fontsize=10, color="#8c2d2d")
    counts = Counter(r["topology"] for r in sca)
    order = [k for k in ("PASS", "PARTIAL", "FAIL") if counts[k]]
    colors = {"PASS": "#54a24b", "PARTIAL": "#eeca3b", "FAIL": "#e45756"}
    axes[2].bar(order, [counts[k] for k in order], color=[colors[k] for k in order])
    axes[2].set_ylabel("Enumerated alternatives"); axes[2].set_title("C  SCA topology (evaluation only)", loc="left", weight="bold")
    axes[2].grid(axis="y", color="#dddddd", linewidth=0.6)
    fig.suptitle("Scaffold × SPP factorial: search space exists, causal contrast gated", weight="bold")
    save(fig, "figure_b_scaffold_spp_factorial")


def figure_c() -> None:
    search = rows(OUT / "08_nasicon" / "NASICON_SEARCH_SPACE.csv")
    audits = {r["case_id"]: r for r in rows(OUT / "08_nasicon" / "NASICON_SPP_CASE_AUDIT.csv")}
    labels = [r["formula"] for r in search]; x = np.arange(len(search))
    feasible = [int(r["distinct_feasible_assignments"]) for r in search]
    coverage = [int(audits[r["case_id"]]["available_pair_count"]) / int(audits[r["case_id"]]["required_pair_count"]) for r in search]
    write_data("figure_c_data.csv", [{"case_id": r["case_id"], "formula": r["formula"], "distinct_feasible": n, "pair_coverage_fraction": cov, "production_quality": audits[r["case_id"]]["spp_pot_quality_status"], "reference_rank": "NA_INVALID_SPP", "solver_status": "NOT_RUN_INVALID_SPP_QUALITY", "objective_parity": "NA"} for r, n, cov in zip(search, feasible, coverage)])
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 3.9), constrained_layout=True)
    axes[0].bar(x, feasible, color="#f2a541"); axes[0].set_xticks(x, labels, rotation=25, ha="right", fontsize=8)
    axes[0].set_ylabel("Distinct feasible structures"); axes[0].set_title("A  Registered search space", loc="left", weight="bold"); axes[0].grid(axis="y", color="#dddddd", linewidth=0.6)
    axes[1].bar(x, coverage, color="#4c78a8"); axes[1].axhline(1.0, color="#222222", linestyle="--", linewidth=1)
    axes[1].set_xticks(x, labels, rotation=25, ha="right", fontsize=8); axes[1].set_ylim(0, 1.08)
    axes[1].set_ylabel("Required-pair coverage"); axes[1].set_title("B  Numerical SPP coverage", loc="left", weight="bold"); axes[1].grid(axis="y", color="#dddddd", linewidth=0.6)
    axes[2].set_xlim(0, 1); axes[2].set_ylim(-0.5, len(search)-0.5); axes[2].set_xticks([]); axes[2].set_yticks(range(len(search)), labels)
    for i, row in enumerate(search):
        audit = audits[row["case_id"]]
        label = "INCOMPLETE" if audit["coverage_class"] == "INSUFFICIENT" else audit["spp_pot_quality_status"].upper()
        axes[2].text(0.5, i, f"{label} • NOT RUN", ha="center", va="center", fontsize=9, color="#8c2d2d")
    axes[2].invert_yaxis(); axes[2].set_title("C  Solver / objective parity", loc="left", weight="bold")
    for spine in axes[2].spines.values(): spine.set_visible(False)
    fig.suptitle("NASICON extension: no valid complete SPP-guided experiment", weight="bold")
    save(fig, "figure_c_nasicon_extension")


def main() -> None:
    figure_a(); figure_b(); figure_c()
    print("PASS rendered 3 figures × PNG/PDF/SVG")


if __name__ == "__main__":
    main()
