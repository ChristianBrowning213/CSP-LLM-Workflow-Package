from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.bench.cases import load_case_set, validate_case
from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.action_compile import compile_action, enforce_compiled_action_semantics
from sok_llm_orchestrator.optimization.action_registry import get_action
from sok_llm_orchestrator.optimization.backend_sensitivity import (
    objective_audit_from_run_dir,
    request_trace_from_run_dir,
)
from sok_llm_orchestrator.orchestrator.paired_run import run_paired_baseline_guided

_SWEEP_METRIC_VIEWS = {"property_aware", "decomposition_aware", "total_objective"}


def default_structural_variants() -> list[str]:
    return ["baseline_control", "guided_hybrid_balanced", "guided_property_push"]


def _safe_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _metric_view(metric_view: str) -> str:
    value = str(metric_view or "property_aware").strip().lower()
    if value not in _SWEEP_METRIC_VIEWS:
        raise ValueError(f"Unsupported guided-sweep metric view: {metric_view}")
    return value


def _sweep_id(
    *,
    case_file: Path,
    mode: str,
    repeats: int,
    variant_action_ids: list[str],
    metric_view: str,
) -> str:
    payload = {
        "case_file": str(case_file.resolve()),
        "mode": mode,
        "repeats": int(repeats),
        "variant_action_ids": list(variant_action_ids),
        "metric_view": metric_view,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"guided-sweep-{digest}"


def _query_for_case(case: dict[str, Any]) -> str:
    query = f"{case['composition']} guided variant sweep case {case['case_id']}"
    if isinstance(case.get("property_bias"), str) and case["property_bias"]:
        query = f"{query}; prioritize high {case['property_bias']}"
    else:
        query = f"{query}; prioritize high property x"
    if isinstance(case.get("symmetry_preference"), str) and case["symmetry_preference"]:
        query = f"{query}; symmetry {case['symmetry_preference']} soft"
    return query


def _mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return 0.0 if values else None
    return float(statistics.pstdev(values))


def _variant_sort_key(summary: dict[str, Any], *, metric_view: str) -> tuple[Any, ...]:
    mean_property = _safe_float(summary.get("mean_property_x")) or float("-inf")
    mean_objective = _safe_float(summary.get("mean_objective_total")) or float("-inf")
    abs_spp = _safe_float(summary.get("mean_abs_spp_term")) or float("-inf")
    prop_gain_rate = _safe_float(summary.get("property_gain_vs_baseline_rate")) or 0.0
    term_change_rate = _safe_float(summary.get("term_signature_changed_vs_baseline_rate")) or 0.0
    spp_presence = _safe_float(summary.get("spp_presence_rate")) or 0.0
    stability_penalty = _safe_float(summary.get("property_x_stdev")) or 0.0
    if metric_view == "total_objective":
        return (mean_objective, mean_property, -stability_penalty, str(summary.get("action_id", "")))
    if metric_view == "decomposition_aware":
        return (
            term_change_rate,
            spp_presence,
            abs_spp,
            mean_property,
            -stability_penalty,
            str(summary.get("action_id", "")),
        )
    return (
        mean_property,
        prop_gain_rate,
        term_change_rate,
        mean_objective,
        -stability_penalty,
        str(summary.get("action_id", "")),
    )


def classify_structural_variant(
    summary: dict[str, Any],
    *,
    baseline_summary: dict[str, Any] | None,
) -> str:
    if bool(summary.get("unstable", False)):
        return "unstable_variant"
    prop_gain_rate = _safe_float(summary.get("property_gain_vs_baseline_rate")) or 0.0
    term_change_rate = _safe_float(summary.get("term_signature_changed_vs_baseline_rate")) or 0.0
    guidance_rate = _safe_float(summary.get("guidance_activation_rate")) or 0.0
    mean_property = _safe_float(summary.get("mean_property_x"))
    mean_obj = _safe_float(summary.get("mean_objective_total"))
    if prop_gain_rate >= 0.6 and guidance_rate > 0.0:
        return "likely_productive"
    if term_change_rate > 0.0 and prop_gain_rate <= 0.0:
        return "term_movement_without_property_gain"
    if baseline_summary:
        base_property = _safe_float(baseline_summary.get("mean_property_x"))
        base_obj = _safe_float(baseline_summary.get("mean_objective_total"))
        if (
            mean_property is not None
            and base_property is not None
            and math.isclose(mean_property, base_property, abs_tol=1e-12)
            and mean_obj is not None
            and base_obj is not None
            and math.isclose(mean_obj, base_obj, abs_tol=1e-12)
        ):
            return "baseline_equivalent"
    return "structurally_real_but_no_gain"


def rank_guided_variants(
    per_variant_table: list[dict[str, Any]],
    *,
    metric_view: str = "property_aware",
) -> list[dict[str, Any]]:
    view = _metric_view(metric_view)
    ranked = sorted(
        [dict(item) for item in per_variant_table],
        key=lambda item: _variant_sort_key(item, metric_view=view),
        reverse=True,
    )
    for idx, item in enumerate(ranked, start=1):
        item["rank"] = idx
    return ranked


def _recommend_structural_allowlist(ranked: list[dict[str, Any]], *, max_variants: int = 2) -> list[str]:
    likely = [str(item["action_id"]) for item in ranked if str(item.get("classification")) == "likely_productive"]
    if likely:
        return likely[: max(1, int(max_variants))]
    fallbacks = [
        str(item["action_id"])
        for item in ranked
        if str(item.get("classification")) not in {"unstable_variant", "baseline_equivalent"}
    ]
    if fallbacks:
        return fallbacks[: max(1, int(max_variants))]
    return [str(ranked[0]["action_id"])] if ranked else []


def build_guided_variant_sweep_report(raw: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in raw.get("rows", []) if isinstance(row, dict)]
    baseline_rows = {
        (str(row.get("case_id")), int(row.get("repeat_index", 0))): row
        for row in rows
        if str(row.get("action_id")) == "baseline_control"
    }
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        action_id = str(row.get("action_id"))
        by_variant.setdefault(action_id, []).append(row)

    per_variant_table: list[dict[str, Any]] = []
    for action_id in sorted(by_variant):
        items = by_variant[action_id]
        prop_values = [float(v) for v in (_safe_float(row.get("property_x")) for row in items) if v is not None]
        obj_values = [float(v) for v in (_safe_float(row.get("objective_total")) for row in items) if v is not None]
        spp_values = [float(v) for v in (_safe_float(row.get("spp_term")) for row in items) if v is not None]
        guidance_rate = sum(1 for row in items if bool(row.get("guidance_active", False))) / max(1, len(items))
        spp_presence_rate = sum(1 for row in items if _safe_float(row.get("spp_term")) is not None) / max(1, len(items))
        signatures = {
            str(row.get("objective_terms_signature"))
            for row in items
            if isinstance(row.get("objective_terms_signature"), str)
        }
        prop_gain_flags: list[bool] = []
        obj_gain_flags: list[bool] = []
        term_change_flags: list[bool] = []
        for row in items:
            key = (str(row.get("case_id")), int(row.get("repeat_index", 0)))
            base = baseline_rows.get(key)
            if not base:
                continue
            prop = _safe_float(row.get("property_x"))
            base_prop = _safe_float(base.get("property_x"))
            if prop is not None and base_prop is not None:
                prop_gain_flags.append(prop > base_prop + 1e-12)
            obj = _safe_float(row.get("objective_total"))
            base_obj = _safe_float(base.get("objective_total"))
            if obj is not None and base_obj is not None:
                obj_gain_flags.append(obj > base_obj + 1e-12)
            term_change_flags.append(
                str(row.get("objective_terms_signature")) != str(base.get("objective_terms_signature"))
            )
        summary = {
            "action_id": action_id,
            "action_family": str(items[0].get("action_family")) if items else None,
            "row_count": len(items),
            "guidance_activation_rate": guidance_rate,
            "spp_presence_rate": spp_presence_rate,
            "mean_property_x": _mean(prop_values),
            "property_x_stdev": _stddev(prop_values),
            "mean_objective_total": _mean(obj_values),
            "objective_total_stdev": _stddev(obj_values),
            "mean_spp_term": _mean(spp_values),
            "mean_abs_spp_term": _mean([abs(v) for v in spp_values]) if spp_values else None,
            "objective_term_signature_count": len(signatures),
            "property_gain_vs_baseline_rate": (sum(1 for flag in prop_gain_flags if flag) / len(prop_gain_flags))
            if prop_gain_flags
            else 0.0,
            "objective_gain_vs_baseline_rate": (sum(1 for flag in obj_gain_flags if flag) / len(obj_gain_flags))
            if obj_gain_flags
            else 0.0,
            "term_signature_changed_vs_baseline_rate": (
                sum(1 for flag in term_change_flags if flag) / len(term_change_flags)
            )
            if term_change_flags
            else 0.0,
        }
        summary["unstable"] = bool((_safe_float(summary["property_x_stdev"]) or 0.0) > 0.08)
        per_variant_table.append(summary)

    baseline_summary = next(
        (item for item in per_variant_table if str(item.get("action_id")) == "baseline_control"),
        None,
    )
    for item in per_variant_table:
        item["classification"] = classify_structural_variant(item, baseline_summary=baseline_summary)

    view = _metric_view(str(raw.get("metric_view", "property_aware")))
    ranked = rank_guided_variants(per_variant_table, metric_view=view)
    for ranked_item in ranked:
        aid = str(ranked_item.get("action_id"))
        for original in per_variant_table:
            if str(original.get("action_id")) == aid:
                original["rank"] = ranked_item["rank"]

    classifications: dict[str, int] = {}
    for item in per_variant_table:
        cls = str(item.get("classification", "structurally_real_but_no_gain"))
        classifications[cls] = classifications.get(cls, 0) + 1

    recommendations = {
        "recommended_structural_allowlist": _recommend_structural_allowlist(ranked),
        "deprioritized_variants": [
            str(item.get("action_id"))
            for item in ranked
            if str(item.get("classification")) in {"structurally_real_but_no_gain", "unstable_variant", "baseline_equivalent"}
        ],
    }
    return {
        "schema_version": "guided_variant_sweep.report.v1",
        "sweep_id": raw.get("sweep_id"),
        "mode": raw.get("mode"),
        "case_file": raw.get("case_file"),
        "repeats": raw.get("repeats"),
        "metric_view": view,
        "variant_action_ids": list(raw.get("variant_action_ids", [])),
        "rows": rows,
        "per_variant_table": per_variant_table,
        "ranked_variants": ranked,
        "classification_counts": classifications,
        "recommendations": recommendations,
        "aggregate": {
            "total_rows": len(rows),
            "guidance_activation_rate": (
                sum(1 for row in rows if bool(row.get("guidance_active", False))) / max(1, len(rows))
            ),
            "spp_presence_rate": (
                sum(1 for row in rows if _safe_float(row.get("spp_term")) is not None) / max(1, len(rows))
            ),
            "property_gain_rate_vs_baseline": (
                _mean(
                    [
                        _safe_float(item.get("property_gain_vs_baseline_rate")) or 0.0
                        for item in per_variant_table
                        if str(item.get("action_id")) != "baseline_control"
                    ]
                )
                if per_variant_table
                else 0.0
            ),
            "best_variant_action_id": str(ranked[0].get("action_id")) if ranked else None,
            "best_variant_classification": str(ranked[0].get("classification")) if ranked else None,
        },
    }


def run_guided_variant_sweep(
    *,
    case_file: Path,
    mode: str,
    workspace: Path,
    settings: Settings,
    repeats: int = 2,
    variant_action_ids: list[str] | None = None,
    metric_view: str = "property_aware",
) -> dict[str, Any]:
    if int(repeats) < 1:
        raise ValueError("repeats must be >= 1")
    view = _metric_view(metric_view)
    variants = [str(item).strip() for item in (variant_action_ids or default_structural_variants()) if str(item).strip()]
    if not variants:
        raise ValueError("At least one variant action id is required.")
    for action_id in variants:
        get_action(action_id)

    cases = load_case_set(case_file)
    for case in cases:
        validate_case(case)

    sweep_id = _sweep_id(
        case_file=case_file,
        mode=mode,
        repeats=int(repeats),
        variant_action_ids=variants,
        metric_view=view,
    )
    sweep_dir = workspace / "experiments" / "guided_sweep" / sweep_id
    sweep_dir.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]

    rows: list[dict[str, Any]] = []
    for repeat_index in range(1, int(repeats) + 1):
        for case in cases:
            query = _query_for_case(case)
            for action_id in variants:
                action = get_action(action_id)
                compiled = enforce_compiled_action_semantics(compile_action(action).to_dict())
                suffix = str(compiled.get("query_suffix", "")).strip()
                query_with_hints = query if not suffix else f"{query} {suffix}".strip()
                paired = run_paired_baseline_guided(
                    query=query_with_hints,
                    mode=mode,
                    workspace=workspace,
                    settings=settings,
                    baseline_execution_overrides=compiled.get("baseline_overrides"),
                    guided_execution_overrides=compiled.get("guided_overrides"),
                    guided_with_spp=bool(compiled.get("guided_with_spp", True)),
                )
                paired_payload = json.loads(paired.report_path.read_text(encoding="utf-8"))
                objective_audit = objective_audit_from_run_dir(paired.guided.run_dir) or {}
                request_trace = request_trace_from_run_dir(paired.guided.run_dir)
                guidance_ids = (
                    list(request_trace.get("request_guidance_ids", []))
                    if isinstance(request_trace.get("request_guidance_ids"), list)
                    else []
                )
                row = {
                    "repeat_index": repeat_index,
                    "case_id": case["case_id"],
                    "case_class": case.get("case_class"),
                    "action_id": action_id,
                    "action_family": action.action_family,
                    "compiled_action": compiled,
                    "guided_with_spp": bool(compiled.get("guided_with_spp", False)),
                    "guided_overrides": dict(compiled.get("guided_overrides", {})),
                    "property_x": _safe_float(paired_payload.get("guided_property")),
                    "objective_total": _safe_float(objective_audit.get("objective_total")),
                    "spp_term": _safe_float(objective_audit.get("spp_term")),
                    "objective_terms_signature": objective_audit.get("objective_terms_signature"),
                    "request_guidance_ids": guidance_ids,
                    "guidance_active": bool(guidance_ids),
                    "request_structure_signature": request_trace.get("request_structure_signature"),
                    "request_trace": request_trace,
                    "paired_report_path": str(paired.report_path),
                    "guided_run_dir": str(paired.guided.run_dir),
                    "baseline_run_dir": str(paired.baseline.run_dir),
                }
                rows.append(row)

    raw = {
        "schema_version": "guided_variant_sweep.run.v1",
        "sweep_id": sweep_id,
        "mode": mode,
        "case_file": str(case_file.resolve()),
        "repeats": int(repeats),
        "metric_view": view,
        "variant_action_ids": variants,
        "rows": rows,
    }
    results_path = sweep_dir / "guided_variant_sweep_results.json"
    results_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = build_guided_variant_sweep_report(raw)
    report_path = sweep_dir / "guided_variant_sweep_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "sweep_id": sweep_id,
        "results_path": str(results_path),
        "report_path": str(report_path),
    }


def regenerate_guided_variant_sweep_report(results_path: Path) -> dict[str, Any]:
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    return build_guided_variant_sweep_report(payload if isinstance(payload, dict) else {})
