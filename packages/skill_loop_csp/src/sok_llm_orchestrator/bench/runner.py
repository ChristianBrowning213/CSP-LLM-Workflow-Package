from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.baselines.retrieval_nn import run_retrieval_nn_baseline
from sok_llm_orchestrator.baselines.template_baseline import run_template_baseline
from sok_llm_orchestrator.bench.cases import load_case_set, validate_case
from sok_llm_orchestrator.bench.reporting import build_benchmark_report, build_optimization_benchmark_report
from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.phase1_properties import (
    Phase1BenchmarkModeError,
    Phase1PropertyEntry,
    qlip_objective_for_phase1_entry,
    require_phase1_property_for_benchmark,
)
from sok_llm_orchestrator.contracts.phase2_external_predictors import (
    Phase2ExternalPredictorBenchmarkModeError,
    require_phase2_external_predictor_for_benchmark,
)
from sok_llm_orchestrator.contracts.phase3_external_predictors import (
    Phase3ExternalPredictorBenchmarkModeError,
    require_phase3_external_predictor_for_benchmark,
)
from sok_llm_orchestrator.external_predictors.adapters import normalize_external_predictor_requests
from sok_llm_orchestrator.contracts.qlip_schema import QLIPValidationError, validate_qlip_objective
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.optimization.reporting import regenerate_report_from_session_artifacts
from sok_llm_orchestrator.orchestrator.paired_run import run_paired_baseline_guided
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle


def _case_hypotheses(case: dict[str, Any]) -> list[dict[str, Any]]:
    value = case.get("hypotheses")
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        rows.append(dict(item))
    return rows


def _benchmark_id(case_path: Path, mode: str) -> str:
    text = f"{case_path.resolve()}:{mode}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _stub_retrieval_bundle(composition: str, retrieval_mode: str) -> RetrievalBundle:
    return RetrievalBundle(
        retrieval_id=f"retrieval-{composition}-{retrieval_mode}",
        mode=retrieval_mode,
        fusion_notes=["stub"],
        items=[
            {
                "structure_id": f"{composition}-nn",
                "provenance": "stub",
                "scores": {"score": 0.9},
                "modality": retrieval_mode if retrieval_mode != "hybrid" else "hybrid",
                "identity": None,
                "cell_hint": None,
                "why_returned": "stub benchmark retrieval",
            }
        ],
    )


def _validate_case_phase1_property(case: dict[str, Any], *, strict_phase1_benchmark_mode: bool) -> None:
    objective_payload = case.get("qlip_objective")
    if objective_payload is not None:
        if not isinstance(objective_payload, dict):
            raise ValueError(f"{case.get('case_id', '<unknown>')}: PHASE1_BENCHMARK_REJECTED_MALFORMED_QLIP_OBJECTIVE")
        try:
            validate_qlip_objective(objective_payload)
        except QLIPValidationError as exc:
            raise ValueError(
                f"{case.get('case_id', '<unknown>')}: PHASE1_BENCHMARK_REJECTED_MALFORMED_QLIP_OBJECTIVE: {exc}"
            ) from exc
    if not strict_phase1_benchmark_mode:
        return
    property_bias = case.get("property_bias")
    if not isinstance(property_bias, str) or not property_bias.strip():
        return
    try:
        entry = require_phase1_property_for_benchmark(property_bias)
    except Phase1BenchmarkModeError as exc:
        raise ValueError(f"{case.get('case_id', '<unknown>')}: {exc.code}: {exc}") from exc
    if isinstance(objective_payload, dict) and isinstance(entry.qlip_objective_family, str):
        actual_type = objective_payload.get("type")
        if actual_type != entry.qlip_objective_family:
            raise ValueError(
                f"{case.get('case_id', '<unknown>')}: PHASE1_BENCHMARK_REJECTED_OBJECTIVE_MISMATCH: "
                f"{property_bias} maps to {entry.qlip_objective_family}, got {actual_type}"
            )


