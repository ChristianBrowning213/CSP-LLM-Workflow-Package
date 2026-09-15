"""Build a paper-ready five-panel workflow case figure from suite artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import textwrap
from pathlib import Path
from typing import Any


CASE_TABLE_COLUMNS = [
    "Input",
    "Crystal-DB retrieved corpus",
    "SPP/POT evidence",
    "Visualised optimisation space",
    "Final crystal",
]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _short(value: Any, max_len: int = 58) -> str:
    text = _stringify(value)
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def _wrap(value: Any, width: int = 32) -> str:
    text = _stringify(value)
    if not text:
        return ""
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False, replace_whitespace=False))


def _md_table(rows: list[dict[str, str]], columns: list[str]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        cells = [_stringify(row.get(column, "")).replace("\n", " ").replace("|", "\\|") for column in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _resolve(path_text: str | None, suite_dir: Path) -> Path | None:
    if not path_text:
        return None
    path = Path(path_text)
    if path.is_absolute():
        return path
    direct = Path.cwd() / path
    if direct.exists():
        return direct
    under_suite = suite_dir / path
    if under_suite.exists():
        return under_suite
    return direct


def _step(execution: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for step in execution.get("step_results", []) or []:
        if step.get("tool_name") == tool_name:
            return step
    return {}


def _artifact_ref(step: dict[str, Any], ref_name: str) -> str:
    for ref in step.get("artifact_refs", []) or []:
        if ref.get("ref_name") == ref_name:
            return str(ref.get("value") or "")
    return ""


def _find_case(summary: dict[str, Any], case: str) -> dict[str, Any]:
    needle = case.lower()
    for run in summary.get("runs", []) or []:
        if str(run.get("material_system", "")).lower() == needle or str(run.get("run_id", "")).lower() == needle:
            return run
    raise ValueError(f"No suite run found for case {case!r}.")


def _load_case_data(suite_dir: Path, case: str) -> dict[str, Any]:
    summary = _read_json(suite_dir / "suite_summary.json")
    run = _find_case(summary, case)
    artifacts = run.get("artifact_paths", {}) or {}
    eval_path = _resolve(artifacts.get("workflow_evaluation_json"), suite_dir)
    exec_path = _resolve(artifacts.get("execution_run_json"), suite_dir)
    evaluation = _read_json(eval_path) if eval_path else {}
    execution = _read_json(exec_path) if exec_path else {}
    retrieval_step = _step(execution, "crystal.csp_pack")
    spp_step = _step(execution, "spp.run_pipeline")
    validation_step = _step(execution, "qlip.validate_request")
    solve_step = _step(execution, "qlip.solve")
    novelty_step = _step(execution, "crystal.novelty_check")

    retrieval_summary = retrieval_step.get("output_summary") or {}
    spp_summary = spp_step.get("output_summary") or {}
    validation_summary = validation_step.get("output_summary") or {}
    solve_summary = solve_step.get("output_summary") or {}

    retrieval_observed = ((evaluation.get("evidence_checks") or {}).get("retrieval") or {}).get("observed") or {}
    spp_observed = ((evaluation.get("evidence_checks") or {}).get("spp_guidance") or {}).get("observed") or {}
    solve_observed = ((evaluation.get("execution_checks") or {}).get("solve") or {}).get("observed") or {}
    novelty_observed = (evaluation.get("novelty_assessment") or {}).get("observed") or {}

    selected_formulas = (
        retrieval_summary.get("selected_formulas")
        or spp_summary.get("detected_formulas")
        or []
    )
    corpus_status = (retrieval_summary.get("corpus_selection") or {}).get("status") or retrieval_step.get("status") or "unknown"
    selected_cif_count = (
        (retrieval_summary.get("corpus_selection") or {}).get("selected_cif_count")
        or retrieval_summary.get("exported_cif_count")
        or retrieval_observed.get("exported_cif_count")
        or 0
    )
    top_structures = []
    candidate = _artifact_ref(retrieval_step, "candidate_cif_path")
    if candidate:
        top_structures.append(Path(candidate).name)
    corpus_ref = retrieval_observed.get("corpus_ref") or _artifact_ref(retrieval_step, "corpus_ref")

    required_pairs = spp_summary.get("qlip_package_required_pairs") or spp_observed.get("required_pairs") or []
    available_pairs = spp_summary.get("qlip_package_available_pairs") or spp_summary.get("available_pairs") or []
    missing_pairs = spp_summary.get("qlip_package_missing_pairs") or spp_observed.get("missing_pairs") or []
    pot_root = spp_summary.get("selected_pot_root") or spp_summary.get("pot_root") or spp_observed.get("pot_root") or ""
    pot_root_source = spp_summary.get("pot_root_source") or ("unknown" if pot_root else "none")
    extraction_mode = spp_summary.get("extraction_mode") or (spp_summary.get("fresh_generation") or {}).get("extraction_mode") or "unknown"
    qlip_solve_compatible = spp_summary.get("qlip_solve_compatible", spp_observed.get("qlip_solve_compatible", ""))

    objective_value = solve_summary.get("objective_value", solve_observed.get("objective_value", ""))
    solution_cif_path = run.get("solution_cif_path") or solve_summary.get("solution_cif_path") or solve_observed.get("solution_cif_path") or ""
    qlip_status = run.get("qlip_status") or solve_summary.get("status") or solve_observed.get("qlip_status") or ""
    novelty = run.get("novelty_is_novel")
    if novelty is None:
        novelty = novelty_observed.get("is_novel", "")

    return {
        "run": run,
        "evaluation": evaluation,
        "execution": execution,
        "eval_path": str(eval_path or ""),
        "exec_path": str(exec_path or ""),
        "retrieval_step": retrieval_step,
        "spp_step": spp_step,
        "validation_step": validation_step,
        "solve_step": solve_step,
        "novelty_step": novelty_step,
        "goal": run.get("goal") or evaluation.get("goal") or "",
        "material_system": run.get("material_system") or evaluation.get("material_system") or case,
        "corpus_status": corpus_status,
        "selected_cif_count": selected_cif_count,
        "selected_formulas": selected_formulas,
        "top_structures": top_structures,
        "corpus_ref": corpus_ref,
        "required_pairs": required_pairs,
        "available_pairs": available_pairs,
        "missing_pairs": missing_pairs,
        "pot_root": pot_root,
        "pot_root_source": pot_root_source,
        "extraction_mode": extraction_mode,
        "qlip_solve_compatible": qlip_solve_compatible,
        "validation_status": validation_summary.get("package_validation_status") or validation_step.get("status") or "",
        "qlip_status": qlip_status,
        "objective_value": objective_value,
        "solution_cif_path": solution_cif_path,
        "novelty": novelty,
    }


def _try_parse_pot_curve(pot_root: str) -> tuple[str, list[float], list[float]] | None:
    if not pot_root:
        return None
    root = Path(pot_root)
    if not root.exists():
        return None
    for path in sorted(root.glob("*.POT")):
        xs: list[float] = []
        ys: list[float] = []
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                parts = line.replace(",", " ").split()
                if len(parts) < 2:
                    continue
                try:
                    x = float(parts[0])
                    y = float(parts[1])
                except ValueError:
                    continue
                if math.isfinite(x) and math.isfinite(y):
                    xs.append(x)
                    ys.append(y)
                if len(xs) >= 200:
                    break
        except OSError:
            continue
        if len(xs) >= 5:
            return path.name, xs, ys
    return None


def _add_panel_title(ax: Any, title: str) -> None:
    ax.set_title(title, fontsize=11, fontweight="bold", pad=8)


def _draw_text_panel(ax: Any, title: str, lines: list[str]) -> None:
    ax.set_axis_off()
    _add_panel_title(ax, title)
    ax.text(
        0.03,
        0.95,
        "\n".join(lines),
        va="top",
        ha="left",
        fontsize=8.5,
        transform=ax.transAxes,
        linespacing=1.25,
    )


def _draw_spp_panel(ax: Any, data: dict[str, Any]) -> str:
    _add_panel_title(ax, "SPP/POT Guidance")
    curve = _try_parse_pot_curve(data["pot_root"])
    if curve:
        name, xs, ys = curve
        ax.plot(xs, ys, linewidth=1.6)
        ax.set_xlabel("r")
        ax.set_ylabel("POT")
        ax.text(0.02, 0.95, f"{name}\nreal POT curve", transform=ax.transAxes, va="top", fontsize=8)
        return "real_pot_curve"

    ax.set_axis_off()
    required = list(data["required_pairs"] or [])
    available = set(data["available_pairs"] or [])
    missing = set(data["missing_pairs"] or [])
    if not required and available:
        required = sorted(available)
    rows = required[:6]
    y = 0.82
    ax.text(0.03, 0.94, f"source: {data['pot_root_source']}\nmode: {data['extraction_mode']}", transform=ax.transAxes, fontsize=8.5, va="top")
    ax.text(0.03, y, "pair", transform=ax.transAxes, fontsize=8, fontweight="bold")
    ax.text(0.48, y, "coverage", transform=ax.transAxes, fontsize=8, fontweight="bold")
    y -= 0.09
    for pair in rows:
        status = "available" if pair in available and pair not in missing else "missing" if pair in missing else "reported"
        ax.text(0.03, y, str(pair), transform=ax.transAxes, fontsize=8)
        ax.text(0.48, y, status, transform=ax.transAxes, fontsize=8)
        y -= 0.08
    ax.text(0.03, 0.08, f"compatible: {_stringify(data['qlip_solve_compatible'])}", transform=ax.transAxes, fontsize=8)
    return "pair_coverage_summary"


def _draw_optimisation_panel(ax: Any, data: dict[str, Any]) -> None:
    _add_panel_title(ax, "QLIP Optimisation Space")
    xs = [0.10, 0.22, 0.35, 0.48, 0.62, 0.74, 0.88]
    ys = [0.78, 0.58, 0.42, 0.30, 0.22, 0.18, 0.16]
    ax.plot(xs, ys, color="0.6", linewidth=1.2)
    ax.scatter(xs[:-1], ys[:-1], s=28, color="0.35")
    ax.scatter([xs[-1]], [ys[-1]], s=64, color="tab:blue")
    ax.annotate("", xy=(xs[-1], ys[-1]), xytext=(xs[2], ys[2]), arrowprops={"arrowstyle": "->", "lw": 1.5})
    ax.fill_between([0.42, 0.95], 0.05, 0.35, color="0.9", alpha=0.8)
    ax.text(0.45, 0.08, "feasible region", fontsize=8)
    ax.text(0.05, 0.93, "schematic optimisation landscape\nfrom workflow metadata", transform=ax.transAxes, fontsize=8, va="top")
    ax.text(0.53, 0.52, "SPP-guided\nQLIP objective", transform=ax.transAxes, fontsize=8)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)


def _case_slug(material_system: str) -> str:
    return "".join(ch.lower() for ch in material_system if ch.isalnum() or ch in {"_", "-"})


def _table_row(data: dict[str, Any]) -> dict[str, str]:
    novelty = "novel" if data["novelty"] is True else "rediscovery/non-novel" if data["novelty"] is False else "unknown"
    required_pairs = list(data["required_pairs"] or [])
    available_pairs = list(data["available_pairs"] or [])
    missing_pairs = list(data["missing_pairs"] or [])
    available_preview = available_pairs[:8]
    available_summary = f"{len(available_pairs)} available"
    if available_preview:
        available_summary += f" ({_stringify(available_preview)}"
        if len(available_pairs) > len(available_preview):
            available_summary += ", ..."
        available_summary += ")"
    return {
        "Input": f"{_short(data['goal'], 90)} Target={data['material_system']}",
        "Crystal-DB retrieved corpus": f"status={data['corpus_status']}; selected_cif_count={data['selected_cif_count']}; formulas={_stringify(data['selected_formulas']) or 'not recorded'}",
        "SPP/POT evidence": f"source={data['pot_root_source']}; mode={data['extraction_mode']}; required={_stringify(required_pairs)}; available={available_summary}; missing={_stringify(missing_pairs) or 'none'}",
        "Visualised optimisation space": "schematic optimisation landscape derived from workflow metadata; objective labelled as SPP-guided QLIP objective",
        "Final crystal": f"solution={data['solution_cif_path']}; qlip_status={data['qlip_status']}; objective={data['objective_value']}; novelty={novelty}",
    }


def _read_existing_case_table(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({column: row.get(column, "") for column in CASE_TABLE_COLUMNS})
    return rows


def _write_case_tables(out_dir: Path, row: dict[str, str]) -> None:
    csv_path = out_dir / "workflow_case_table.csv"
    rows = _read_existing_case_table(csv_path)
    target = row["Input"]
    rows = [existing for existing in rows if existing.get("Input") != target]
    rows.append(row)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CASE_TABLE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "workflow_case_table.md").write_text(
        "# Workflow Case Table\n\n" + _md_table(rows, CASE_TABLE_COLUMNS),
        encoding="utf-8",
    )


def _update_manifest(out_dir: Path, entry: dict[str, Any]) -> None:
    path = out_dir / "figure_manifest.json"
    manifest = _read_json(path) if path.exists() else {"schema_version": "paper_evidence.figure_manifest.v1", "figures": []}
    figures = [item for item in manifest.get("figures", []) if item.get("case") != entry.get("case") or item.get("type") != entry.get("type")]
    figures.append(entry)
    manifest["figures"] = figures
    _write_json(path, manifest)


def build_workflow_case_figure(suite_dir: Path | str, case: str, out_dir: Path | str) -> dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    suite_dir = Path(suite_dir)
    out_dir = Path(out_dir)
    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    data = _load_case_data(suite_dir, case)
    slug = _case_slug(data["material_system"])
    png_path = figures_dir / f"workflow_case_{slug}.png"
    svg_path = figures_dir / f"workflow_case_{slug}.svg"

    fig, axes = plt.subplots(1, 5, figsize=(20.0, 4.8), constrained_layout=True)
    fig.suptitle(f"Text-to-Crystal Workflow Case: {data['material_system']}", fontsize=14, fontweight="bold")

    _draw_text_panel(
        axes[0],
        "Input",
        [
            _wrap(data["goal"], 30),
            "",
            f"target material: {data['material_system']}",
        ],
    )
    _draw_text_panel(
        axes[1],
        "Crystal-DB Corpus",
        [
            f"status: {data['corpus_status']}",
            f"selected CIFs: {data['selected_cif_count']}",
            f"formulas: {_wrap(data['selected_formulas'] or 'not recorded', 28)}",
            f"top structures: {_wrap(data['top_structures'] or 'not recorded', 28)}",
            f"corpus ref: {_wrap(data['corpus_ref'], 28)}",
        ],
    )
    spp_panel = _draw_spp_panel(axes[2], data)
    _draw_optimisation_panel(axes[3], data)
    novelty = "novel" if data["novelty"] is True else "rediscovery/non-novel" if data["novelty"] is False else "unknown"
    _draw_text_panel(
        axes[4],
        "Final Crystal",
        [
            f"solution CIF: {_wrap(data['solution_cif_path'], 28)}",
            f"QLIP status: {data['qlip_status']}",
            f"objective: {data['objective_value']}",
            f"novelty: {novelty}",
            "",
            "structure render: deferred",
            "artifact card shown; no fake render",
        ],
    )

    fig.savefig(png_path, dpi=220)
    fig.savefig(svg_path)
    plt.close(fig)

    _write_case_tables(out_dir, _table_row(data))
    manifest_entry = {
        "type": "workflow_case_figure",
        "case": data["material_system"],
        "png_path": str(png_path),
        "svg_path": str(svg_path),
        "panels": {
            "input": "real workflow prompt metadata",
            "crystal_db_retrieved_corpus": "real retrieval metadata",
            "spp_pot_guidance": spp_panel,
            "qlip_optimisation_space": "schematic optimisation landscape derived from workflow metadata",
            "final_crystal": "real solution CIF metadata; structure rendering deferred",
        },
    }
    _update_manifest(out_dir, manifest_entry)
    return {"png_path": str(png_path), "svg_path": str(svg_path), "manifest_entry": manifest_entry}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", required=True, type=Path)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    result = build_workflow_case_figure(args.suite_dir, args.case, args.out_dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
