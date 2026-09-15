from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.action_compile import (
    compile_action,
    compiled_config_signature,
    enforce_compiled_action_semantics,
)
from sok_llm_orchestrator.optimization.action_registry import get_action
from sok_llm_orchestrator.optimization.backend_sensitivity import (
    DIMENSION_KEY_MAP,
    action_dimensions_from_compiled,
    build_sensitivity_trace_matrix,
    build_request_objective_diff_summary,
    classify_backend_sensitivity,
    classify_dimension_roles,
    classify_override_key_effect,
    classify_override_propagation,
    execution_signature_from_compiled,
    objective_audit_from_execution,
    objective_audit_from_run_dir,
    request_trace_from_run_dir,
    summarize_action_library_relevance,
    summarize_dimension_sensitivity,
    summarize_override_propagation,
)
from sok_llm_orchestrator.orchestrator.paired_run import run_paired_baseline_guided

ForcedExecutorFn = Callable[[str, dict[str, Any]], dict[str, Any]]

DEFAULT_FORCED_ACTIONS = [
    "baseline_control",
    "guided_hybrid_balanced",
    "guided_property_push",
    "retrieval_text_explore",
    "cell_policy_probe",
]


def _experiment_id(query: str, mode: str, action_ids: list[str]) -> str:
    payload = {"query": query, "mode": mode, "actions": action_ids}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"sensitivity-{digest}"