def _require_external_predictor_for_benchmark(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        predictor_id: Any = item
    elif isinstance(item, dict):
        predictor_id = item.get("predictor_id")
    else:
        predictor_id = None
    if isinstance(predictor_id, str) and predictor_id.startswith("phase3."):
        return require_phase3_external_predictor_for_benchmark(item)
    if isinstance(predictor_id, str) and predictor_id.startswith("phase2."):
        return require_phase2_external_predictor_for_benchmark(item)
    try:
        return require_phase2_external_predictor_for_benchmark(item)
    except Phase2ExternalPredictorBenchmarkModeError:
        return require_phase3_external_predictor_for_benchmark(item)


def _validate_case_external_predictors(
    case: dict[str, Any],
    *,
    strict_phase1_benchmark_mode: bool,
) -> None:
    raw = case.get("external_predictors")
    if raw is None:
        return
    if not isinstance(raw, list):
        raise ValueError(
            f"{case.get('case_id', '<unknown>')}: PHASE2_BENCHMARK_REJECTED_MALFORMED_EXTERNAL_PREDICTOR_REQUEST"
        )
    if not strict_phase1_benchmark_mode:
        normalize_external_predictor_requests(raw)
        return
    for item in raw:
        try:
            _require_external_predictor_for_benchmark(item)
        except (Phase2ExternalPredictorBenchmarkModeError, Phase3ExternalPredictorBenchmarkModeError) as exc:
            raise ValueError(f"{case.get('case_id', '<unknown>')}: {exc.code}: {exc}") from exc


def _phase1_objective_override_for_case(case: dict[str, Any]) -> dict[str, Any] | None:
    objective_payload = case.get("qlip_objective")
    if isinstance(objective_payload, dict):
        return dict(objective_payload)
    property_bias = case.get("property_bias")
    if not isinstance(property_bias, str) or not property_bias.strip():
        return None
    try:
        entry: Phase1PropertyEntry = require_phase1_property_for_benchmark(property_bias)
    except Phase1BenchmarkModeError:
        return None
    if not isinstance(entry.qlip_objective_family, str):
        return None
    return qlip_objective_for_phase1_entry(entry, formula=str(case.get("composition", "")))


def _case_execution_overrides(case: dict[str, Any]) -> dict[str, Any] | None:
    overrides: dict[str, Any] = {}
    objective_payload = _phase1_objective_override_for_case(case)
    if isinstance(objective_payload, dict):
        overrides["qlip_objective"] = objective_payload
    external_predictors = normalize_external_predictor_requests(case.get("external_predictors"))
    if external_predictors:
        overrides["external_predictors"] = external_predictors
    return overrides or None


def run_benchmark_cases(
    case_file: Path,
    mode: str,
    workspace: Path,
    settings: Settings,
    strict_phase1_benchmark_mode: bool = False,
) -> dict[str, Any]:
    cases = load_case_set(case_file)
    for case in cases:
        validate_case(case)
        _validate_case_phase1_property(case, strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode))
        _validate_case_external_predictors(case, strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode))

    bench_id = _benchmark_id(case_file, mode)
    bench_dir = workspace / "benchmarks" / bench_id
    bench_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    property_assertion_failures: list[str] = []
    for case in cases:
        property_bias = case.get("property_bias")
        query = f"{case['composition']} benchmark case {case['case_id']}"
        if isinstance(property_bias, str) and property_bias:
            query = f"{query}; prioritize high {property_bias}"
        case_overrides = _case_execution_overrides(case)
        case_objective = case_overrides.get("qlip_objective") if isinstance(case_overrides, dict) else None
        paired = run_paired_baseline_guided(
            query=query,
            mode=mode,
            workspace=workspace,
            settings=settings,
            baseline_execution_overrides=case_overrides,
            guided_execution_overrides=case_overrides,
            strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
        )
        paired_payload = json.loads(paired.report_path.read_text(encoding="utf-8"))
        external_phase2 = paired_payload.get("external_phase2", {})
        external_phase3 = paired_payload.get("external_phase3", {})
        retrieval = _stub_retrieval_bundle(case["composition"], case["retrieval_mode"])
        nn = run_retrieval_nn_baseline(retrieval)
        template = run_template_baseline(case["case_id"], case["composition"])
        property_assertion_status = paired_payload.get("property_assertion_status")
        if property_assertion_status == "fail":
            property_assertion_failures.append(case["case_id"])
        rows.append(
            {
                "case_id": case["case_id"],
                "case_class": case.get("case_class"),
                "challenge_class": case.get("challenge_class"),
                "guidance_rationale": case.get("guidance_rationale"),
                "recommended_guidance_focus": case.get("recommended_guidance_focus"),
                "suggested_structural_dimensions": list(case.get("suggested_structural_dimensions", []))
                if isinstance(case.get("suggested_structural_dimensions"), list)
                else [],
                "suggested_corpus_bias": case.get("suggested_corpus_bias"),
                "suggested_perturbation_bias": case.get("suggested_perturbation_bias"),
                "hypotheses": _case_hypotheses(case),
                "composition": case["composition"],
                "paired_report": str(paired.report_path),
                "baseline_run_id": paired.baseline.run_id,
                "guided_run_id": paired.guided.run_id,
                "baseline_status": paired.baseline.status,
                "guided_status": paired.guided.status,
                "property_key": paired_payload.get("property_key"),
                "qlip_objective_family": (
                    str(case_objective.get("type"))
                    if isinstance(case_objective, dict) and isinstance(case_objective.get("type"), str)
                    else None
                ),
                "baseline_property": paired_payload.get("baseline_property"),
                "guided_property": paired_payload.get("guided_property"),
                "external_phase2": external_phase2 if isinstance(external_phase2, dict) else {},
                "external_phase3": external_phase3 if isinstance(external_phase3, dict) else {},
                "property_assertion_status": property_assertion_status,
                "retrieval_nn": nn,
                "template_baseline": template,
            }
        )
    raw = {
        "schema_version": "benchmark.run.v1",
        "benchmark_id": bench_id,
        "case_file": str(case_file.resolve()),
        "strict_phase1_benchmark_mode": bool(strict_phase1_benchmark_mode),
        "rows": rows,
        "property_assertion_failures": property_assertion_failures,
    }
    raw_path = bench_dir / "benchmark_results.json"
    raw_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = build_benchmark_report(raw)
    report_path = bench_dir / "benchmark_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"benchmark_id": bench_id, "results_path": str(raw_path), "report_path": str(report_path)}


