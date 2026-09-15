"""Composite reports for unique verifiable CSP benchmarks."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from sca.evaluators.unique_csp import (
    AuditBundleCompletenessBenchmarkEvaluator,
    ConstraintFaithfulnessBenchmarkEvaluator,
    EvidenceFaithfulnessBenchmarkEvaluator,
    EvidenceTraceabilityBenchmarkEvaluator,
    SolverCertificateBenchmarkEvaluator,
)
from sca.traceability.io import inspect_run_bundle


SECTION_TITLES = [
    "Summary",
    "Output validity",
    "Constraint faithfulness",
    "Structure/prototype match",
    "MLIP/relaxation robustness",
    "Evidence traceability",
    "Solver certificate",
    "Audit bundle completeness",
    "Retrieval ablation",
    "Repairability",
    "Failure cases",
    "Why this benchmark is different",
]


def build_unique_csp_summary(
    results: str | Path | None,
    bundles: str | Path,
    out_csv: str | Path,
    json_out: str | Path,
    markdown: str | Path,
) -> dict[str, Any]:
    result_rows = _load_results(results)
    bundle_rows = _bundle_metric_rows(bundles)
    rows = [_aggregate(result_rows, bundle_rows)]
    for key, value in _component_rows(rows[0]).items():
        rows.append({"metric": key, "value": value})

    csv_path = Path(out_csv)
    json_path = Path(json_out)
    md_path = Path(markdown)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps({"rows": rows, "bundle_rows": bundle_rows}, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(rows[0], bundle_rows), encoding="utf-8")
    return {"rows": len(rows), "out_csv": str(csv_path), "json": str(json_path), "markdown": str(md_path)}


def compute_unique_composite(row: dict[str, Any]) -> float:
    return (
        0.20 * _float(row.get("output_validity"), 0.0)
        + 0.20 * _float(row.get("constraint_faithfulness_score"), 0.0)
        + 0.15 * _float(row.get("structure_or_prototype_match_score"), 0.0)
        + 0.15 * _float(row.get("mlip_or_relaxation_robustness_score"), 0.0)
        + 0.15 * _float(row.get("evidence_trace_score"), 0.0)
        + 0.10 * _float(row.get("audit_bundle_score"), 0.0)
        + 0.05 * _float(row.get("solver_certificate_score"), 0.0)
    )


def _load_results(results: str | Path) -> list[dict[str, Any]]:
    if results is None:
        return []
    path = Path(results)
    if not path.exists():
        return []
    return pd.read_csv(path).to_dict(orient="records")


def _bundle_metric_rows(bundles: str | Path) -> list[dict[str, Any]]:
    root = Path(bundles)
    bundle_dirs = [root] if (root / "prompt.txt").exists() else sorted(path for path in root.iterdir() if path.is_dir())
    evaluators = [
        EvidenceTraceabilityBenchmarkEvaluator(),
        ConstraintFaithfulnessBenchmarkEvaluator(),
        SolverCertificateBenchmarkEvaluator(),
        EvidenceFaithfulnessBenchmarkEvaluator(),
        AuditBundleCompletenessBenchmarkEvaluator(),
    ]
    rows = []
    for bundle_dir in bundle_dirs:
        row = {"run_bundle_dir": str(bundle_dir), "run_id": bundle_dir.name}
        inspection = inspect_run_bundle(bundle_dir)
        if inspection.bundle and inspection.bundle.structured_intent:
            row["target_formula"] = inspection.bundle.structured_intent.formula
            row["target_space_group"] = inspection.bundle.structured_intent.space_group
            row["target_structure_family"] = inspection.bundle.structured_intent.prototype_family
        for evaluator in evaluators:
            result = evaluator.evaluate_row(row)
            for key, value in result.metrics.items():
                row[key] = value
                row[f"{evaluator.name}_{key}"] = value
        rows.append(row)
    return rows


def _aggregate(result_rows: list[dict[str, Any]], bundle_rows: list[dict[str, Any]]) -> dict[str, Any]:
    all_rows = result_rows + bundle_rows
    row = {
        "metric": "traceable_constraint_grounded_csp_score",
        "num_result_rows": len(result_rows),
        "num_bundle_rows": len(bundle_rows),
        "output_validity": _mean_key(all_rows, ("pre_dft_valid", "parse_ok")),
        "constraint_faithfulness_score": _mean_key(all_rows, ("constraint_faithfulness_score",)),
        "structure_or_prototype_match_score": _mean_key(
            all_rows,
            ("structure_match", "prototype_match", "target_structure_family_match"),
        ),
        "mlip_or_relaxation_robustness_score": _mean_key(
            all_rows,
            ("mlip_consensus_stable_flag", "relax_ok", "collapse_free"),
        ),
        "evidence_trace_score": _mean_key(all_rows, ("evidence_trace_score",)),
        "audit_bundle_score": _mean_key(all_rows, ("audit_bundle_score",)),
        "solver_certificate_score": _mean_key(all_rows, ("solver_certificate_score",)),
    }
    row["traceable_constraint_grounded_csp_score"] = compute_unique_composite(row)
    return row


def _component_rows(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "output_validity",
        "constraint_faithfulness_score",
        "structure_or_prototype_match_score",
        "mlip_or_relaxation_robustness_score",
        "evidence_trace_score",
        "audit_bundle_score",
        "solver_certificate_score",
        "traceable_constraint_grounded_csp_score",
    ]
    return {key: row.get(key) for key in keys}


def _markdown(summary: dict[str, Any], bundle_rows: list[dict[str, Any]]) -> str:
    lines = ["# Unique Verifiable CSP Benchmark Report", ""]
    for title in SECTION_TITLES:
        lines.extend([f"## {title}", ""])
        if title == "Summary":
            lines.append(
                f"- Composite score: {summary.get('traceable_constraint_grounded_csp_score', 0):.3f}"
            )
            lines.append(f"- Result rows: {summary.get('num_result_rows', 0)}")
            lines.append(f"- Bundle rows: {summary.get('num_bundle_rows', 0)}")
        elif title == "Why this benchmark is different":
            lines.append(
                "Existing crystal-generation benchmarks ask whether a model emitted a plausible CIF. "
                "This benchmark asks whether the text-to-crystal workflow is traceable, "
                "constraint-grounded, solver-backed, auditable, repairable, and reproducible."
            )
        elif title == "Failure cases":
            failures = [row for row in bundle_rows if not row.get("artifact_bundle_complete")]
            lines.append(f"- Bundle failure cases: {len(failures)}")
        else:
            key = _section_key(title)
            lines.append(f"- Mean component value: {summary.get(key, 0):.3f}")
        lines.append("")
    return "\n".join(lines)


def _section_key(title: str) -> str:
    return {
        "Output validity": "output_validity",
        "Constraint faithfulness": "constraint_faithfulness_score",
        "Structure/prototype match": "structure_or_prototype_match_score",
        "MLIP/relaxation robustness": "mlip_or_relaxation_robustness_score",
        "Evidence traceability": "evidence_trace_score",
        "Solver certificate": "solver_certificate_score",
        "Audit bundle completeness": "audit_bundle_score",
    }.get(title, "traceable_constraint_grounded_csp_score")


def _mean_key(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> float:
    values = []
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip() != "":
                parsed = _bool_or_float(value)
                if parsed is not None:
                    values.append(parsed)
                    break
    return sum(values) / len(values) if values else 0.0


def _bool_or_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, float) and math.isnan(value):
        return None
    normalized = str(value).strip().lower()
    if normalized in {"", "nan", "none", "null"}:
        return None
    if normalized in {"true", "yes", "1"}:
        return 1.0
    if normalized in {"false", "no", "0"}:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any, default: float) -> float:
    parsed = _bool_or_float(value)
    return default if parsed is None else parsed
