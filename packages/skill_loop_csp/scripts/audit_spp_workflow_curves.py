from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sok_llm_orchestrator.agentic import visualise_workflow_artifact as visualizer


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_slug(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_") or "item"


def _numeric_rows(path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.replace(",", " ").split()
        values: list[float] = []
        for part in parts:
            try:
                values.append(float(part))
            except ValueError:
                break
        if len(values) >= 2 and all(math.isfinite(v) for v in values):
            rows.append(values)
    return rows


def _comment_metadata(path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("#"):
            break
        body = stripped.lstrip("#").strip()
        if ":" in body:
            key, value = body.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta


def _preview(path: Path, out_path: Path, limit: int = 30) -> list[str]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    preview = lines[:limit]
    out_path.write_text("\n".join(preview) + ("\n" if preview else ""), encoding="utf-8")
    return preview


def _plot_curve(
    xs: list[float],
    ys: list[float],
    out_path: Path,
    *,
    title: str,
    label: str | None = None,
    color: str = "#2f5f9f",
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.0, 3.4))
    ax.plot(xs, ys, linewidth=1.1, alpha=0.95, color=color, label=label)
    if label:
        ax.legend(fontsize=8)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Distance (A)")
    ax.set_ylabel("SPP/POT value")
    ax.grid(True, linewidth=0.35, alpha=0.28)
    ax.margins(x=0.02, y=0.05)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def _plot_overlay(
    raw_xs: list[float],
    raw_ys: list[float],
    workflow_xs: list[float],
    workflow_ys: list[float],
    out_path: Path,
    *,
    title: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.2, 3.5))
    ax.plot(raw_xs, raw_ys, linewidth=1.2, alpha=0.9, label="raw numeric POT", color="#2f5f9f")
    ax.plot(workflow_xs, workflow_ys, linewidth=0.9, alpha=0.75, label="workflow parser output", color="#c23b22", linestyle="--")
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Distance (A)")
    ax.set_ylabel("SPP/POT value")
    ax.grid(True, linewidth=0.35, alpha=0.28)
    ax.legend(fontsize=8)
    ax.margins(x=0.02, y=0.05)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def _flat_cap_stats(ys: list[float]) -> dict[str, Any]:
    if not ys:
        return {
            "raw_y_min": None,
            "raw_y_max": None,
            "fraction_at_apparent_max_cap": 0.0,
            "long_flat_plateaus_exist": False,
            "likely_clipping_or_capping_pattern": False,
        }
    y_min = min(ys)
    y_max = max(ys)
    tol = max(abs(y_max) * 1e-8, 1e-8)
    at_max = sum(1 for y in ys if abs(y - y_max) <= tol)
    rounded = [round(y, 8) for y in ys]
    counts = Counter(rounded)
    max_repeat_fraction = max(counts.values()) / len(ys)
    longest_run = 1
    run = 1
    for prev, cur in zip(rounded, rounded[1:]):
        if cur == prev:
            run += 1
            longest_run = max(longest_run, run)
        else:
            run = 1
    longest_run_fraction = longest_run / len(ys)
    plateau = max_repeat_fraction >= 0.25 or longest_run_fraction >= 0.12
    cap_like = plateau and (y_max >= 8.0 or max_repeat_fraction >= 0.40)
    return {
        "raw_y_min": y_min,
        "raw_y_max": y_max,
        "fraction_at_apparent_max_cap": at_max / len(ys),
        "max_repeated_value_fraction": max_repeat_fraction,
        "longest_flat_run_fraction": longest_run_fraction,
        "long_flat_plateaus_exist": plateau,
        "likely_clipping_or_capping_pattern": cap_like,
    }


def _arrays_match(a_x: list[float], a_y: list[float], b_x: list[float], b_y: list[float]) -> bool:
    if len(a_x) != len(b_x) or len(a_y) != len(b_y):
        return False
    for av, bv in zip(a_x, b_x):
        if abs(av - bv) > 1e-9:
            return False
    for av, bv in zip(a_y, b_y):
        if abs(av - bv) > 1e-9:
            return False
    return True


def audit_case(case_name: str, manifest_path: Path, out_dir: Path) -> list[dict[str, Any]]:
    manifest = _read_json(manifest_path)
    spp_panel = manifest.get("panels", {}).get("spp_pot_guidance", {})
    case_dir = out_dir / _safe_slug(case_name)
    case_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for child in spp_panel.get("children") or []:
        pair = str(child.get("pair") or "unknown")
        pair_slug = _safe_slug(pair)
        pot_path = Path(str(child.get("spp_source_data_path") or child.get("source_artifact_path") or ""))
        pair_dir = case_dir / pair_slug
        pair_dir.mkdir(parents=True, exist_ok=True)
        raw_copy = pair_dir / pot_path.name
        preview_path = pair_dir / f"{pair_slug}_raw_preview.txt"
        raw_plot = pair_dir / f"{pair_slug}_raw_direct_plot.png"
        workflow_plot = pair_dir / f"{pair_slug}_current_workflow_reproduction.png"
        overlay_plot = pair_dir / f"{pair_slug}_raw_vs_workflow_overlay.png"
        metadata_path = pair_dir / f"{pair_slug}_metadata.json"

        if not pot_path.is_file():
            row = {
                "case": case_name,
                "pair": pair,
                "raw_pot_path": str(pot_path),
                "raw_pot_copy": "",
                "suspected_failure_mode": "missing_pot_file",
            }
            rows.append(row)
            continue

        shutil.copyfile(pot_path, raw_copy)
        preview_lines = _preview(pot_path, preview_path)
        numeric = _numeric_rows(pot_path)
        comment_meta = _comment_metadata(pot_path)
        detected_columns = max((len(row) for row in numeric), default=0)
        raw_xs = [row[0] for row in numeric]
        raw_ys = [row[1] for row in numeric]
        parsed = visualizer._parse_pot_file(pot_path)
        workflow_xs, workflow_ys = parsed if parsed else ([], [])

        if raw_xs and raw_ys:
            _plot_curve(raw_xs, raw_ys, raw_plot, title=f"{case_name} {pair} RAW POT", label="raw numeric POT")
        if workflow_xs and workflow_ys:
            _plot_curve(
                workflow_xs,
                workflow_ys,
                workflow_plot,
                title=f"{case_name} {pair} current workflow parser output",
                label="workflow parser output",
                color="#c23b22",
            )
        if raw_xs and raw_ys and workflow_xs and workflow_ys:
            _plot_overlay(raw_xs, raw_ys, workflow_xs, workflow_ys, overlay_plot, title=f"{case_name} {pair}: raw vs workflow")

        match = _arrays_match(raw_xs, raw_ys, workflow_xs, workflow_ys)
        flat_stats = _flat_cap_stats(raw_ys)
        if not workflow_xs:
            failure_mode = "workflow_parser_failed"
        elif not match:
            failure_mode = "workflow_parser_differs_from_raw_numeric_columns"
        elif flat_stats["likely_clipping_or_capping_pattern"]:
            failure_mode = "flat_cap_present_in_raw_pot_file"
        else:
            failure_mode = "workflow_matches_raw_pot_file"

        metadata = {
            "case": case_name,
            "pair": pair,
            "raw_pot_path": str(pot_path),
            "file_size": pot_path.stat().st_size,
            "detected_format": "commented_two_column_pot" if comment_meta and detected_columns >= 2 else "numeric_pot",
            "number_of_rows": len(numeric),
            "number_of_columns": detected_columns,
            "column_names": ["distance", "value"] if detected_columns >= 2 else [],
            "comment_metadata": comment_meta,
            "preview_path": str(preview_path),
            "raw_plot": str(raw_plot),
            "workflow_plot": str(workflow_plot),
            "overlay_plot": str(overlay_plot),
            "workflow_plot_matches_raw_plot_data": match,
            "manifest_child": child,
            **flat_stats,
            "suspected_failure_mode": failure_mode,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        rows.append(
            {
                "case": case_name,
                "pair": pair,
                "raw_pot_path": str(pot_path),
                "raw_pot_copy": str(raw_copy),
                "preview_path": str(preview_path),
                "metadata_path": str(metadata_path),
                "raw_plot": str(raw_plot),
                "workflow_plot": str(workflow_plot),
                "overlay_plot": str(overlay_plot),
                "file_size": pot_path.stat().st_size,
                "detected_format": metadata["detected_format"],
                "number_of_rows": len(numeric),
                "number_of_columns": detected_columns,
                "raw_x_min": min(raw_xs) if raw_xs else None,
                "raw_x_max": max(raw_xs) if raw_xs else None,
                "raw_y_min": flat_stats["raw_y_min"],
                "raw_y_max": flat_stats["raw_y_max"],
                "fraction_at_apparent_max_cap": flat_stats["fraction_at_apparent_max_cap"],
                "max_repeated_value_fraction": flat_stats["max_repeated_value_fraction"],
                "longest_flat_run_fraction": flat_stats["longest_flat_run_fraction"],
                "long_flat_plateaus_exist": flat_stats["long_flat_plateaus_exist"],
                "likely_clipping_or_capping_pattern": flat_stats["likely_clipping_or_capping_pattern"],
                "workflow_plot_matches_raw_plot_data": match,
                "visualizer_render_mode": child.get("render_mode"),
                "visualizer_post_processing": child.get("post_processing"),
                "suspected_failure_mode": failure_mode,
            }
        )
    return rows


def write_outputs(rows: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "spp_audit_summary.json"
    csv_path = out_dir / "spp_audit_summary.csv"
    report_path = out_dir / "spp_audit_report.md"
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    fields = [
        "case",
        "pair",
        "raw_pot_path",
        "raw_pot_copy",
        "raw_x_min",
        "raw_x_max",
        "raw_y_min",
        "raw_y_max",
        "fraction_at_apparent_max_cap",
        "max_repeated_value_fraction",
        "longest_flat_run_fraction",
        "long_flat_plateaus_exist",
        "likely_clipping_or_capping_pattern",
        "workflow_plot_matches_raw_plot_data",
        "visualizer_render_mode",
        "visualizer_post_processing",
        "suspected_failure_mode",
        "raw_plot",
        "workflow_plot",
        "overlay_plot",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    mode_counts = Counter(row["suspected_failure_mode"] for row in rows)
    lines = [
        "# SPP Workflow Curve Audit",
        "",
        "This audit compares the POT files referenced by the workflow manifests with the current workflow parser output.",
        "",
        "## Summary",
        "",
        f"- Pair potentials audited: {len(rows)}",
        f"- Failure-mode counts: `{dict(mode_counts)}`",
        "",
        "## Interpretation",
        "",
    ]
    if mode_counts.get("flat_cap_present_in_raw_pot_file"):
        lines.append(
            "- The flat/high-value plateau is present in the raw POT file numeric values for at least one pair. "
            "For those pairs, the workflow plot is faithfully showing the raw POT data rather than introducing the plateau."
        )
    if any(not row.get("workflow_plot_matches_raw_plot_data") for row in rows):
        lines.append(
            "- At least one workflow parser output differs from the raw numeric POT columns. Inspect the overlay plots for wrong-column or representation mismatches."
        )
    else:
        lines.append("- Current workflow parser output matches the raw numeric POT columns for all audited pairs.")
    lines.extend(
        [
            "",
            "## Pair Details",
            "",
            "| Case | Pair | Raw y min | Raw y max | Max repeat fraction | Workflow matches raw | Suspected failure mode |",
            "|---|---|---:|---:|---:|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['case']} | {row['pair']} | {row.get('raw_y_min')} | {row.get('raw_y_max')} | "
            f"{row.get('max_repeated_value_fraction')} | {row.get('workflow_plot_matches_raw_plot_data')} | {row.get('suspected_failure_mode')} |"
        )
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            f"- JSON: `{json_path}`",
            f"- CSV: `{csv_path}`",
            "- Per-pair folders include raw POT copies, text previews, raw direct plots, current workflow reproductions, overlay comparisons, and per-pair metadata JSON.",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit SPP/POT curves used by workflow artifact figures.")
    parser.add_argument("--figures-dir", type=Path, default=Path("test_workdir/paper_evidence_pack_v1/figures"))
    parser.add_argument("--out-dir", type=Path, default=Path("test_workdir/paper_evidence_pack_v1/final_doc_images/spp_audit"))
    parser.add_argument("--case", action="append", default=["CoAs2", "BaTiO3", "CaTiO3"])
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for case in args.case:
        manifest = args.figures_dir / f"workflow_artifact_{_safe_slug(case)}_manifest.json"
        if not manifest.is_file():
            raise FileNotFoundError(f"Missing workflow manifest for {case}: {manifest}")
        rows.extend(audit_case(case, manifest, args.out_dir))
    write_outputs(rows, args.out_dir)
    print(json.dumps({"out_dir": str(args.out_dir), "pairs_audited": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
