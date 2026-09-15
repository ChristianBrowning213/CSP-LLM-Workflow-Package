"""Render compact Stage 2 diagnostic plots from frozen cubic cell-scale artifacts.

Read-only over ``outputs/cross_family_cubic_scale_panel_v1``: it consumes the
already-frozen ``*/scale_*/metrics.json`` records and writes publication-readable
PNG/PDF figures beside them. No solver, no production module, no result mutation.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

MULTIPLIERS = (1.0, 1.1, 1.2, 1.3)
TOPO_COLOR = {"PASS": "#2f855a", "PARTIAL": "#d69e2e", "FAIL": "#c53030"}
TOPO_NUM = {"FAIL": 0, "PARTIAL": 1, "PASS": 2}


def load_rows(panel_root: Path) -> list[dict[str, Any]]:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(panel_root.glob("*/scale_*/metrics.json"))]
    if len(rows) != 44:
        raise SystemExit(f"expected 44 frozen variants, found {len(rows)}")
    return rows


def _by_target(rows: list[dict[str, Any]]) -> dict[str, dict[float, dict[str, Any]]]:
    grouped: dict[str, dict[float, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["row_id"]), {})[round(float(row["scale_multiplier"]), 2)] = row
    return grouped


def plot_topology_grid(rows: list[dict[str, Any]], out: Path) -> None:
    grouped = _by_target(rows)
    order = sorted(grouped, key=lambda name: (not name.startswith("layered"), name))
    fig, ax = plt.subplots(figsize=(6.4, 5.2), constrained_layout=True)
    for y, name in enumerate(order):
        for x, mult in enumerate(MULTIPLIERS):
            row = grouped[name].get(round(mult, 2))
            status = str(row["topology_status"]) if row else "NA"
            ax.scatter(x, y, s=260, marker="s", color=TOPO_COLOR.get(status, "#cbd5e0"),
                       edgecolors="white", linewidths=1.0)
            tl = row and row.get("qlip_status") == "FEASIBLE_TIME_LIMIT"
            if tl:
                ax.text(x, y, "TL", ha="center", va="center", fontsize=6.5, color="white")
    ax.set_xticks(range(len(MULTIPLIERS)), [f"{m:.2f}x" for m in MULTIPLIERS])
    ax.set_yticks(range(len(order)), [f"{n} {grouped[n][1.0]['formula']}" for n in order])
    ax.set_xlabel("cubic edge multiplier")
    ax.set_title("Stage 2 topology by target x scale (TL = solver time limit)")
    handles = [plt.Line2D([0], [0], marker="s", linestyle="", markersize=10,
                          markerfacecolor=color, markeredgecolor="white", label=label)
               for label, color in TOPO_COLOR.items()]
    ax.legend(handles=handles, loc="lower right", framealpha=0.95, fontsize=8)
    ax.set_xlim(-0.5, len(MULTIPLIERS) - 0.5)
    ax.set_ylim(-0.7, len(order) - 0.3)
    ax.invert_yaxis()
    ax.grid(True, alpha=0.15)
    fig.savefig(out / "STAGE2_TOPOLOGY_GRID.png", dpi=220)
    fig.savefig(out / "STAGE2_TOPOLOGY_GRID.pdf")
    plt.close(fig)


def plot_multiplier_summary(rows: list[dict[str, Any]], out: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.6), constrained_layout=True)
    families = {"all": rows,
                "layered": [r for r in rows if str(r["family"]).startswith("layered")],
                "spinel": [r for r in rows if str(r["family"]) == "spinel"]}
    for ax, (title, subset) in zip(axes, families.items(), strict=True):
        counts = {m: Counter(str(r["topology_status"]) for r in subset
                             if round(float(r["scale_multiplier"]), 2) == round(m, 2)) for m in MULTIPLIERS}
        bottoms = np.zeros(len(MULTIPLIERS))
        for status in ("FAIL", "PARTIAL", "PASS"):
            vals = np.array([counts[m].get(status, 0) for m in MULTIPLIERS], dtype=float)
            ax.bar([f"{m:.2f}x" for m in MULTIPLIERS], vals, bottom=bottoms,
                   color=TOPO_COLOR[status], label=status, width=0.6)
            bottoms += vals
        ax.set_title(f"{title} (n={len(subset) // 4} targets)")
        ax.set_ylabel("target count")
    axes[0].legend(loc="upper right", fontsize=8)
    fig.suptitle("Stage 2 PASS / PARTIAL / FAIL vs multiplier")
    fig.savefig(out / "STAGE2_MULTIPLIER_COUNTS.png", dpi=220)
    fig.savefig(out / "STAGE2_MULTIPLIER_COUNTS.pdf")
    plt.close(fig)


def plot_scale_effects(rows: list[dict[str, Any]], out: Path) -> None:
    grouped = _by_target(rows)
    order = sorted(grouped, key=lambda name: (not name.startswith("layered"), name))
    fig, axes = plt.subplots(2, 2, figsize=(10.4, 8.0), constrained_layout=True)
    specs = [
        ("runtime_s", "solver wall runtime (s)", False),
        ("minimum_distance_A", "SCA minimum distance (A)", False),
        ("grid_spacing_A", "physical grid spacing (A)", False),
        ("objective", "QLIP objective", True),
    ]
    for ax, (key, label, symlog) in zip(axes.flat, specs, strict=True):
        for name in order:
            series = grouped[name]
            xs = [m for m in MULTIPLIERS if series.get(round(m, 2))]
            ys = [series[round(m, 2)].get(key) for m in xs]
            style = "-o" if name.startswith("layered") else "--s"
            ax.plot(xs, [np.nan if v is None else v for v in ys], style, markersize=4, linewidth=1.0, label=name)
        ax.set_xlabel("cubic edge multiplier")
        ax.set_ylabel(label)
        ax.set_xticks(MULTIPLIERS)
        if symlog:
            ax.set_yscale("symlog")
        ax.grid(True, alpha=0.2)
    axes.flat[0].axhline(300, color="#718096", linestyle=":", linewidth=1.0)
    axes.flat[1].legend(ncol=2, fontsize=6.5, loc="upper left")
    fig.suptitle("Stage 2 scale effects (solid = layered, dashed = spinel)")
    fig.savefig(out / "STAGE2_SCALE_EFFECTS.png", dpi=220)
    fig.savefig(out / "STAGE2_SCALE_EFFECTS.pdf")
    plt.close(fig)


def plot_objective_vs_topology(rows: list[dict[str, Any]], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.2, 4.4), constrained_layout=True)
    for row in rows:
        obj = row.get("objective")
        if obj is None:
            continue
        jitter = (hash(row["row_id"]) % 7 - 3) / 40.0
        ax.scatter(obj, TOPO_NUM.get(str(row["topology_status"]), -1) + jitter,
                   color=TOPO_COLOR.get(str(row["topology_status"]), "#cbd5e0"),
                   s=40, edgecolors="white", linewidths=0.5)
    ax.set_xscale("symlog")
    ax.set_yticks([0, 1, 2], ["FAIL", "PARTIAL", "PASS"])
    ax.set_xlabel("QLIP objective (symlog; more negative = more favorable)")
    ax.set_title("Stage 2 QLIP objective vs SCA topology")
    ax.grid(True, alpha=0.2)
    fig.savefig(out / "STAGE2_OBJECTIVE_VS_TOPOLOGY.png", dpi=220)
    fig.savefig(out / "STAGE2_OBJECTIVE_VS_TOPOLOGY.pdf")
    plt.close(fig)


def plot_transitions(rows: list[dict[str, Any]], out: Path) -> None:
    grouped = _by_target(rows)
    order = sorted(grouped, key=lambda name: (not name.startswith("layered"), name))
    fig, ax = plt.subplots(figsize=(6.6, 4.6), constrained_layout=True)
    for y, name in enumerate(order):
        series = grouped[name]
        base = TOPO_NUM.get(str(series[1.0]["topology_status"]), -1)
        best = max(TOPO_NUM.get(str(series[round(m, 2)]["topology_status"]), -1)
                   for m in MULTIPLIERS if series.get(round(m, 2)))
        worst = min(TOPO_NUM.get(str(series[round(m, 2)]["topology_status"]), -1)
                    for m in MULTIPLIERS if series.get(round(m, 2)))
        ax.plot([worst, best], [y, y], color="#a0aec0", linewidth=2.0, zorder=1)
        ax.scatter(base, y, color="#1a202c", s=70, zorder=3, label="baseline 1.00x" if y == 0 else None)
        ax.scatter(best, y, color="#2f855a", s=45, marker=">", zorder=2, label="best scaled" if y == 0 else None)
        ax.scatter(worst, y, color="#c53030", s=45, marker="<", zorder=2, label="worst scaled" if y == 0 else None)
    ax.set_yticks(range(len(order)), order)
    ax.set_xticks([0, 1, 2], ["FAIL", "PARTIAL", "PASS"])
    ax.invert_yaxis()
    ax.set_title("Stage 2 topology span: baseline vs scaled range")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(True, axis="x", alpha=0.2)
    fig.savefig(out / "STAGE2_TRANSITIONS.png", dpi=220)
    fig.savefig(out / "STAGE2_TRANSITIONS.pdf")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path,
                        default=Path("outputs/cross_family_cubic_scale_panel_v1"))
    args = parser.parse_args()
    panel_root = args.panel.resolve()
    rows = load_rows(panel_root)
    plot_topology_grid(rows, panel_root)
    plot_multiplier_summary(rows, panel_root)
    plot_scale_effects(rows, panel_root)
    plot_objective_vs_topology(rows, panel_root)
    plot_transitions(rows, panel_root)
    print(f"wrote Stage 2 plots to {panel_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
