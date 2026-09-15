from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.backend_sensitivity import objective_audit_from_run_dir
from sok_llm_orchestrator.orchestrator.pipeline import PipelineRun, run_csp_pipeline
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query


@dataclass(slots=True)
class PairedRunResult:
    pair_id: str
    baseline: PipelineRun
    guided: PipelineRun
    report_path: Path


def _objective_from_run(run: PipelineRun) -> float | None:
    audit = objective_audit_from_run_dir(run.run_dir)
    if not isinstance(audit, dict):
        return None
    value = audit.get("objective_total")
    return float(value) if isinstance(value, (int, float)) else None


def _property_from_run(run: PipelineRun, property_key: str) -> float | None:
    solve_path = run.run_dir / "artifacts" / "qlip_solve.json"
    if not solve_path.exists():
        return None
    payload = json.loads(solve_path.read_text(encoding="utf-8"))
    root = payload.get("result", payload).get("result", {})
    outputs = root.get("outputs", {})
    estimates = outputs.get("property_estimates", {})
    if isinstance(estimates, dict) and property_key in estimates:
        value = estimates.get(property_key)
        return float(value) if isinstance(value, (int, float)) else None
    summary = root.get("summary", {})
    value = summary.get(property_key)
    return float(value) if isinstance(value, (int, float)) else None


def _external_predictions_from_run(run: PipelineRun) -> dict:
    path = run.run_dir / "artifacts" / "external_predictions.json"
    if not path.exists():
        return {
            "schema_version": "external_predictions.v1",
            "native_phase1_objective": False,
            "requests": [],
            "predictions": [],
            "errors": [],
            "ok": True,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _external_predictions_for_phase(payload: dict, phase: str) -> dict:
    prefix = f"{phase}.external."
    requests = [
        item
        for item in payload.get("requests", [])
        if isinstance(item, dict) and str(item.get("predictor_id", "")).startswith(prefix)
    ]
    predictions = [
        item
        for item in payload.get("predictions", [])
        if isinstance(item, dict) and str(item.get("predictor_id", "")).startswith(prefix)
    ]
    errors = [
        item
        for item in payload.get("errors", [])
        if isinstance(item, dict) and str(item.get("predictor_id", "")).startswith(prefix)
    ]
    return {
        "schema_version": f"{phase}.external_predictions.v1",
        "native_phase1_objective": False,
        "requests": requests,
        "predictions": predictions,
        "errors": errors,
        "ok": not errors,
    }


def run_paired_baseline_guided(
    query: str,
    mode: str,
    workspace: Path,
    settings: Settings,
    baseline_execution_overrides: dict | None = None,
    guided_execution_overrides: dict | None = None,
    baseline_with_spp: bool = False,
    guided_with_spp: bool = True,
    baseline_query: str | None = None,
    guided_query: str | None = None,
    strict_phase1_benchmark_mode: bool = False,
) -> PairedRunResult:
    base_query = baseline_query or query
    guide_query = guided_query or query
    task_spec = task_spec_from_query(guide_query)
    property_key = task_spec.property_bias
    baseline = run_csp_pipeline(
        query=base_query,
        with_spp=baseline_with_spp,
        mode=mode,
        workspace=workspace,
        settings=settings,
        execution_overrides=baseline_execution_overrides,
        strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
    )
    guided = run_csp_pipeline(
        query=guide_query,
        with_spp=guided_with_spp,
        mode=mode,
        workspace=workspace,
        settings=settings,
        execution_overrides=guided_execution_overrides,
        strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
    )
    pair_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{query}:{mode}:{baseline.run_id}:{guided.run_id}:{baseline_execution_overrides}:{guided_execution_overrides}",
        )
    )
    pair_dir = workspace / "paired" / pair_id
    pair_dir.mkdir(parents=True, exist_ok=True)
    baseline_property = _property_from_run(baseline, property_key) if property_key else None
    guided_property = _property_from_run(guided, property_key) if property_key else None
    baseline_objective_audit = objective_audit_from_run_dir(baseline.run_dir)
    guided_objective_audit = objective_audit_from_run_dir(guided.run_dir)
    baseline_external_predictions = _external_predictions_from_run(baseline)
    guided_external_predictions = _external_predictions_from_run(guided)
    property_assertion_pass: bool | None = None
    property_assertion_status = "not_available"
    if property_key and baseline_property is not None and guided_property is not None:
        property_assertion_pass = guided_property > baseline_property
        property_assertion_status = "pass" if property_assertion_pass else "fail"

    report = {
        "schema_version": "paired_run_report.v1",
        "pair_id": pair_id,
        "baseline_run_id": baseline.run_id,
        "guided_run_id": guided.run_id,
        "baseline_status": baseline.status,
        "guided_status": guided.status,
        "baseline_objective": _objective_from_run(baseline),
        "guided_objective": _objective_from_run(guided),
        "baseline_objective_audit": baseline_objective_audit,
        "guided_objective_audit": guided_objective_audit,
        "property_key": property_key,
        "baseline_property": baseline_property,
        "guided_property": guided_property,
        "property_assertion_status": property_assertion_status,
        "property_assertion_pass": property_assertion_pass,
        "external_predictors": {
            "native_phase1_objective": False,
            "baseline": baseline_external_predictions,
            "guided": guided_external_predictions,
        },
        "external_phase2": {
            "native_phase1_objective": False,
            "baseline": _external_predictions_for_phase(baseline_external_predictions, "phase2"),
            "guided": _external_predictions_for_phase(guided_external_predictions, "phase2"),
        },
        "external_phase3": {
            "native_phase1_objective": False,
            "baseline": _external_predictions_for_phase(baseline_external_predictions, "phase3"),
            "guided": _external_predictions_for_phase(guided_external_predictions, "phase3"),
        },
    }
    report_path = pair_dir / "comparison.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return PairedRunResult(pair_id=pair_id, baseline=baseline, guided=guided, report_path=report_path)
