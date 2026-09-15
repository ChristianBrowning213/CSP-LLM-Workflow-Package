"""Direct CIF-set literature benchmark runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from sca.benchmark import benchmark_folder, benchmark_manifest
from sca.benchmark_protocols.metrics import build_comparator_matrix, compute_metric_results, metric_rows
from sca.benchmark_protocols.registry import select_protocols
from sca.evaluators.registry import get_evaluator_spec
from sca.io import write_csv, write_jsonl


PROTOCOL_LEVELS = {
    "exact_protocol",
    "subset_protocol",
    "approximate_protocol",
    "contextual_only",
    "not_comparable",
}


def run_direct_cif_benchmark(
    *,
    cif_folder: str | Path | None,
    manifest: str | Path | None,
    protocols: str,
    out_csv: str | Path,
    summary_csv: str | Path,
    json_out: str | Path,
    markdown: str | Path,
    evaluators: str = "auto",
    include_relaxation: bool = False,
    relax_backend: str = "chgnet",
    hull_reference: str | Path | None = None,
    reference_corpus: str | Path | None = None,
    protocol_match_level: str = "contextual_only",
    path_col: str = "cif_path",
    attempt_col: str = "attempt_id",
    target_col: str = "benchmark_id",
    method_col: str = "method",
) -> dict[str, Any]:
    if (cif_folder is None) == (manifest is None):
        raise ValueError("Provide exactly one of cif_folder or manifest")
    if protocol_match_level not in PROTOCOL_LEVELS:
        raise ValueError(f"protocol_match_level must be one of {', '.join(sorted(PROTOCOL_LEVELS))}")
    selected_protocols = select_protocols(protocols)
    evaluator_names = _select_evaluators(
        selected_protocols,
        evaluators=evaluators,
        manifest=manifest,
        include_relaxation=include_relaxation,
        relax_backend=relax_backend,
        hull_reference=hull_reference,
    )
    if manifest is not None:
        records = benchmark_manifest(
            manifest,
            evaluator_names=evaluator_names,
            path_col=path_col,
            formula_col="target_formula",
            spacegroup_col="target_space_group",
            target_cif_col="target_cif_path",
            reference_id_col="reference_id",
            method_col=method_col,
            query_id_col=target_col,
            hull_reference_path=hull_reference,
        )
    else:
        records = benchmark_folder(
            cif_folder,
            evaluator_names=evaluator_names,
            method=method_col if method_col and method_col != "method" else "direct_cif_set",
            hull_reference_path=hull_reference,
        )
    out_csv = Path(out_csv)
    out_jsonl = out_csv.with_suffix(".jsonl")
    write_csv(records, out_csv)
    write_jsonl(records, out_jsonl)

    metrics = compute_metric_results(out_csv, target_col=target_col, attempt_col=attempt_col)
    matrix = build_comparator_matrix(selected_protocols, metrics, protocol_match_level)
    summary_rows = matrix + _metric_only_rows(metrics, matrix)
    _write_summary(summary_rows, summary_csv, json_out)
    Path(markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown).write_text(
        render_direct_report(
            summary_rows=summary_rows,
            result_count=len(records),
            selected_protocols=len(selected_protocols),
            evaluator_names=evaluator_names,
            input_label=str(manifest or cif_folder),
            protocol_match_level=protocol_match_level,
        ),
        encoding="utf-8",
    )
    return {
        "records": len(records),
        "results_csv": str(out_csv),
        "results_jsonl": str(out_jsonl),
        "summary_csv": str(summary_csv),
        "summary_json": str(json_out),
        "markdown": str(markdown),
        "evaluators": evaluator_names,
        "protocols": len(selected_protocols),
    }


def protocol_rows_with_computability(results_csv: str | Path | None = None) -> list[dict[str, Any]]:
    protocols = select_protocols("all")
    metrics = compute_metric_results(results_csv) if results_csv else {}
    rows = []
    for protocol in protocols:
        metric = metrics.get(protocol.metric_name)
        row = protocol.to_row()
        row["required_evaluators_available"] = _required_evaluators_available(protocol.required_evaluators)
        row["currently_computable"] = bool(metric and metric.n_computable)
        row["n_computable"] = metric.n_computable if metric else 0
        row["n_not_computable"] = metric.n_not_computable if metric else 0
        rows.append(row)
    return rows


def _required_evaluators_available(evaluators: tuple[str, ...]) -> bool:
    for evaluator in evaluators:
        try:
            if not get_evaluator_spec(evaluator).available:
                return False
        except KeyError:
            return False
    return True


def render_direct_report(
    *,
    summary_rows: list[dict[str, Any]],
    result_count: int,
    selected_protocols: int,
    evaluator_names: list[str],
    input_label: str,
    protocol_match_level: str,
) -> str:
    comparator_rows = [row for row in summary_rows if row.get("paper_value") is not None]
    beaten = [row for row in comparator_rows if row.get("beats_paper") is True]
    not_beaten = [row for row in comparator_rows if row.get("beats_paper") is False]
    not_computable = [row for row in comparator_rows if not row.get("n_computable")]
    lines = [
        "# Literature-Replication Direct CIF Benchmark Report",
        "",
        "## Input set",
        "",
        f"- Input: {input_label}",
        f"- Result rows: {result_count}",
        f"- Protocols selected: {selected_protocols}",
        f"- Protocol match level: {protocol_match_level}",
        f"- Evaluators: {', '.join(evaluator_names)}",
        "",
        "## Computable metrics",
        "",
    ]
    lines.extend(_markdown_table([row for row in summary_rows if row.get("n_computable")]))
    lines.extend(["", "## Comparator matrix", ""])
    lines.extend(_markdown_table(comparator_rows))
    lines.extend(["", "## Values beaten", ""])
    lines.extend(_markdown_table(beaten))
    lines.extend(["", "## Values not beaten", ""])
    lines.extend(_markdown_table(not_beaten))
    lines.extend(["", "## Not-computable metrics", ""])
    lines.extend(_markdown_table(not_computable))
    lines.extend(["", "## Caveats", ""])
    lines.extend(
        [
            "- Contextual comparator values are not leaderboard claims.",
            "- Surrogate MLIP is not DFT.",
            "- Local novelty is not global novelty.",
            "- Subset protocol is not full MP-20/MPTS-52.",
        ]
    )
    lines.extend(["", "## Per-target failures", ""])
    lines.append("Run `paper-target-diagnostics` for per-target failure analysis when reference and relaxation outputs are available.")
    return "\n".join(lines) + "\n"


def _select_evaluators(
    protocols,
    *,
    evaluators: str,
    manifest: str | Path | None,
    include_relaxation: bool,
    relax_backend: str,
    hull_reference: str | Path | None,
) -> list[str]:
    if evaluators != "auto":
        return [name.strip() for name in evaluators.split(",") if name.strip()]
    selected = ["pre_dft_validity"]
    if manifest and _manifest_has_any(manifest, ("target_cif_path", "reference_cif_path")):
        selected.append("structure_match")
    if hull_reference:
        selected.append("predicted_hull")
    if _protocol_requires(protocols, "property_targets") and manifest:
        selected.append("property_targets")
    if include_relaxation:
        if relax_backend != "chgnet":
            raise ValueError("Only --relax-backend chgnet is currently supported")
        selected.append("chgnet_relax")
    return selected


def _protocol_requires(protocols, evaluator: str) -> bool:
    return any(evaluator in protocol.required_evaluators for protocol in protocols)


def _manifest_has_any(manifest: str | Path, columns: tuple[str, ...]) -> bool:
    frame = pd.read_csv(manifest, dtype=str).fillna("")
    return any(column in frame.columns and frame[column].astype(str).str.strip().ne("").any() for column in columns)


def _metric_only_rows(metrics, matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    used = {row["metric_name"] for row in matrix}
    rows = []
    for row in metric_rows(metrics):
        if row["metric_name"] not in used:
            rows.append(
                {
                    "benchmark_family": row["benchmark_family"],
                    "metric_name": row["metric_name"],
                    "our_value": row["our_value"],
                    "paper_value": None,
                    "paper_name": None,
                    "comparator_name": None,
                    "direction": None,
                    "unit": row["unit"],
                    "beats_paper": None,
                    "delta": None,
                    "dataset_scope": None,
                    "protocol_match_level": None,
                    "n_total": row["n_total"],
                    "n_computable": row["n_computable"],
                    "n_not_computable": row["n_not_computable"],
                    "required_inputs_missing": row["required_inputs_missing"],
                    "notes": row["notes"],
                }
            )
    return rows


def _write_summary(rows: list[dict[str, Any]], summary_csv: str | Path, json_out: str | Path) -> None:
    summary_csv = Path(summary_csv)
    json_out = Path(json_out)
    summary_csv.parent.mkdir(parents=True, exist_ok=True)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(summary_csv, index=False)
    json_out.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")


def _markdown_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No rows."]
    columns = [
        "benchmark_family",
        "metric_name",
        "our_value",
        "paper_value",
        "paper_name",
        "beats_paper",
        "protocol_match_level",
        "n_computable",
        "required_inputs_missing",
    ]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows[:100]:
        lines.append("| " + " | ".join(_cell(row.get(column)) for column in columns) + " |")
    return lines


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")
