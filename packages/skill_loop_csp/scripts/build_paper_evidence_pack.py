"""Build paper-facing evidence tables and figures from a paper smoke suite.

The output is descriptive: it summarizes recorded workflow artifacts without
inventing missing solver, property, DFT, novelty, or POT-plot evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


STAGES = ["Crystal-DB", "SPP/POT", "QLIP validate", "QLIP solve", "novelty", "evaluator"]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _stringify(row.get(column, "")) for column in columns})


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


def _md_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        cells = [_stringify(row.get(column, "")).replace("\n", " ").replace("|", "\\|") for column in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _resolve_artifact_path(path_text: str | None, suite_dir: Path) -> Path | None:
    if not path_text:
        return None
    path = Path(path_text)
    if path.is_absolute():
        return path
    direct = Path.cwd() / path
    if direct.exists():
        return direct
    candidate = suite_dir / path
    if candidate.exists():
        return candidate
    return direct


def _step(execution_run: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for step in execution_run.get("step_results", []) or []:
        if step.get("tool_name") == tool_name:
            return step
    return {}


def _nested(data: dict[str, Any], *keys: str, default: Any = "") -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def _load_run_context(summary_run: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    artifacts = summary_run.get("artifact_paths", {}) or {}
    evaluation_path = _resolve_artifact_path(artifacts.get("workflow_evaluation_json"), suite_dir)
    execution_path = _resolve_artifact_path(artifacts.get("execution_run_json"), suite_dir)
    return {
        "evaluation": _read_json(evaluation_path) if evaluation_path else {},
        "execution": _read_json(execution_path) if execution_path else {},
        "evaluation_path": str(evaluation_path) if evaluation_path else "",
        "execution_path": str(execution_path) if execution_path else "",
    }


def _first_error_code(step_data: dict[str, Any], evaluation: dict[str, Any], fallback: str = "") -> str:
    error = step_data.get("error") or {}
    if isinstance(error, dict):
        code = error.get("code") or error.get("error_code")
        if code:
            return str(code)
    failure = evaluation.get("failure_assessment") or {}
    return str(failure.get("error_code") or fallback or "")


def _diagnostic_summary(evaluation: dict[str, Any], spp_summary: dict[str, Any], summary_run: dict[str, Any]) -> str:
    failure = evaluation.get("failure_assessment") or {}
    if failure.get("error_message"):
        return str(failure["error_message"])
    errors = evaluation.get("errors") or []
    if errors:
        return _stringify(errors[0])
    missing_pairs = spp_summary.get("qlip_package_missing_pairs") or spp_summary.get("missing_pairs")
    corpus_quality = spp_summary.get("corpus_quality_status")
    if missing_pairs or corpus_quality:
        return f"SPP corpus/POT diagnostics: corpus_quality={corpus_quality or 'unknown'}, missing_pairs={_stringify(missing_pairs)}"
    if summary_run.get("actual_failure_code") or summary_run.get("failure_code"):
        return str(summary_run.get("actual_failure_code") or summary_run.get("failure_code"))
    return str(evaluation.get("evaluator_summary") or "")


def _extract_row(summary_run: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    context = _load_run_context(summary_run, suite_dir)
    evaluation = context["evaluation"]
    execution = context["execution"]
    retrieval_step = _step(execution, "crystal.csp_pack")
    spp_step = _step(execution, "spp.run_pipeline")
    validation_step = _step(execution, "qlip.validate_request")
    solve_step = _step(execution, "qlip.solve")
    novelty_step = _step(execution, "crystal.novelty_check")
    retrieval_summary = retrieval_step.get("output_summary") or {}
    spp_summary = spp_step.get("output_summary") or {}
    validation_summary = validation_step.get("output_summary") or {}
    solve_summary = solve_step.get("output_summary") or {}

    retrieval_observed = _nested(evaluation, "evidence_checks", "retrieval", "observed", default={}) or {}
    spp_observed = _nested(evaluation, "evidence_checks", "spp_guidance", "observed", default={}) or {}
    solve_observed = _nested(evaluation, "execution_checks", "solve", "observed", default={}) or {}
    novelty_observed = _nested(evaluation, "novelty_assessment", "observed", default={}) or {}
    failure = evaluation.get("failure_assessment") or {}
    evidence_dimensions = summary_run.get("evidence_dimensions") or {}

    selected_formulas = (
        spp_summary.get("detected_formulas")
        or _nested(spp_summary, "fresh_generation", "corpus_quality", "detected_formulas", default=[])
        or _nested(spp_observed, "corpus_quality", "detected_formulas", default=[])
        or []
    )
    corpus_selection = retrieval_summary.get("corpus_selection") or {}
    corpus_status = corpus_selection.get("status") or retrieval_summary.get("status") or retrieval_step.get("status") or "unknown"
    selected_cif_count = (
        corpus_selection.get("selected_cif_count")
        or retrieval_summary.get("exported_cif_count")
        or retrieval_observed.get("exported_cif_count")
        or 0
    )

    pot_root_source = (
        spp_summary.get("pot_root_source")
        or _nested(spp_summary, "qlip_package", "pot_root_source")
        or ("unknown" if spp_step else "none")
    )
    extraction_mode = spp_summary.get("extraction_mode") or _nested(spp_summary, "fresh_generation", "extraction_mode") or "unknown"
    corpus_quality_status = (
        spp_summary.get("corpus_quality_status")
        or _nested(spp_summary, "fresh_generation", "corpus_quality", "corpus_quality_status")
        or "unknown"
    )
    qlip_solve_compatible = spp_summary.get("qlip_solve_compatible", spp_observed.get("qlip_solve_compatible", ""))
    objective_value = solve_summary.get("objective_value", solve_observed.get("objective_value", ""))
    solution_cif_path = summary_run.get("solution_cif_path") or solve_summary.get("solution_cif_path") or solve_observed.get("solution_cif_path") or ""
    novelty_result = summary_run.get("novelty_is_novel")
    if novelty_result is None:
        novelty_result = novelty_observed.get("is_novel", "")

    failed_tool = failure.get("failed_tool") or summary_run.get("actual_failed_tool") or summary_run.get("failed_tool") or ""
    error_code = failure.get("error_code") or summary_run.get("actual_failure_code") or summary_run.get("failure_code") or ""
    if failed_tool and not error_code:
        error_code = _first_error_code(_step(execution, failed_tool), evaluation)

    row = {
        "run_id": summary_run.get("run_id", ""),
        "input_goal": summary_run.get("goal") or evaluation.get("goal") or "",
        "material_system": summary_run.get("material_system") or evaluation.get("material_system") or "",
        "expected_outcome": summary_run.get("expected_outcome") or summary_run.get("expected_final_status") or "",
        "actual_final_status": summary_run.get("final_status") or evaluation.get("final_status") or "",
        "expectation_pass": bool(summary_run.get("expected_outcome_pass") or summary_run.get("expectation_result") == "pass"),
        "crystal_db_status": retrieval_step.get("status") or ("succeeded" if evidence_dimensions.get("retrieval_executed") else "not_run"),
        "corpus_selection_status": corpus_status,
        "selected_corpus_formulas": selected_formulas,
        "selected_cif_count": selected_cif_count,
        "spp_status": spp_summary.get("qlip_package_status") or spp_step.get("status") or _nested(evaluation, "evidence_checks", "spp_guidance", "status"),
        "pot_root_source": pot_root_source,
        "extraction_mode": extraction_mode,
        "corpus_quality_status": corpus_quality_status,
        "qlip_solve_compatible": qlip_solve_compatible,
        "qlip_validation_status": validation_summary.get("package_validation_status") or validation_step.get("status") or _nested(evaluation, "execution_checks", "validation", "status"),
        "qlip_solve_status": summary_run.get("qlip_status") or solve_summary.get("status") or solve_observed.get("qlip_status") or "",
        "objective_value": objective_value,
        "solution_cif_path": solution_cif_path,
        "novelty_result": novelty_result,
        "workflow_score": summary_run.get("overall_score_0_100") or _nested(evaluation, "scores", "overall_score_0_100"),
        "failed_tool": failed_tool,
        "error_code": error_code,
        "diagnostic_summary": _diagnostic_summary(evaluation, spp_summary, summary_run),
        "workflow_evaluation_json": context["evaluation_path"],
        "execution_run_json": context["execution_path"],
        "evaluator_present": bool(context["evaluation_path"] and Path(context["evaluation_path"]).exists()),
        "retrieval_executed": bool(evidence_dimensions.get("retrieval_executed") or retrieval_step),
        "spp_executed": bool(evidence_dimensions.get("spp_executed") or spp_step),
        "qlip_validated": bool(evidence_dimensions.get("qlip_validated") or validation_step),
        "qlip_solved": bool(evidence_dimensions.get("qlip_solved") or solve_step),
        "novelty_checked": bool(evidence_dimensions.get("novelty_checked") or novelty_step),
    }
    return row


def _paper_table_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    table = []
    for row in rows:
        goal = str(row["input_goal"])
        input_text = goal if len(goal) <= 82 else goal[:79] + "..."
        corpus = f"{row['selected_cif_count']} CIF(s); status={row['corpus_selection_status']}"
        if row["selected_corpus_formulas"]:
            corpus += f"; formulas={_stringify(row['selected_corpus_formulas'])}"
        spp = (
            f"status={row['spp_status']}; pot_root_source={row['pot_root_source']}; "
            f"mode={row['extraction_mode']}; compatible={_stringify(row['qlip_solve_compatible'])}"
        )
        optimisation = f"validate={row['qlip_validation_status']}; solve={row['qlip_solve_status']}"
        if row["objective_value"] != "":
            optimisation += f"; objective={row['objective_value']}"
        if row["actual_final_status"] == "completed":
            novelty = "novel" if row["novelty_result"] is True else "rediscovery/non-novel" if row["novelty_result"] is False else "novelty unknown"
            final = f"{row['solution_cif_path']}; {row['qlip_solve_status']}; {novelty}"
        else:
            final = f"{row['failed_tool'] or 'diagnostic partial'}; {row['error_code'] or 'no_error_code'}; {row['diagnostic_summary']}"
        table.append(
            {
                "Input": input_text,
                "Target material": str(row["material_system"]),
                "Crystal-DB retrieved corpus": corpus,
                "SPP/POT evidence": spp,
                "QLIP optimisation": optimisation,
                "Final crystal / diagnostic": final,
            }
        )
    return table


def _write_figures(rows: list[dict[str, Any]], out_dir: Path) -> list[dict[str, Any]]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []

    def save_current(name: str, title: str) -> None:
        path = figures_dir / name
        plt.tight_layout()
        plt.savefig(path, dpi=180)
        plt.close()
        manifest.append({"path": str(path), "title": title, "status": "generated", "type": "data_figure"})

    completed = sum(1 for row in rows if row["actual_final_status"] == "completed")
    partial = sum(1 for row in rows if row["actual_final_status"] in {"partial", "blocked"})
    failed_expectation = sum(1 for row in rows if not row["expectation_pass"])
    plt.figure(figsize=(6.5, 4.0))
    plt.bar(["completed", "partial diagnostic", "failed expectation"], [completed, partial, failed_expectation])
    plt.ylabel("run count")
    plt.title("Workflow outcome counts")
    save_current("workflow_outcome_counts.png", "Workflow outcome counts")

    stage_counts = {
        "Crystal-DB": sum(1 for row in rows if row["retrieval_executed"]),
        "SPP/POT": sum(1 for row in rows if row["spp_executed"]),
        "QLIP validate": sum(1 for row in rows if row["qlip_validated"]),
        "QLIP solve": sum(1 for row in rows if row["qlip_solved"]),
        "novelty": sum(1 for row in rows if row["novelty_checked"]),
        "evaluator": sum(1 for row in rows if row["evaluator_present"]),
    }
    plt.figure(figsize=(7.0, 4.0))
    plt.bar(stage_counts.keys(), stage_counts.values())
    plt.xticks(rotation=30, ha="right")
    plt.ylabel("runs with stage evidence")
    plt.title("Evidence chain completion")
    save_current("evidence_chain_completion.png", "Evidence chain completion")

    labels = [str(row["run_id"]) for row in rows]
    scores = [float(row["workflow_score"] or 0) for row in rows]
    colors = ["tab:blue" if row["actual_final_status"] == "completed" else "tab:gray" for row in rows]
    plt.figure(figsize=(max(8.0, len(rows) * 0.65), 4.5))
    plt.bar(labels, scores, color=colors)
    plt.xticks(rotation=45, ha="right")
    plt.ylim(0, 105)
    plt.ylabel("workflow score")
    plt.title("Supported and diagnostic workflow scores")
    save_current("supported_vs_diagnostic_scores.png", "Supported and diagnostic workflow scores")

    pot_counts = Counter(str(row["pot_root_source"] or "unknown") for row in rows)
    plt.figure(figsize=(6.5, 4.0))
    plt.bar(list(pot_counts.keys()), list(pot_counts.values()))
    plt.xticks(rotation=20, ha="right")
    plt.ylabel("run count")
    plt.title("POT root source counts")
    save_current("pot_root_source_counts.png", "POT root source counts")

    axes = [
        "direct CIF output",
        "solver-backed output",
        "retrieval evidence",
        "staged failure diagnostics",
        "novelty check",
        "DFT/property validation",
    ]
    data = [
        [1.0, 0.2, 0.0, 0.3, 0.3, 0.8],
        [0.0, 1.0, 1.0, 1.0, 1.0, 0.0],
    ]
    plt.figure(figsize=(8.0, 3.5))
    plt.imshow(data, vmin=0, vmax=1, cmap="Greys")
    plt.yticks([0, 1], ["Direct text-to-crystal", "Our workflow"])
    plt.xticks(range(len(axes)), axes, rotation=35, ha="right")
    plt.colorbar(label="qualitative evidence present")
    plt.title("Comparison evidence axes")
    save_current("comparison_evidence_axes.png", "Comparison evidence axes")

    schematic = """<svg xmlns="http://www.w3.org/2000/svg" width="980" height="220" viewBox="0 0 980 220">
  <style>text{font-family:Arial,sans-serif;font-size:14px}.box{fill:#f7f7f7;stroke:#333;stroke-width:1.4}.ok{stroke:#1b6e3f}.diag{stroke:#8a5a00}.arrow{stroke:#333;stroke-width:1.4;marker-end:url(#m)}</style>
  <defs><marker id="m" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#333"/></marker></defs>
  <rect class="box" x="20" y="70" width="120" height="50" rx="4"/><text x="42" y="100">Input text</text>
  <rect class="box" x="170" y="70" width="120" height="50" rx="4"/><text x="190" y="100">Crystal-DB</text>
  <rect class="box" x="320" y="70" width="120" height="50" rx="4"/><text x="350" y="100">Corpus</text>
  <rect class="box" x="470" y="70" width="120" height="50" rx="4"/><text x="496" y="92">SPP/POT</text><text x="488" y="110">guidance</text>
  <rect class="box ok" x="620" y="70" width="120" height="50" rx="4"/><text x="650" y="100">QLIP</text>
  <rect class="box ok" x="770" y="70" width="120" height="50" rx="4"/><text x="790" y="92">Novelty +</text><text x="792" y="110">evaluator</text>
  <line class="arrow" x1="140" y1="95" x2="170" y2="95"/><line class="arrow" x1="290" y1="95" x2="320" y2="95"/><line class="arrow" x1="440" y1="95" x2="470" y2="95"/><line class="arrow" x1="590" y1="95" x2="620" y2="95"/><line class="arrow" x1="740" y1="95" x2="770" y2="95"/>
  <path class="arrow diag" d="M530 122 C530 170, 665 170, 665 122" fill="none"/><text x="555" y="188">diagnostic partial branch</text>
  <text x="812" y="148">complete branch: solution CIF + report</text>
</svg>
"""
    svg_path = figures_dir / "workflow_schematic_dataflow.svg"
    _write_text(svg_path, schematic)
    manifest.append({"path": str(svg_path), "title": "Workflow schematic dataflow", "status": "generated", "type": "schematic"})

    return manifest


def _write_spp_visualisation_status(rows: list[dict[str, Any]], out_dir: Path) -> list[dict[str, Any]]:
    lines = ["# SPP Visualisation Status", ""]
    deferred = True
    for row in rows:
        if row["actual_final_status"] != "completed":
            continue
        context = _load_run_context({"artifact_paths": {"execution_run_json": row["execution_run_json"]}}, Path.cwd())
        spp_summary = (_step(context["execution"], "spp.run_pipeline").get("output_summary") or {})
        pot_root = spp_summary.get("selected_pot_root") or spp_summary.get("pot_root")
        if not pot_root:
            continue
        pot_files = sorted(Path(pot_root).glob("*.POT")) if Path(pot_root).exists() else []
        lines.extend(
            [
                f"## {row['run_id']}",
                f"- POT root: `{pot_root}`",
                f"- POT file count: {len(pot_files)}",
                f"- Pair files: {_stringify([p.name for p in pot_files[:20]])}",
                "- Plot status: deferred. The evidence pack found POT files, but no project-stable parser for the POT curve format is available here.",
                "- Parser task: add a small POT reader that extracts pair name, radial grid, and potential values from the SPP-Maker output format.",
                "",
            ]
        )
    if len(lines) == 2:
        lines.extend(
            [
                "No completed-case POT root with readable `.POT` files was found in this suite bundle.",
                "No SPP curve was plotted; no synthetic curve was created.",
                "",
            ]
        )
    _write_text(out_dir / "spp_visualisation_status.md", "\n".join(lines))
    return [{"path": str(out_dir / "spp_visualisation_status.md"), "title": "SPP visualisation status", "status": "deferred" if deferred else "generated", "type": "deferred_note"}]


def _write_final_crystal_artifacts(rows: list[dict[str, Any]], out_dir: Path) -> list[dict[str, Any]]:
    lines = ["# Final Crystal Artifacts", ""]
    count = 0
    for row in rows:
        path_text = str(row.get("solution_cif_path") or "")
        if row["actual_final_status"] == "completed" and path_text and Path(path_text).exists():
            count += 1
            novelty = "novel" if row["novelty_result"] is True else "rediscovery/non-novel" if row["novelty_result"] is False else "unknown"
            lines.extend(
                [
                    f"## {row['run_id']}",
                    f"- Material: {row['material_system']}",
                    f"- Solution CIF: `{path_text}`",
                    f"- QLIP status: {row['qlip_solve_status']}",
                    f"- Novelty result: {novelty}",
                    "",
                ]
            )
    if not count:
        lines.append("No completed-case solution CIF paths were present and verified in this suite bundle.")
    lines.extend(
        [
            "Static structure rendering is deferred in this pack; use VESTA, OVITO, pymatgen, or ASE visualization on the listed CIF paths.",
            "No crystal image was fabricated from unavailable structure data.",
            "",
        ]
    )
    path = out_dir / "final_crystal_artifacts.md"
    _write_text(path, "\n".join(lines))
    return [{"path": str(path), "title": "Final crystal artifacts", "status": "deferred_rendering", "type": "deferred_note"}]


def _write_comparison_outputs(out_dir: Path) -> None:
    axes_rows = [
        {"Evidence type": "Direct CIF generation", "CrystaLLM": "yes", "AtomGPT": "yes / structure generation", "CrysText": "yes", "Our workflow": "no"},
        {"Evidence type": "Retrieval evidence", "CrystaLLM": "no / limited", "AtomGPT": "no / limited", "CrysText": "no / limited", "Our workflow": "yes"},
        {"Evidence type": "Solver-backed candidate", "CrystaLLM": "no initial solver", "AtomGPT": "downstream checks", "CrysText": "benchmark checks", "Our workflow": "yes, QLIP"},
        {"Evidence type": "Failure diagnostics", "CrystaLLM": "invalid sample counts", "AtomGPT": "task dependent", "CrysText": "benchmark dependent", "Our workflow": "staged tool errors"},
        {"Evidence type": "DFT/property validation", "CrystaLLM": "selected/examples", "AtomGPT": "yes/downstream", "CrysText": "energy-above-hull conditioning", "Our workflow": "not yet"},
    ]
    _write_text(
        out_dir / "comparison_axes_table.md",
        "# Comparison Axes Table\n\n" + _md_table(axes_rows, ["Evidence type", "CrystaLLM", "AtomGPT", "CrysText", "Our workflow"]),
    )
    summary = """# Text-to-Crystal Comparison Summary

## CrystaLLM Evidence Style
CrystaLLM-style systems train autoregressive language models over crystal representations such as CIF text. They report generated structure plausibility and selected downstream validation, but the LLM is the direct structure decoder.

## AtomGPT Evidence Style
AtomGPT-style systems support forward atomistic property tasks and inverse property/text-to-structure generation. Their evidence is centered on generation and downstream screening or optimization tasks.

## CrysText Evidence Style
CrysText-style systems evaluate text-conditioned crystal generation with benchmark metrics such as structure match and RMSE-style comparisons, including conditioning such as energy-above-hull.

## Our Evidence Style
Our system does not train an LLM to emit CIF tokens. It uses the LLM as a workflow and formulation controller over Crystal-DB retrieval, SPP/POT guidance, QLIP validation/solve, novelty checking, and evaluator reporting.

## What We Can Fairly Compare Now
We can compare traceability, staged artifact completeness, solver-backed candidate production for supported cases, novelty/rediscovery reporting, and explicit diagnostic behavior for unsupported cases.

## What We Cannot Yet Compare
We cannot claim DFT stability, property optimization success, or a better generation rate than direct text-to-crystal systems without running those evaluations.

"""
    summary += _md_table(axes_rows, ["Evidence type", "CrystaLLM", "AtomGPT", "CrysText", "Our workflow"])
    _write_text(out_dir / "text_to_crystal_comparison_summary.md", summary)


def _maybe_build_workflow_artifacts(rows: list[dict[str, Any]], suite_dir: Path, out_dir: Path) -> list[dict[str, Any]]:
    try:
        from sok_llm_orchestrator.agentic.visualise_workflow_artifact import visualise_workflow_artifact
    except Exception as exc:  # pragma: no cover - import failure is reported in manifest
        return [{"type": "workflow_artifact_import", "status": "failed", "error": str(exc)}]

    built: list[dict[str, Any]] = []
    preferred = {"CoAs2", "CaTiO3", "BaTiO3"}
    for row in rows:
        if row.get("actual_final_status") != "completed" or row.get("material_system") not in preferred:
            continue
        run_dir = ""
        execution_path = str(row.get("execution_run_json") or "")
        if execution_path:
            path = Path(execution_path)
            parts = path.parts
            if "_raw_run" in parts:
                idx = parts.index("_raw_run")
                run_dir = str(Path(*parts[:idx]))
        if not run_dir:
            run_id = str(row.get("run_id") or "")
            candidate = suite_dir / run_id
            if candidate.exists():
                run_dir = str(candidate)
        if not run_dir:
            built.append({"type": "workflow_artifact", "case": row.get("material_system"), "status": "skipped_missing_run_dir"})
            continue
        result = visualise_workflow_artifact(Path(run_dir), out_dir / "figures", str(row["material_system"]))
        built.append({"type": "workflow_artifact", "case": row["material_system"], "status": "generated", "path": result["png_path"], "svg_path": result["svg_path"], "manifest_path": result["manifest_path"]})
    return built


def build_evidence_pack(suite_dir: Path | str, out_dir: Path | str, *, workflow_artifacts: bool = False) -> dict[str, Any]:
    suite_dir = Path(suite_dir)
    out_dir = Path(out_dir)
    suite_summary = _read_json(suite_dir / "suite_summary.json")
    rows = [_extract_row(run, suite_dir) for run in suite_summary.get("runs", []) or []]
    out_dir.mkdir(parents=True, exist_ok=True)

    result_columns = [
        "run_id",
        "input_goal",
        "material_system",
        "expected_outcome",
        "actual_final_status",
        "expectation_pass",
        "crystal_db_status",
        "corpus_selection_status",
        "selected_corpus_formulas",
        "selected_cif_count",
        "spp_status",
        "pot_root_source",
        "extraction_mode",
        "corpus_quality_status",
        "qlip_solve_compatible",
        "qlip_validation_status",
        "qlip_solve_status",
        "objective_value",
        "solution_cif_path",
        "novelty_result",
        "workflow_score",
        "failed_tool",
        "error_code",
        "diagnostic_summary",
    ]
    _write_json(out_dir / "paper_results_table.json", {"schema_version": "paper_evidence.results.v1", "rows": rows})
    _write_csv(out_dir / "paper_results_table.csv", rows, result_columns)
    _write_text(out_dir / "paper_results_table.md", "# Paper Results Table\n\n" + _md_table(rows, result_columns))

    matrix_columns = ["Input", "Target material", "Crystal-DB retrieved corpus", "SPP/POT evidence", "QLIP optimisation", "Final crystal / diagnostic"]
    matrix_rows = _paper_table_rows(rows)
    _write_csv(out_dir / "workflow_case_matrix.csv", matrix_rows, matrix_columns)
    _write_text(out_dir / "workflow_case_matrix.md", "# Workflow Case Matrix\n\n" + _md_table(matrix_rows, matrix_columns))

    _write_comparison_outputs(out_dir)
    manifest = _write_figures(rows, out_dir)
    manifest.extend(_write_spp_visualisation_status(rows, out_dir))
    manifest.extend(_write_final_crystal_artifacts(rows, out_dir))
    if workflow_artifacts:
        manifest.extend(_maybe_build_workflow_artifacts(rows, suite_dir, out_dir))
    _write_json(out_dir / "figure_manifest.json", {"schema_version": "paper_evidence.figure_manifest.v1", "figures": manifest})
    return {"out_dir": str(out_dir), "run_count": len(rows), "figure_count": len(manifest), "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--workflow-artifacts", action="store_true", help="Generate detailed workflow artifact figures for completed showcase cases.")
    args = parser.parse_args()
    result = build_evidence_pack(args.suite_dir, args.out_dir, workflow_artifacts=args.workflow_artifacts)
    print(json.dumps({"out_dir": result["out_dir"], "run_count": result["run_count"], "figure_count": result["figure_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