def run_optimization_benchmark_cases(
    case_file: Path,
    mode: str,
    workspace: Path,
    settings: Settings,
    executor_factory: Any = None,
    max_iterations: int | None = None,
    strict_phase1_benchmark_mode: bool = False,
) -> dict[str, Any]:
    cases = load_case_set(case_file)
    for case in cases:
        validate_case(case)
        _validate_case_phase1_property(case, strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode))
        _validate_case_external_predictors(case, strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode))

    bench_id = "opt-" + _benchmark_id(case_file, mode)
    bench_dir = workspace / "benchmarks" / bench_id
    bench_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for case in cases:
        case_settings = copy.deepcopy(settings)
        if max_iterations is not None:
            case_settings.optimization_max_iterations = int(max_iterations)
        query = f"{case['composition']} optimization benchmark case {case['case_id']}"
        property_bias = case.get("property_bias")
        if isinstance(property_bias, str) and property_bias:
            query = f"{query}; prioritize high {property_bias}"
        case_objective = _phase1_objective_override_for_case(case)
        executor = executor_factory(case) if callable(executor_factory) else None
        engine = OptimizationEngine(
            workspace=workspace,
            settings=case_settings,
            mode=mode,
            executor=executor,
        )
        start = engine.start(
            query=query,
            auto_run=True,
            seed_hint=f"benchmark:{case['case_id']}",
            case_metadata=case,
            strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
        )
        session = engine.get(start.session_id)
        report = regenerate_report_from_session_artifacts(start.session_path)
        rows.append(
            {
                "case_id": case["case_id"],
                "case_class": case.get("case_class"),
                "challenge_class": case.get("challenge_class"),
                "guidance_rationale": case.get("guidance_rationale"),
                "recommended_guidance_focus": case.get("recommended_guidance_focus"),
                "suggested_structural_dimensions": list(case.get("suggested_structural_dimensions", []))
                if isinstance(case.get("suggested_structural_dimensions"), list)
                else [],
                "suggested_corpus_bias": case.get("suggested_corpus_bias"),
                "suggested_perturbation_bias": case.get("suggested_perturbation_bias"),
                "hypotheses": _case_hypotheses(case),
                "session_id": session.session_id,
                "session_path": str(start.session_path),
                "iteration_count": report.get("iteration_count"),
                "initial_best_score": report.get("initial_score"),
                "final_best_score": report.get("final_best_score"),
                "improvement_delta": report.get("improvement_delta"),
                "stop_reason": report.get("termination_reason"),
                "failure_category": report.get("failure_taxonomy", {}).get("primary_category"),
                "qlip_objective_family": (
                    str(case_objective.get("type"))
                    if isinstance(case_objective, dict) and isinstance(case_objective.get("type"), str)
                    else None
                ),
            }
        )

    raw = {
        "schema_version": "benchmark.optimization.run.v1",
        "benchmark_id": bench_id,
        "case_file": str(case_file.resolve()),
        "strict_phase1_benchmark_mode": bool(strict_phase1_benchmark_mode),
        "rows": rows,
    }
    raw_path = bench_dir / "optimization_benchmark_results.json"
    raw_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = build_optimization_benchmark_report(raw)
    report_path = bench_dir / "optimization_benchmark_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"benchmark_id": bench_id, "results_path": str(raw_path), "report_path": str(report_path)}
