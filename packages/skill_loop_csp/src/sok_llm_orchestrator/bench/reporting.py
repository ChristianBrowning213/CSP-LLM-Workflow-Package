from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.metrics.result_schema import validate_result_payload
from sok_llm_orchestrator.optimization.reporting import regenerate_report_from_session_artifacts


def _row_to_metric(row: dict[str, Any]) -> dict[str, Any]:
    baseline_ok = row.get("baseline_status") == "SUCCEEDED"
    guided_ok = row.get("guided_status") == "SUCCEEDED"
    notes: list[str] = []
    property_key = row.get("property_key")
    qlip_objective_family = row.get("qlip_objective_family")
    if isinstance(qlip_objective_family, str) and qlip_objective_family:
        notes.append(f"qlip_objective_family:{qlip_objective_family}")
    baseline_property = row.get("baseline_property")
    guided_property = row.get("guided_property")
    external_phase2 = row.get("external_phase2")
    if isinstance(external_phase2, dict):
        guided = external_phase2.get("guided", {})
        predictions = guided.get("predictions", []) if isinstance(guided, dict) else []
        if isinstance(predictions, list):
            for prediction in predictions:
                if not isinstance(prediction, dict):
                    continue
                notes.append(
                    "phase2_external:"
                    f"{prediction.get('predictor_id')}:{prediction.get('target')}={prediction.get('value')}"
                )
    external_phase3 = row.get("external_phase3")
    if isinstance(external_phase3, dict):
        guided = external_phase3.get("guided", {})
        predictions = guided.get("predictions", []) if isinstance(guided, dict) else []
        if isinstance(predictions, list):
            for prediction in predictions:
                if not isinstance(prediction, dict):
                    continue
                notes.append(
                    "phase3_external:"
                    f"{prediction.get('predictor_id')}:{prediction.get('target')}={prediction.get('value')}"
                )
    if property_key and baseline_property is not None and guided_property is not None:
        notes.append(f"property:{property_key}")
        notes.append(f"baseline_property:{baseline_property}")
        notes.append(f"guided_property:{guided_property}")
        notes.append(f"property_improved:{guided_property > baseline_property}")
    return {
        "case_id": row["case_id"],
        "run_family": "qlip_retrieval_spp",
        "feasible": guided_ok,
        "time_to_first_feasible_s": 0.0 if guided_ok else None,
        "objective_value": None,
        "retry_count": 0,
        "analogue_distance": 0.0,
        "space_group_match": baseline_ok and guided_ok,
        "evidence_completeness": 1.0,
        "reproducible": True,
        "notes": notes,
    }


def build_benchmark_report(benchmark_raw: dict[str, Any]) -> dict[str, Any]:
    rows = benchmark_raw.get("rows", [])
    metrics_rows = [_row_to_metric(row) for row in rows]
    wins = sum(1 for row in rows if row.get("guided_status") == "SUCCEEDED" and row.get("baseline_status") != "SUCCEEDED")
    losses = sum(1 for row in rows if row.get("guided_status") != "SUCCEEDED" and row.get("baseline_status") == "SUCCEEDED")
    ties = len(rows) - wins - losses
    property_available = [
        row
        for row in rows
        if row.get("property_key") and row.get("baseline_property") is not None and row.get("guided_property") is not None
    ]
    property_pass = sum(
        1
        for row in property_available
        if isinstance(row.get("guided_property"), (int, float))
        and isinstance(row.get("baseline_property"), (int, float))
        and float(row["guided_property"]) > float(row["baseline_property"])
    )
    property_fail = len(property_available) - property_pass
    external_rows = [
        row
        for row in rows
        if isinstance(row.get("external_phase2"), dict)
        and isinstance(row["external_phase2"].get("guided"), dict)
        and row["external_phase2"]["guided"].get("predictions")
    ]
    external_phase3_rows = [
        row
        for row in rows
        if isinstance(row.get("external_phase3"), dict)
        and isinstance(row["external_phase3"].get("guided"), dict)
        and row["external_phase3"]["guided"].get("predictions")
    ]
    case_classes = sorted({row.get("case_class") for row in rows if row.get("case_class")})
    payload = {
        "schema_version": "metrics.result.v1",
        "generated_at": "deterministic",
        "rows": metrics_rows,
        "summary": {
            "total_cases": len(rows),
            "feasibility_rate": (sum(1 for row in metrics_rows if row["feasible"]) / len(rows)) if rows else 0.0,
            "guided_win_rate": (wins / len(rows)) if rows else None,
        },
    }
    validate_result_payload(payload)
    return {
        "schema_version": "benchmark.report.v1",
        "benchmark_id": benchmark_raw.get("benchmark_id"),
        "per_case_table": rows,
        "aggregate_summary": payload["summary"],
        "baseline_vs_guided": {"wins": wins, "losses": losses, "ties": ties},
        "property_comparison": {
            "available_count": len(property_available),
            "pass_count": property_pass,
            "fail_count": property_fail,
            "all_pass": property_fail == 0,
        },
        "external_phase2_summary": {
            "rows_with_external_predictions": len(external_rows),
            "native_phase1_objective": False,
            "predictor_ids": sorted(
                {
                    str(prediction.get("predictor_id"))
                    for row in external_rows
                    for prediction in row["external_phase2"]["guided"].get("predictions", [])
                    if isinstance(prediction, dict) and isinstance(prediction.get("predictor_id"), str)
                }
            ),
        },
        "external_phase3_summary": {
            "rows_with_external_predictions": len(external_phase3_rows),
            "native_phase1_objective": False,
            "predictor_ids": sorted(
                {
                    str(prediction.get("predictor_id"))
                    for row in external_phase3_rows
                    for prediction in row["external_phase3"]["guided"].get("predictions", [])
                    if isinstance(prediction, dict) and isinstance(prediction.get("predictor_id"), str)
                }
            ),
        },
        "retrieval_ablation": {"modes": sorted({row.get("retrieval_nn", {}).get("mode") for row in rows})},
        "case_class_summary": {"classes": case_classes, "count": len(case_classes)},
        "reproducibility": {"all_reproducible": all(row.get("baseline_status") and row.get("guided_status") for row in rows)},
        "metrics_payload": payload,
    }