def _key_ablation_experiment_id(
    query: str,
    mode: str,
    base_action_id: str,
    dimensions: list[str],
    variant_values: dict[str, Any] | None,
) -> str:
    payload = {
        "query": query,
        "mode": mode,
        "base_action_id": base_action_id,
        "dimensions": dimensions,
        "variant_values": variant_values or {},
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"key-ablation-{digest}"


def _normalize_action_ids(action_ids: list[str] | None) -> list[str]:
    ids = action_ids or list(DEFAULT_FORCED_ACTIONS)
    out: list[str] = []
    for item in ids:
        value = str(item).strip()
        if not value or value in out:
            continue
        out.append(value)
    return out


def _normalize_dimensions(dimensions: list[str] | None) -> list[str]:
    dims = dimensions or list(DIMENSION_KEY_MAP.keys())
    out: list[str] = []
    for item in dims:
        value = str(item).strip()
        if not value or value in out:
            continue
        if value not in DIMENSION_KEY_MAP:
            raise ValueError(f"Unknown key-ablation dimension: {value}")
        out.append(value)
    return out


def _hydrate_row_from_artifacts(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    request_trace = out.get("request_trace", {})
    if not isinstance(request_trace, dict):
        request_trace = {}
    run_reference = out.get("run_reference", {})
    if not isinstance(run_reference, dict):
        run_reference = {}
    run_dir = run_reference.get("guided_run_dir")
    if isinstance(run_dir, str) and run_dir:
        refreshed_trace = request_trace_from_run_dir(Path(run_dir))
        merged = dict(refreshed_trace)
        merged.update(request_trace)
        # Keep richer regenerated fields when older rows only have minimal request trace.
        for key, value in refreshed_trace.items():
            if key not in request_trace:
                merged[key] = value
        request_trace = merged
        if not isinstance(out.get("objective_audit"), dict):
            refreshed_objective = objective_audit_from_run_dir(Path(run_dir))
            if isinstance(refreshed_objective, dict):
                out["objective_audit"] = refreshed_objective
    out["request_trace"] = request_trace
    return out


def _build_report(raw: dict[str, Any]) -> dict[str, Any]:
    rows = list(raw.get("rows", []))
    unique_action_ids = sorted({str(row.get("action_id")) for row in rows if row.get("action_id")})
    unique_compiled = sorted({str(row.get("compiled_config_signature")) for row in rows if row.get("compiled_config_signature")})
    unique_executable = sorted({str(row.get("executable_signature")) for row in rows if row.get("executable_signature")})
    objective_totals = sorted(
        {
            round(float(row["objective_audit"]["objective_total"]), 12)
            for row in rows
            if isinstance(row.get("objective_audit"), dict)
            and isinstance(row["objective_audit"].get("objective_total"), (int, float))
        }
    )
    objective_term_signatures = sorted(
        {
            str(row["objective_audit"].get("objective_terms_signature"))
            for row in rows
            if isinstance(row.get("objective_audit"), dict)
            and isinstance(row["objective_audit"].get("objective_terms_signature"), str)
        }
    )
    classification = classify_backend_sensitivity(
        unique_action_ids=len(unique_action_ids),
        unique_compiled_signatures=len(unique_compiled),
        unique_executable_signatures=len(unique_executable),
        unique_objective_totals=len(objective_totals),
        unique_objective_term_signatures=len(objective_term_signatures),
    )
    dim_summary = summarize_dimension_sensitivity(rows)
    return {
        "schema_version": "forced_sensitivity.report.v1",
        "experiment_id": raw.get("experiment_id"),
        "mode": raw.get("mode"),
        "query": raw.get("query"),
        "rows": rows,
        "diagnostics": {
            "unique_action_id_count": len(unique_action_ids),
            "unique_compiled_config_signature_count": len(unique_compiled),
            "unique_executable_signature_count": len(unique_executable),
            "unique_objective_total_value_count": len(objective_totals),
            "unique_objective_term_signature_count": len(objective_term_signatures),
            "backend_sensitivity_classification": classification,
            "dimension_sensitivity_summary": dim_summary,
        },
    }


def _execute_row(
    *,
    iteration_index: int,
    query: str,
    mode: str,
    workspace: Path,
    settings: Settings,
    compiled_dict: dict[str, Any],
    executor: ForcedExecutorFn | None,
) -> dict[str, Any]:
    compiled_sig = compiled_config_signature(compiled_dict, include_action_identity=False)
    exec_sig = execution_signature_from_compiled(query=query, mode=mode, compiled=compiled_dict)
    objective_audit: dict[str, Any]
    request_trace: dict[str, Any]
    run_reference: dict[str, Any]
    if executor is not None:
        query_with_hints = query if not compiled_dict.get("query_suffix") else f"{query} {compiled_dict['query_suffix']}".strip()
        execution = executor(query_with_hints, compiled_dict)
        objective_audit = objective_audit_from_execution(execution)
        request_trace = (
            dict(execution.get("guided_request_trace", {}))
            if isinstance(execution.get("guided_request_trace"), dict)
            else {"effective_overrides": dict(compiled_dict.get("guided_overrides", {}))}
        )
        run_reference = dict(execution.get("run_reference", {})) if isinstance(execution.get("run_reference"), dict) else {}
    else:
        query_with_hints = query if not compiled_dict.get("query_suffix") else f"{query} {compiled_dict['query_suffix']}".strip()
        paired = run_paired_baseline_guided(
            query=query_with_hints,
            mode=mode,
            workspace=workspace,
            settings=settings,
            baseline_execution_overrides=compiled_dict.get("baseline_overrides"),
            guided_execution_overrides=compiled_dict.get("guided_overrides"),
            guided_with_spp=bool(compiled_dict.get("guided_with_spp", True)),
        )
        objective_audit = objective_audit_from_run_dir(paired.guided.run_dir) or {}
        request_trace = request_trace_from_run_dir(paired.guided.run_dir)
        run_reference = {
            "pair_id": paired.pair_id,
            "baseline_run_id": paired.baseline.run_id,
            "guided_run_id": paired.guided.run_id,
            "baseline_run_dir": str(paired.baseline.run_dir),
            "guided_run_dir": str(paired.guided.run_dir),
            "report_path": str(paired.report_path),
        }
    return {
        "iteration_index": iteration_index,
        "action_id": str(compiled_dict.get("action_id")),
        "action_family": str(compiled_dict.get("action_family")),
        "compiled_action": compiled_dict,
        "action_dimensions": action_dimensions_from_compiled(compiled_dict),
        "compiled_config_signature": compiled_sig,
        "executable_signature": exec_sig,
        "request_trace": request_trace,
        "objective_audit": objective_audit,
        "run_reference": run_reference,
    }


def run_forced_sensitivity_experiment(
    *,
    query: str,
    mode: str,
    workspace: Path,
    settings: Settings,
    action_ids: list[str] | None = None,
    executor: ForcedExecutorFn | None = None,
) -> dict[str, Any]:
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    actions = _normalize_action_ids(action_ids)
    exp_id = _experiment_id(query, mode, actions)
    exp_dir = workspace / "experiments" / "sensitivity" / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    previous_row: dict[str, Any] | None = None
    for idx, action_id in enumerate(actions):
        action = get_action(action_id)
        compiled = compile_action(action)
        compiled_dict = enforce_compiled_action_semantics(compiled.to_dict())
        row = _execute_row(
            iteration_index=idx,
            query=query,
            mode=mode,
            workspace=workspace,
            settings=settings,
            compiled_dict=compiled_dict,
            executor=executor,
        )
        row["sensitivity_trace_matrix"] = build_sensitivity_trace_matrix(previous_row, row)
        rows.append(row)
        previous_row = row
    raw = {
        "schema_version": "forced_sensitivity.run.v1",
        "experiment_id": exp_id,
        "mode": mode,
        "query": query,
        "action_ids": actions,
        "rows": rows,
    }
    raw_path = exp_dir / "forced_sensitivity_results.json"
    raw_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = _build_report(raw)
    report_path = exp_dir / "forced_sensitivity_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"experiment_id": exp_id, "results_path": str(raw_path), "report_path": str(report_path)}


def regenerate_forced_sensitivity_report(results_path: Path) -> dict[str, Any]:
    raw = json.loads(results_path.read_text(encoding="utf-8"))
    return _build_report(raw if isinstance(raw, dict) else {})


def _dimension_variant_value(
    *,
    dimension: str,
    baseline_compiled: dict[str, Any],
    variant_values: dict[str, Any] | None,
) -> Any:
    if isinstance(variant_values, dict) and dimension in variant_values:
        return variant_values[dimension]
    override_key = DIMENSION_KEY_MAP[dimension]
    guided = baseline_compiled.get("guided_overrides", {})
    baseline_value = guided.get(override_key) if isinstance(guided, dict) else None
    candidates: list[Any] = []
    for action_id in sorted(DEFAULT_FORCED_ACTIONS):
        action = get_action(action_id)
        compiled = compile_action(action).to_dict()
        value = compiled.get("guided_overrides", {}).get(override_key)
        if value is None or value == baseline_value:
            continue
        if value not in candidates:
            candidates.append(value)
    return candidates[0] if candidates else None


def _build_key_ablation_report(raw: dict[str, Any]) -> dict[str, Any]:
    baseline_raw = raw.get("baseline", {})
    baseline = _hydrate_row_from_artifacts(baseline_raw if isinstance(baseline_raw, dict) else {})
    comparisons_raw = list(raw.get("comparisons", []))
    comparisons: list[dict[str, Any]] = []
    for row in comparisons_raw:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        variant_raw = item.get("variant_row", {})
        variant = _hydrate_row_from_artifacts(variant_raw if isinstance(variant_raw, dict) else {})
        item["variant_row"] = variant
        diff_summary = build_request_objective_diff_summary(baseline, variant) if variant else dict(item.get("diff_summary", {}))
        item["diff_summary"] = diff_summary
        item["classification"] = classify_override_key_effect(diff_summary)
        item["propagation_classification"] = classify_override_propagation(
            diff_summary,
            override_key=str(item.get("override_key")) if item.get("override_key") is not None else None,
        )
        comparisons.append(item)
    by_class: dict[str, int] = {}
    by_propagation: dict[str, int] = {}
    for row in comparisons:
        cls = row.get("classification")
        if not isinstance(cls, str):
            cls = "unclear"
        by_class[cls] = by_class.get(cls, 0) + 1
        prop = row.get("propagation_classification")
        if not isinstance(prop, str):
            prop = "unclear"
        by_propagation[prop] = by_propagation.get(prop, 0) + 1
    return {
        "schema_version": "key_ablation.report.v1",
        "experiment_id": raw.get("experiment_id"),
        "mode": raw.get("mode"),
        "query": raw.get("query"),
        "base_action_id": raw.get("base_action_id"),
        "baseline": baseline,
        "comparisons": comparisons,
        "diagnostics": {
            "comparison_count": len(comparisons),
            "classification_counts": by_class,
            "propagation_classification_counts": by_propagation,
            "dimension_role_classification": classify_dimension_roles(comparisons),
            "action_library_relevance_summary": summarize_action_library_relevance(comparisons),
            "override_key_propagation_summary": summarize_override_propagation(comparisons),
        },
    }


def run_per_key_ablation_experiment(
    *,
    query: str,
    mode: str,
    workspace: Path,
    settings: Settings,
    base_action_id: str = "baseline_control",
    dimensions: list[str] | None = None,
    variant_values: dict[str, Any] | None = None,
    executor: ForcedExecutorFn | None = None,
) -> dict[str, Any]:
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    dims = _normalize_dimensions(dimensions)
    exp_id = _key_ablation_experiment_id(query, mode, base_action_id, dims, variant_values)
    exp_dir = workspace / "experiments" / "key_ablation" / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)

    base_action = get_action(base_action_id)
    baseline_compiled = compile_action(base_action).to_dict()
    baseline_compiled = enforce_compiled_action_semantics(baseline_compiled)
    baseline_row = _execute_row(
        iteration_index=0,
        query=query,
        mode=mode,
        workspace=workspace,
        settings=settings,
        compiled_dict=baseline_compiled,
        executor=executor,
    )

    comparisons: list[dict[str, Any]] = []
    for idx, dim in enumerate(dims, start=1):
        override_key = DIMENSION_KEY_MAP[dim]
        variant_value = _dimension_variant_value(
            dimension=dim,
            baseline_compiled=baseline_compiled,
            variant_values=variant_values,
        )
        if variant_value is None:
            comparisons.append(
                {
                    "dimension": dim,
                    "override_key": override_key,
                    "baseline_value": baseline_compiled.get("guided_overrides", {}).get(override_key),
                    "variant_value": None,
                    "classification": "unclear",
                    "propagation_classification": "unclear",
                    "dimension_role": classify_dimension_roles(
                        [{"dimension": dim, "propagation_classification": "unclear"}]
                    ).get(dim),
                    "diff_summary": {},
                    "reason": "no_registered_alternative_value",
                }
            )
            continue
        variant_compiled = json.loads(json.dumps(baseline_compiled))
        guided = variant_compiled.get("guided_overrides", {})
        if not isinstance(guided, dict):
            guided = {}
            variant_compiled["guided_overrides"] = guided
        guided[override_key] = variant_value
        variant_compiled = enforce_compiled_action_semantics(variant_compiled)
        variant_row = _execute_row(
            iteration_index=idx,
            query=query,
            mode=mode,
            workspace=workspace,
            settings=settings,
            compiled_dict=variant_compiled,
            executor=executor,
        )
        diff_summary = build_request_objective_diff_summary(baseline_row, variant_row)
        classification = classify_override_key_effect(diff_summary)
        propagation_classification = classify_override_propagation(
            diff_summary,
            override_key=override_key,
        )
        comparisons.append(
            {
                "dimension": dim,
                "override_key": override_key,
                "baseline_value": baseline_compiled.get("guided_overrides", {}).get(override_key),
                "variant_value": variant_value,
                "variant_row": variant_row,
                "diff_summary": diff_summary,
                "classification": classification,
                "propagation_classification": propagation_classification,
                "dimension_role": classify_dimension_roles(
                    [{"dimension": dim, "propagation_classification": propagation_classification}]
                ).get(dim),
            }
        )

    raw = {
        "schema_version": "key_ablation.run.v1",
        "experiment_id": exp_id,
        "mode": mode,
        "query": query,
        "base_action_id": base_action_id,
        "dimensions": dims,
        "baseline": baseline_row,
        "comparisons": comparisons,
    }
    results_path = exp_dir / "key_ablation_results.json"
    results_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = _build_key_ablation_report(raw)
    report_path = exp_dir / "key_ablation_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "experiment_id": exp_id,
        "results_path": str(results_path),
        "report_path": str(report_path),
    }


def regenerate_per_key_ablation_report(results_path: Path) -> dict[str, Any]:
    raw = json.loads(results_path.read_text(encoding="utf-8"))
    return _build_key_ablation_report(raw if isinstance(raw, dict) else {})
