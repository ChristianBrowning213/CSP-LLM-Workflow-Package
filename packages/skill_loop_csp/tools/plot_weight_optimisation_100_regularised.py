"""Generate documentation plots for the regularised SPP weight sweep."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = REPO_ROOT / "test_workdir" / "weight_optimisation_100_regularised" / "config_metrics.csv"
INPUT_SUMMARY = REPO_ROOT / "test_workdir" / "weight_optimisation_100_regularised" / "WEIGHT_OPTIMISATION_SUMMARY.json"
OUT_DIR = REPO_ROOT / "docs" / "assets" / "weight_optimisation_100_regularised"
CONFIG_ORDER = ["A", "B", "C", "D", "E", "F"]


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    parsed = _as_float(value)
    return int(parsed) if parsed is not None else 0


def _load_rows() -> list[dict[str, Any]]:
    if not INPUT_CSV.is_file():
        raise FileNotFoundError(f"Required input CSV not found: {INPUT_CSV}")
    with INPUT_CSV.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    by_config = {str(row.get("config_id") or ""): row for row in rows}
    return [by_config[key] for key in CONFIG_ORDER if key in by_config]


def _save(fig: plt.Figure, filename: str, outputs: list[str]) -> None:
    path = OUT_DIR / filename
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    outputs.append(str(path.relative_to(REPO_ROOT)))


def _style_axes(ax: plt.Axes, title: str, ylabel: str, xlabel: str = "Config") -> None:
    ax.set_title(title, fontsize=13, weight="bold")
    ax.set_ylabel(ylabel)
    ax.set_xlabel(xlabel)
    ax.grid(axis="y", alpha=0.25, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _colors(configs: list[str]) -> list[str]:
    palette = {
        "A": "#7a7f87",
        "B": "#c76f3a",
        "C": "#1f7a4d",
        "D": "#5f6bb8",
        "E": "#8c5aa8",
        "F": "#b33a3a",
    }
    return [palette.get(config, "#4c78a8") for config in configs]


def plot_final_cif_rate(rows: list[dict[str, Any]], outputs: list[str]) -> None:
    configs = [str(row["config_id"]) for row in rows]
    values = [_as_float(row.get("final_cif_rate")) or 0.0 for row in rows]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    bars = ax.bar(configs, values, color=_colors(configs), edgecolor="#333333", linewidth=0.8)
    _style_axes(ax, "Final CIF Rate By Configuration", "Final CIF rate")
    ax.set_ylim(0, max(values + [1.0]) * 1.08)
    for bar, value, config in zip(bars, values, configs):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.015, f"{value:.2f}", ha="center", va="bottom", fontsize=9)
        if config == "C":
            ax.annotate(
                "recommended default",
                xy=(bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, 45),
                textcoords="offset points",
                ha="center",
                arrowprops={"arrowstyle": "->", "color": "#1f7a4d"},
                color="#1f7a4d",
                fontsize=9,
            )
        if config == "F":
            ax.annotate(
                "high yield,\ncontact-unsafe",
                xy=(bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, 45),
                textcoords="offset points",
                ha="center",
                arrowprops={"arrowstyle": "->", "color": "#b33a3a"},
                color="#b33a3a",
                fontsize=9,
            )
    fig.text(0.02, 0.01, "Diagnostic workflow metric; not physical validation.", fontsize=8, color="#555555")
    _save(fig, "final_cif_rate_by_config.png", outputs)


def plot_short_contacts(rows: list[dict[str, Any]], outputs: list[str]) -> None:
    configs = [str(row["config_id"]) for row in rows]
    lt18 = [_as_int(row.get("short_contact_lt_1p8_count")) for row in rows]
    lt15 = [_as_int(row.get("short_contact_lt_1p5_count")) for row in rows]
    x = range(len(configs))
    width = 0.36
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.bar([i - width / 2 for i in x], lt18, width=width, label="<1.8 A warnings", color="#e0a33a", edgecolor="#333333", linewidth=0.6)
    ax.bar([i + width / 2 for i in x], lt15, width=width, label="<1.5 A safety failures", color="#b33a3a", edgecolor="#333333", linewidth=0.6)
    _style_axes(ax, "Short-Contact Warnings By Configuration", "Count")
    ax.set_xticks(list(x), configs)
    ax.legend(frameon=False)
    for i, (config, fail_count) in enumerate(zip(configs, lt15)):
        if fail_count:
            ax.annotate(
                "safety failure",
                xy=(i + width / 2, fail_count),
                xytext=(0, 28),
                textcoords="offset points",
                ha="center",
                arrowprops={"arrowstyle": "->", "color": "#b33a3a"},
                color="#b33a3a",
                fontsize=9,
            )
            ax.scatter([i + width / 2], [fail_count], s=110, facecolors="none", edgecolors="#b33a3a", linewidths=2)
    fig.text(0.02, 0.01, "<1.5 A contacts are treated as default-selection disqualifiers pending case audit.", fontsize=8, color="#555555")
    _save(fig, "short_contact_warnings_by_config.png", outputs)


def plot_rule_rank(rows: list[dict[str, Any]], outputs: list[str]) -> None:
    configs = [str(row["config_id"]) for row in rows]
    values = [_as_float(row.get("rank_score_rule_only")) or 0.0 for row in rows]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.plot(configs, values, marker="o", color="#345995", linewidth=2.2)
    ax.scatter(configs, values, s=90, color=_colors(configs), edgecolor="#222222", zorder=3)
    _style_axes(ax, "Rule-Only Rank Score By Configuration", "Rule-only rank score")
    ax.set_ylim(min(values) - 0.15, max(values) + 0.25)
    for config, value in zip(configs, values):
        ax.text(config, value + 0.035, f"{value:.3f}", ha="center", fontsize=9)
    c_value = values[configs.index("C")]
    f_value = values[configs.index("F")]
    ax.annotate("C selected:\ncontact-safe default", xy=("C", c_value), xytext=(-55, 55), textcoords="offset points", arrowprops={"arrowstyle": "->", "color": "#1f7a4d"}, color="#1f7a4d", fontsize=9)
    ax.annotate("F ranks highest\nbut contact-unsafe", xy=("F", f_value), xytext=(-75, 45), textcoords="offset points", arrowprops={"arrowstyle": "->", "color": "#b33a3a"}, color="#b33a3a", fontsize=9)
    fig.text(0.02, 0.01, "Rank combines yield, QLIP status, rule score, contact warnings, and infrastructure failures.", fontsize=8, color="#555555")
    _save(fig, "rule_rank_score_by_config.png", outputs)


def plot_llm_alignment(rows: list[dict[str, Any]], outputs: list[str]) -> bool:
    llm_rows = [row for row in rows if str(row.get("config_id")) in {"A", "C", "F"} and _as_float(row.get("mean_llm_score")) is not None]
    if not llm_rows:
        print("Warning: no mean_llm_score values found; skipping LLM alignment plot.", file=sys.stderr)
        return False
    configs = [str(row["config_id"]) for row in llm_rows]
    values = [_as_float(row.get("mean_llm_score")) or 0.0 for row in llm_rows]
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    bars = ax.bar(configs, values, color=_colors(configs), edgecolor="#333333", linewidth=0.8)
    _style_axes(ax, "Live LLM Robocrys Intent Alignment", "Mean LLM alignment score")
    ax.set_ylim(0, max(values + [0.35]) * 1.18)
    for bar, value, config in zip(bars, values, configs):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.008, f"{value:.3f}", ha="center", va="bottom", fontsize=9)
        if config == "C":
            ax.annotate("improves over A;\n<1.5 A = 0", xy=(bar.get_x() + bar.get_width() / 2, value), xytext=(0, 38), textcoords="offset points", ha="center", arrowprops={"arrowstyle": "->", "color": "#1f7a4d"}, color="#1f7a4d", fontsize=9)
        if config == "F":
            ax.annotate("highest LLM;\ncontact-unsafe", xy=(bar.get_x() + bar.get_width() / 2, value), xytext=(0, 38), textcoords="offset points", ha="center", arrowprops={"arrowstyle": "->", "color": "#b33a3a"}, color="#b33a3a", fontsize=9)
    fig.text(0.02, 0.01, "Semantic/motif intent score only; not stability or experimental validation.", fontsize=8, color="#555555")
    _save(fig, "llm_alignment_rescored_configs.png", outputs)
    return True


def plot_yield_tradeoff(rows: list[dict[str, Any]], outputs: list[str]) -> None:
    configs = [str(row["config_id"]) for row in rows]
    xvals = [_as_int(row.get("short_contact_lt_1p8_count")) for row in rows]
    yvals = [_as_float(row.get("final_cif_rate")) or 0.0 for row in rows]
    lt15 = [_as_int(row.get("short_contact_lt_1p5_count")) for row in rows]
    fig, ax = plt.subplots(figsize=(8, 5.2))
    for config, xval, yval, fail_count, color in zip(configs, xvals, yvals, lt15, _colors(configs)):
        marker = "X" if fail_count else "o"
        size = 150 if fail_count else 95
        ax.scatter(xval, yval, s=size, marker=marker, color=color, edgecolor="#222222", linewidth=0.8)
        ax.text(xval + 0.18, yval + 0.002, config, fontsize=10, weight="bold")
    _style_axes(ax, "Yield Versus Contact-Safety Trade-Off", "<1.8 A contact warning count", xlabel="<1.8 A contact warning count")
    ax.set_ylabel("Final CIF rate")
    ax.set_ylim(min(yvals) - 0.04, max(yvals) + 0.04)
    ax.set_xlim(min(xvals) - 1, max(xvals) + 2)
    ax.annotate("C: good yield,\nno <1.5 A failures", xy=(xvals[configs.index("C")], yvals[configs.index("C")]), xytext=(-95, 45), textcoords="offset points", arrowprops={"arrowstyle": "->", "color": "#1f7a4d"}, color="#1f7a4d", fontsize=9)
    ax.annotate("F: high yield,\nmore warnings + <1.5 A", xy=(xvals[configs.index("F")], yvals[configs.index("F")]), xytext=(-120, -45), textcoords="offset points", arrowprops={"arrowstyle": "->", "color": "#b33a3a"}, color="#b33a3a", fontsize=9)
    fig.text(0.02, 0.01, "X markers indicate at least one <1.5 A contact-safety failure.", fontsize=8, color="#555555")
    _save(fig, "yield_vs_contact_safety_tradeoff.png", outputs)


def plot_recommended_summary(rows: list[dict[str, Any]], outputs: list[str]) -> bool:
    subset = [row for row in rows if str(row.get("config_id")) in {"A", "C", "F"}]
    if len(subset) != 3:
        print("Warning: missing A/C/F rows; skipping recommended summary plot.", file=sys.stderr)
        return False
    configs = [str(row["config_id"]) for row in subset]
    final_rate = [_as_float(row.get("final_cif_rate")) or 0.0 for row in subset]
    llm = [_as_float(row.get("mean_llm_score")) or 0.0 for row in subset]
    lt15 = [_as_int(row.get("short_contact_lt_1p5_count")) for row in subset]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8))
    panels = [
        ("Final CIF rate", final_rate, "rate"),
        ("Mean LLM score", llm, "score"),
        ("<1.5 A contacts", lt15, "count"),
    ]
    for ax, (title, values, ylabel) in zip(axes, panels):
        ax.bar(configs, values, color=_colors(configs), edgecolor="#333333", linewidth=0.7)
        _style_axes(ax, title, ylabel)
        for config, value in zip(configs, values):
            label = f"{value:.3f}" if isinstance(value, float) else str(value)
            ax.text(config, value + (max(values) * 0.03 if max(values) else 0.03), label, ha="center", fontsize=8)
    axes[0].annotate("recommended\nConfig C", xy=("C", final_rate[configs.index("C")]), xytext=(-15, 35), textcoords="offset points", ha="center", arrowprops={"arrowstyle": "->", "color": "#1f7a4d"}, color="#1f7a4d", fontsize=9)
    axes[2].annotate("F disqualified\npending audit", xy=("F", lt15[configs.index("F")]), xytext=(-50, 35), textcoords="offset points", ha="center", arrowprops={"arrowstyle": "->", "color": "#b33a3a"}, color="#b33a3a", fontsize=9)
    fig.suptitle("Recommended Default Summary: A/C/F", fontsize=14, weight="bold")
    fig.text(0.02, 0.01, "Diagnostic benchmark summary only; not physical validation.", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.05, 1, 0.93))
    _save(fig, "recommended_config_summary.png", outputs)
    return True


def main() -> int:
    try:
        rows = _load_rows()
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not rows:
        print(f"Error: no rows found in {INPUT_CSV}", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    plot_final_cif_rate(rows, outputs)
    plot_short_contacts(rows, outputs)
    plot_rule_rank(rows, outputs)
    llm_plot_written = plot_llm_alignment(rows, outputs)
    plot_yield_tradeoff(rows, outputs)
    summary_plot_written = plot_recommended_summary(rows, outputs)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_csv_path": str(INPUT_CSV.relative_to(REPO_ROOT)),
        "input_summary_path": str(INPUT_SUMMARY.relative_to(REPO_ROOT)) if INPUT_SUMMARY.exists() else "",
        "output_plot_paths": outputs,
        "recommended_default_config": "C",
        "safety_note": "Config F is contact-unsafe because it has one <1.5 A case; Config C is the recommended current default.",
        "llm_plot_written": llm_plot_written,
        "recommended_summary_plot_written": summary_plot_written,
    }
    manifest_path = OUT_DIR / "plot_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"plots": outputs, "manifest": str(manifest_path.relative_to(REPO_ROOT))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