def compare_benchmark_reports(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_summary = left.get("aggregate_summary", {})
    right_summary = right.get("aggregate_summary", {})
    return {
        "schema_version": "benchmark.compare.v1",
        "left_benchmark_id": left.get("benchmark_id"),
        "right_benchmark_id": right.get("benchmark_id"),
        "delta_feasibility_rate": right_summary.get("feasibility_rate", 0.0) - left_summary.get("feasibility_rate", 0.0),
        "delta_guided_win_rate": (right_summary.get("guided_win_rate") or 0.0) - (left_summary.get("guided_win_rate") or 0.0),
    }


def build_optimization_benchmark_report(benchmark_raw: dict[str, Any]) -> dict[str, Any]:
    rows = list(benchmark_raw.get("rows", []))
    deltas = [float(row["improvement_delta"]) for row in rows if isinstance(row.get("improvement_delta"), (int, float))]
    improved = sum(1 for d in deltas if d > 0.0)
    case_classes = sorted({row.get("case_class") for row in rows if row.get("case_class")})
    aggregate = {
        "total_cases": len(rows),
        "improved_cases": improved,
        "improvement_rate": (improved / len(rows)) if rows else 0.0,
        "mean_improvement_delta": (sum(deltas) / len(deltas)) if deltas else 0.0,
        "case_classes": case_classes,
    }
    return {
        "schema_version": "benchmark.optimization.report.v1",
        "benchmark_id": benchmark_raw.get("benchmark_id"),
        "per_case_table": rows,
        "aggregate_summary": aggregate,
    }


def regenerate_optimization_benchmark_report(results_path: Path) -> dict[str, Any]:
    raw = json.loads(results_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for row in raw.get("rows", []):
        session_path = Path(str(row["session_path"]))
        report = regenerate_report_from_session_artifacts(session_path)
        rows.append(
            {
                "case_id": row["case_id"],
                "case_class": row.get("case_class"),
                "challenge_class": row.get("challenge_class"),
                "guidance_rationale": row.get("guidance_rationale"),
                "recommended_guidance_focus": row.get("recommended_guidance_focus"),
                "suggested_structural_dimensions": list(row.get("suggested_structural_dimensions", []))
                if isinstance(row.get("suggested_structural_dimensions"), list)
                else [],
                "suggested_corpus_bias": row.get("suggested_corpus_bias"),
                "suggested_perturbation_bias": row.get("suggested_perturbation_bias"),
                "hypotheses": list(row.get("hypotheses", [])) if isinstance(row.get("hypotheses"), list) else [],
                "session_id": row["session_id"],
                "session_path": str(session_path),
                "iteration_count": report.get("iteration_count"),
                "initial_best_score": report.get("initial_score"),
                "final_best_score": report.get("final_best_score"),
                "improvement_delta": report.get("improvement_delta"),
                "stop_reason": report.get("termination_reason"),
                "failure_category": report.get("failure_taxonomy", {}).get("primary_category"),
            }
        )
    rebuilt = {
        "schema_version": "benchmark.optimization.run.v1",
        "benchmark_id": raw.get("benchmark_id"),
        "case_file": raw.get("case_file"),
        "rows": rows,
    }
    return build_optimization_benchmark_report(rebuilt)
