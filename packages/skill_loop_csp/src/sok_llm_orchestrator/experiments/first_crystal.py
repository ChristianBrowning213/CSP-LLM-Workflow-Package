from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.bench.cases import load_case_set, validate_case
from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.phase1_properties import (
    Phase1BenchmarkModeError,
    require_phase1_property_for_benchmark,
)
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.optimization.reporting import regenerate_report_from_session_artifacts

_METRIC_VIEWS = {"score", "property_x", "spp_term", "objective_total"}


def _experiment_id(
    *,
    case_file: Path,
    mode: str,
    max_iterations: int,
    reward_version: str,
    action_profile: str,
    run_tag: str | None = None,
    analysis_metric_view: str = "score",
    include_baseline_control: bool = False,
    selection_metric_view: str | None = None,
    strict_phase1_benchmark_mode: bool = False,
) -> str:
    raw = {
        "case_file": str(case_file.resolve()),
        "mode": mode,
        "max_iterations": int(max_iterations),
        "reward_version": reward_version,
        "action_profile": action_profile,
    }
    if isinstance(run_tag, str) and run_tag.strip():
        raw["run_tag"] = run_tag.strip()
    if analysis_metric_view != "score":
        raw["analysis_metric_view"] = analysis_metric_view
    raw["include_baseline_control"] = bool(include_baseline_control)
    raw["strict_phase1_benchmark_mode"] = bool(strict_phase1_benchmark_mode)
    if isinstance(selection_metric_view, str) and selection_metric_view.strip():
        raw["selection_metric_view"] = selection_metric_view.strip().lower()
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"first-crystal-{digest}"


def _repeated_experiment_id(
    *,
    case_file: Path,
    mode: str,
    repeats: int,
    max_iterations: int,
    reward_version: str,
    action_profile: str,
    analysis_metric_view: str,
    include_baseline_control: bool = False,
    selection_metric_view: str | None = None,
    strict_phase1_benchmark_mode: bool = False,
) -> str:
    raw = {
        "case_file": str(case_file.resolve()),
        "mode": mode,
        "repeats": int(repeats),
        "max_iterations": int(max_iterations),
        "reward_version": reward_version,
        "action_profile": action_profile,
        "analysis_metric_view": analysis_metric_view,
        "include_baseline_control": bool(include_baseline_control),
        "strict_phase1_benchmark_mode": bool(strict_phase1_benchmark_mode),
    }
    if isinstance(selection_metric_view, str) and selection_metric_view.strip():
        raw["selection_metric_view"] = selection_metric_view.strip().lower()
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"first-crystal-repeated-{digest}"


def default_first_crystal_case_pack() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "branch"
        / "benchmarks"
        / "first_crystal_cases.json"
    )


def _case_pack_metadata(case_file: Path) -> dict[str, Any]:
    try:
        payload = json.loads(case_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    meta: dict[str, Any] = {}
    if isinstance(payload.get("pack_id"), str):
        meta["pack_id"] = str(payload["pack_id"])
    if isinstance(payload.get("pack_intent"), str):
        meta["pack_intent"] = str(payload["pack_intent"])
    if isinstance(payload.get("recommended_protocol"), dict):
        meta["recommended_protocol"] = dict(payload["recommended_protocol"])
    if isinstance(payload.get("focused_case_ids"), list):
        meta["focused_case_ids"] = [str(item) for item in payload["focused_case_ids"] if isinstance(item, str)]
    return meta


def _query_for_case(case: dict[str, Any]) -> str:
    query = f"{case['composition']} first crystal experiment case {case['case_id']}"
    if isinstance(case.get("property_bias"), str) and case["property_bias"]:
        query = f"{query}; prioritize high {case['property_bias']}"
    if isinstance(case.get("symmetry_preference"), str) and case["symmetry_preference"]:
        query = f"{query}; symmetry {case['symmetry_preference']} soft"
    return query


def _validate_case_phase1_property(case: dict[str, Any], *, strict_phase1_benchmark_mode: bool) -> None:
    if not strict_phase1_benchmark_mode:
        return
    property_bias = case.get("property_bias")
    if not isinstance(property_bias, str) or not property_bias.strip():
        return
    try:
        require_phase1_property_for_benchmark(property_bias)
    except Phase1BenchmarkModeError as exc:
        raise ValueError(f"{case.get('case_id', '<unknown>')}: {exc.code}: {exc}") from exc


def _normalized_hypotheses(case: dict[str, Any]) -> list[dict[str, Any]]:
    value = case.get("hypotheses")
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        items.append(dict(item))
    return items


def _hypothesis_ids(hypotheses: list[dict[str, Any]]) -> list[str]:
    return [str(item["hypothesis_id"]) for item in hypotheses if isinstance(item.get("hypothesis_id"), str)]


def _safe_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _first_number(values: list[float | None]) -> float | None:
    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _best_number(values: list[float | None]) -> float | None:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return max(numeric) if numeric else None


def _metric_delta(initial: float | None, final: float | None) -> float | None:
    if initial is None or final is None:
        return None
    return float(final) - float(initial)


def _validate_metric_view(metric_view: str) -> str:
    value = str(metric_view or "score").strip().lower()
    if value not in _METRIC_VIEWS:
        raise ValueError(f"Unsupported analysis metric view: {metric_view}")
    return value


def classify_progress_signal(
    *,
    guidance_active: bool,
    objective_total_delta: float | None,
    property_delta: float | None,
    objective_term_signature_diversity_count: int | None,
) -> str:
    obj_delta = float(objective_total_delta) if isinstance(objective_total_delta, (int, float)) else None
    prop_delta = float(property_delta) if isinstance(property_delta, (int, float)) else None
    term_diversity = int(objective_term_signature_diversity_count or 0)
    if not guidance_active:
        return "no_structural_guidance_used"
    if obj_delta is not None and obj_delta > 1e-12:
        return "total_objective_improved"
    if obj_delta is not None and math.isclose(obj_delta, 0.0, abs_tol=1e-12):
        if prop_delta is not None and prop_delta > 1e-12:
            return "total_flat_property_gain"
        if term_diversity > 1:
            return "total_flat_objective_terms_changed"
        return "guidance_used_no_downstream_gain"
    if prop_delta is not None and prop_delta > 1e-12:
        return "property_improved_without_total_objective_gain"
    return "unclear"


def _analysis_metric_values(
    *,
    metric_view: str,
    score_trace: list[float | None],
    property_trace: list[float | None],
    spp_term_trace: list[float | None],
    objective_total_trace: list[float | None],
) -> list[float | None]:
    if metric_view == "score":
        return score_trace
    if metric_view == "property_x":
        return property_trace
    if metric_view == "spp_term":
        return spp_term_trace
    return objective_total_trace


def _multi_signal_from_report(report: dict[str, Any], *, analysis_metric_view: str) -> dict[str, Any]:
    objective_trace = report.get("objective_audit_trace", []) if isinstance(report, dict) else []
    iteration_trace = report.get("iteration_trace", []) if isinstance(report, dict) else []
    effectiveness_trace = report.get("iteration_effectiveness_trace", []) if isinstance(report, dict) else []
    score_trace_raw = report.get("reward_trace", []) if isinstance(report, dict) else []

    score_trace: list[float | None] = [_safe_float(item) for item in score_trace_raw] if isinstance(score_trace_raw, list) else []
    property_trace: list[float | None] = []
    if isinstance(iteration_trace, list):
        for item in iteration_trace:
            reward = item.get("reward", {}) if isinstance(item, dict) else {}
            if isinstance(reward, dict):
                property_trace.append(_safe_float(reward.get("property_estimate")))

    objective_total_trace: list[float | None] = []
    spp_term_trace: list[float | None] = []
    objective_term_signatures: set[str] = set()
    if isinstance(objective_trace, list):
        for audit in objective_trace:
            if not isinstance(audit, dict):
                continue
            objective_total_trace.append(_safe_float(audit.get("objective_total")))
            spp_term_trace.append(_safe_float(audit.get("spp_term")))
            sig = audit.get("objective_terms_signature")
            if isinstance(sig, str):
                objective_term_signatures.add(sig)

    guidance_ids: set[str] = set()
    guidance_iteration_count = 0
    if isinstance(effectiveness_trace, list):
        for entry in effectiveness_trace:
            if not isinstance(entry, dict):
                continue
            request_trace = entry.get("request_trace", {})
            if not isinstance(request_trace, dict):
                continue
            ids = request_trace.get("request_guidance_ids", [])
            row_ids: list[str] = []
            if isinstance(ids, list):
                row_ids = [str(item) for item in ids if isinstance(item, str)]
            if row_ids:
                guidance_iteration_count += 1
            guidance_ids.update(row_ids)
    guidance_active = "objective.energy_spp" in guidance_ids or bool(guidance_ids)

    metric_trace = _analysis_metric_values(
        metric_view=analysis_metric_view,
        score_trace=score_trace,
        property_trace=property_trace,
        spp_term_trace=spp_term_trace,
        objective_total_trace=objective_total_trace,
    )
    initial_metric = _first_number(metric_trace)
    final_metric = _best_number(metric_trace)
    metric_delta = _metric_delta(initial_metric, final_metric)

    initial_property = _first_number(property_trace)
    final_property = _best_number(property_trace)
    property_delta = _metric_delta(initial_property, final_property)
    initial_obj = _first_number(objective_total_trace)
    final_obj = _best_number(objective_total_trace)
    obj_delta = _metric_delta(initial_obj, final_obj)
    initial_spp = _first_number(spp_term_trace)
    final_spp = _best_number(spp_term_trace)
    spp_delta = _metric_delta(initial_spp, final_spp)
    spp_present_count = sum(1 for value in spp_term_trace if isinstance(value, (int, float)))

    return {
        "guidance_active": guidance_active,
        "guidance_iteration_count": guidance_iteration_count,
        "guidance_ids_used": sorted(guidance_ids),
        "spp_term_present_count": spp_present_count,
        "spp_term_values": [float(value) for value in spp_term_trace if isinstance(value, (int, float))],
        "initial_spp_term": initial_spp,
        "final_best_spp_term": final_spp,
        "spp_term_delta": spp_delta,
        "initial_property_x": initial_property,
        "final_best_property_x": final_property,
        "property_x_delta": property_delta,
        "property_x_improved": bool(isinstance(property_delta, (int, float)) and property_delta > 1e-12),
        "initial_objective_total": initial_obj,
        "final_best_objective_total": final_obj,
        "objective_total_delta": obj_delta,
        "objective_total_improved": bool(isinstance(obj_delta, (int, float)) and obj_delta > 1e-12),
        "objective_term_signature_count": len(objective_term_signatures),
        "analysis_metric_view": analysis_metric_view,
        "analysis_metric_initial": initial_metric,
        "analysis_metric_final_best": final_metric,
        "analysis_metric_delta": metric_delta,
        "analysis_metric_improved": bool(isinstance(metric_delta, (int, float)) and metric_delta > 1e-12),
    }


def _first_crystal_row_from_report(
    case: dict[str, Any],
    session_path: Path,
    report: dict[str, Any],
    *,
    analysis_metric_view: str,
) -> dict[str, Any]:
    diagnostics = report.get("diagnostics", {}) if isinstance(report, dict) else {}
    hypothesis_summary = (
        report.get("hypothesis_branch_summary", {})
        if isinstance(report, dict) and isinstance(report.get("hypothesis_branch_summary"), dict)
        else {}
    )
    structure_diag = (
        diagnostics.get("structure_diversity_summary", {})
        if isinstance(diagnostics, dict) and isinstance(diagnostics.get("structure_diversity_summary"), dict)
        else {}
    )
    regime_diag = (
        diagnostics.get("regime_level_summary", {})
        if isinstance(diagnostics, dict) and isinstance(diagnostics.get("regime_level_summary"), dict)
        else {}
    )
    spp_explore = report.get("spp_exploration_summary", {}) if isinstance(report, dict) else {}
    if not isinstance(spp_explore, dict):
        spp_explore = {}
    multi = _multi_signal_from_report(report, analysis_metric_view=analysis_metric_view)
    likely_reason = diagnostics.get("likely_flatness_reason") if isinstance(diagnostics, dict) else None
    sensitivity_classification = (
        diagnostics.get("backend_sensitivity_classification")
        if isinstance(diagnostics, dict)
        else None
    )
    recommendation = "review_iteration_trace"
    if likely_reason == "repeated_same_action":
        recommendation = "increase_exploration_or_adjust_action_limits"
    elif likely_reason == "different_actions_same_effective_config":
        recommendation = "inspect_action_compile_surface_for_effective_noops"
    elif likely_reason == "missing_config_signature_data":
        recommendation = "rerun_with_diagnostics_enabled_or_recompute_signatures_from_compiled_actions"
    elif likely_reason == "backend_objective_invariant_under_tested_actions":
        recommendation = "expand_action_space_or_adjust_objective_contract"
    elif likely_reason == "no_legal_diversity_explored":
        recommendation = "prioritize_non_baseline_families_next_run"
    if sensitivity_classification == "different_action_same_effective_request":
        recommendation = "inspect_request_path_trace_for_inert_overrides"
    elif sensitivity_classification == "different_action_different_config_same_objective":
        recommendation = "backend_coupling_weak_for_tested_action_dimensions"
    elif sensitivity_classification == "different_action_same_total_different_objective_terms":
        recommendation = "objective_terms_move_but_total_is_flat_check_weighting"
    progress_mode = classify_progress_signal(
        guidance_active=bool(multi.get("guidance_active", False)),
        objective_total_delta=_safe_float(multi.get("objective_total_delta")),
        property_delta=_safe_float(multi.get("property_x_delta")),
        objective_term_signature_diversity_count=(
            int(multi.get("objective_term_signature_count"))
            if isinstance(multi.get("objective_term_signature_count"), int)
            else None
        ),
    )
    hypotheses = _normalized_hypotheses(case)
    return {
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
        "hypotheses": hypotheses,
        "hypothesis_ids": _hypothesis_ids(hypotheses),
        "hypothesis_count": len(hypotheses),
        "session_id": report.get("session_id"),
        "session_path": str(session_path),
        "initial_score": report.get("initial_score"),
        "final_best_score": report.get("final_best_score"),
        "improvement_delta": report.get("improvement_delta"),
        "stop_reason": report.get("termination_reason"),
        "best_iteration_index": report.get("best_iteration_index"),
        "best_action_id": report.get("best_action_id"),
        "best_action_family": report.get("best_action_family"),
        "best_structure_artifact_path": report.get("best_structure_artifact_path"),
        "best_structure_linkage": report.get("best_structure_linkage"),
        "action_diversity_count": diagnostics.get("unique_action_id_count"),
        "family_diversity_count": diagnostics.get("unique_action_family_count"),
        "score_diversity_count": diagnostics.get("unique_score_value_count"),
        "compiled_config_diversity_count": diagnostics.get("unique_compiled_config_signature_count"),
        "executable_diversity_count": diagnostics.get("unique_executable_signature_count"),
        "best_remained_iteration_zero": diagnostics.get("best_remained_iteration_zero"),
        "first_improvement_iteration": diagnostics.get("first_improvement_iteration"),
        "flat_objective_flag": diagnostics.get("flat_objective_flag"),
        "likely_flatness_reason": likely_reason,
        "objective_total_diversity_count": diagnostics.get("unique_objective_total_value_count"),
        "objective_term_signature_diversity_count": diagnostics.get("unique_objective_term_signature_count"),
        "backend_sensitivity_classification": sensitivity_classification,
        "dimension_sensitivity_summary": diagnostics.get("dimension_sensitivity_summary"),
        "hypotheses_tried": list(hypothesis_summary.get("hypotheses_tried", []))
        if isinstance(hypothesis_summary.get("hypotheses_tried"), list)
        else [],
        "active_hypothesis_by_iteration": list(hypothesis_summary.get("active_hypothesis_by_iteration", []))
        if isinstance(hypothesis_summary.get("active_hypothesis_by_iteration"), list)
        else [],
        "branch_switch_count": int(hypothesis_summary.get("branch_switch_count", 0))
        if isinstance(hypothesis_summary.get("branch_switch_count"), int)
        else 0,
        "branch_switch_events": list(hypothesis_summary.get("branch_switch_events", []))
        if isinstance(hypothesis_summary.get("branch_switch_events"), list)
        else [],
        "best_hypothesis_id": hypothesis_summary.get("best_hypothesis_id"),
        "hypothesis_branch_summary": (
            list(hypothesis_summary.get("rows", []))
            if isinstance(hypothesis_summary.get("rows"), list)
            else []
        ),
        "diagnostic_recommendation": recommendation,
        "dominance_warning": structure_diag.get("dominance_warning"),
        "dominance_recommendation": structure_diag.get("dominance_recommendation"),
        "unique_structure_signature_count": structure_diag.get("unique_structure_signature_count"),
        "structure_change_rate": structure_diag.get("structure_change_rate"),
        "objective_changed_structure_unchanged_count": structure_diag.get("objective_changed_structure_unchanged_count"),
        "guidance_changed_structure_unchanged_count": structure_diag.get("guidance_changed_structure_unchanged_count"),
        "same_structure_despite_guidance_variation_rate": structure_diag.get("same_structure_despite_guidance_variation_rate"),
        "weighting_profiles_tried": list(regime_diag.get("unique_weighting_profiles", []))
        if isinstance(regime_diag.get("unique_weighting_profiles"), list)
        else [],
        "structure_perturbation_profiles_tried": list(regime_diag.get("unique_structure_perturbation_profiles", []))
        if isinstance(regime_diag.get("unique_structure_perturbation_profiles"), list)
        else [],
        "template_seed_profiles_tried": list(regime_diag.get("unique_template_seed_profiles", []))
        if isinstance(regime_diag.get("unique_template_seed_profiles"), list)
        else [],
        "lattice_candidate_profiles_tried": list(regime_diag.get("unique_lattice_candidate_profiles", []))
        if isinstance(regime_diag.get("unique_lattice_candidate_profiles"), list)
        else [],
        "symmetry_relaxation_profiles_tried": list(regime_diag.get("unique_symmetry_relaxation_profiles", []))
        if isinstance(regime_diag.get("unique_symmetry_relaxation_profiles"), list)
        else [],
        "ordering_perturbation_profiles_tried": list(regime_diag.get("unique_ordering_perturbation_profiles", []))
        if isinstance(regime_diag.get("unique_ordering_perturbation_profiles"), list)
        else [],
        "structure_change_rate_by_regime": (
            dict(regime_diag.get("structure_change_rate_by_regime", {}))
            if isinstance(regime_diag.get("structure_change_rate_by_regime"), dict)
            else {}
        ),
        "unique_structure_signature_count_by_regime": (
            dict(regime_diag.get("unique_structure_signature_count_by_regime", {}))
            if isinstance(regime_diag.get("unique_structure_signature_count_by_regime"), dict)
            else {}
        ),
        "property_gain_by_regime": (
            dict(regime_diag.get("property_gain_by_regime", {}))
            if isinstance(regime_diag.get("property_gain_by_regime"), dict)
            else {}
        ),
        "dominance_warning_by_regime": (
            dict(regime_diag.get("dominance_warning_by_regime", {}))
            if isinstance(regime_diag.get("dominance_warning_by_regime"), dict)
            else {}
        ),
        "recommended_structure_moving_regimes": (
            list(regime_diag.get("recommended_structure_moving_regimes", []))
            if isinstance(regime_diag.get("recommended_structure_moving_regimes"), list)
            else []
        ),
        "recommended_next_regime": regime_diag.get("recommended_next_regime"),
        "guidance_active": multi["guidance_active"],
        "guidance_iteration_count": multi["guidance_iteration_count"],
        "guidance_ids_used": list(multi["guidance_ids_used"]),
        "spp_term_present_count": multi["spp_term_present_count"],
        "spp_term_values": list(multi["spp_term_values"]),
        "initial_spp_term": multi["initial_spp_term"],
        "final_best_spp_term": multi["final_best_spp_term"],
        "spp_term_delta": multi["spp_term_delta"],
        "initial_property_x": multi["initial_property_x"],
        "final_best_property_x": multi["final_best_property_x"],
        "property_x_delta": multi["property_x_delta"],
        "property_x_improved": multi["property_x_improved"],
        "initial_objective_total": multi["initial_objective_total"],
        "final_best_objective_total": multi["final_best_objective_total"],
        "objective_total_delta": multi["objective_total_delta"],
        "objective_total_improved": multi["objective_total_improved"],
        "analysis_metric_view": multi["analysis_metric_view"],
        "analysis_metric_initial": multi["analysis_metric_initial"],
        "analysis_metric_final_best": multi["analysis_metric_final_best"],
        "analysis_metric_delta": multi["analysis_metric_delta"],
        "analysis_metric_improved": multi["analysis_metric_improved"],
        "progress_signal_mode": progress_mode,
        "total_flat_property_gain": progress_mode == "total_flat_property_gain",
        "selection_metric_view": report.get("selection_metric_view"),
        "spp_unique_corpus_strategy_count": spp_explore.get("unique_corpus_strategy_count"),
        "spp_unique_selected_corpus_candidate_count": spp_explore.get("unique_selected_corpus_candidate_count"),
        "spp_unique_package_variant_count": spp_explore.get("unique_spp_package_variant_count"),
        "spp_unique_payload_signature_count": spp_explore.get("unique_spp_payload_signature_count"),
        "spp_branch_count": spp_explore.get("branch_count"),
        "spp_richer_exploration_detected": spp_explore.get("richer_exploration_detected"),
    }


def build_first_crystal_summary(
    *,
    experiment_id: str,
    case_file: Path,
    rows: list[dict[str, Any]],
    reward_version: str,
    action_profile: str,
    analysis_metric_view: str,
    case_pack_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    deltas = [float(row["improvement_delta"]) for row in rows if isinstance(row.get("improvement_delta"), (int, float))]
    metric_deltas = [float(row["analysis_metric_delta"]) for row in rows if isinstance(row.get("analysis_metric_delta"), (int, float))]
    with_structure = sum(1 for row in rows if isinstance(row.get("best_structure_artifact_path"), str))
    flat_cases = sum(1 for row in rows if bool(row.get("flat_objective_flag", False)))
    iteration_zero_best_cases = sum(1 for row in rows if bool(row.get("best_remained_iteration_zero", False)))
    guidance_active_cases = sum(1 for row in rows if bool(row.get("guidance_active", False)))
    spp_present_cases = sum(1 for row in rows if int(row.get("spp_term_present_count", 0) or 0) > 0)
    property_improved_cases = sum(1 for row in rows if bool(row.get("property_x_improved", False)))
    objective_improved_cases = sum(1 for row in rows if bool(row.get("objective_total_improved", False)))
    metric_improved_cases = sum(1 for row in rows if bool(row.get("analysis_metric_improved", False)))
    total_flat_property_gain_cases = sum(1 for row in rows if bool(row.get("total_flat_property_gain", False)))
    spp_richer_cases = sum(1 for row in rows if bool(row.get("spp_richer_exploration_detected", False)))
    dominance_warning_cases = sum(1 for row in rows if bool(row.get("dominance_warning", False)))
    structure_changed_cases = sum(
        1 for row in rows if isinstance(row.get("structure_change_rate"), (int, float)) and float(row.get("structure_change_rate")) > 0.0
    )
    hypothesis_switch_cases = sum(1 for row in rows if int(row.get("branch_switch_count", 0) or 0) > 0)
    hypothesis_coverage: set[str] = set()
    for row in rows:
        tried = row.get("hypotheses_tried")
        if isinstance(tried, list):
            for item in tried:
                if isinstance(item, str) and item:
                    hypothesis_coverage.add(item)
    multi_weighting_cases = sum(
        1
        for row in rows
        if isinstance(row.get("weighting_profiles_tried"), list) and len(row.get("weighting_profiles_tried")) > 1
    )
    multi_perturb_cases = sum(
        1
        for row in rows
        if isinstance(row.get("structure_perturbation_profiles_tried"), list)
        and len(row.get("structure_perturbation_profiles_tried")) > 1
    )
    multi_seed_cases = sum(
        1
        for row in rows
        if isinstance(row.get("template_seed_profiles_tried"), list) and len(row.get("template_seed_profiles_tried")) > 1
    )
    multi_lattice_cases = sum(
        1
        for row in rows
        if isinstance(row.get("lattice_candidate_profiles_tried"), list)
        and len(row.get("lattice_candidate_profiles_tried")) > 1
    )
    multi_symmetry_cases = sum(
        1
        for row in rows
        if isinstance(row.get("symmetry_relaxation_profiles_tried"), list)
        and len(row.get("symmetry_relaxation_profiles_tried")) > 1
    )
    multi_ordering_cases = sum(
        1
        for row in rows
        if isinstance(row.get("ordering_perturbation_profiles_tried"), list)
        and len(row.get("ordering_perturbation_profiles_tried")) > 1
    )
    rows_count = max(1, len(rows))
    return {
        "schema_version": "first_crystal.summary.v1",
        "experiment_id": experiment_id,
        "case_file": str(case_file.resolve()),
        "reward_version": reward_version,
        "action_profile": action_profile,
        "analysis_metric_view": analysis_metric_view,
        "case_pack_metadata": dict(case_pack_metadata or {}),
        "rows": rows,
        "aggregate": {
            "total_cases": len(rows),
            "mean_improvement_delta": (sum(deltas) / len(deltas)) if deltas else 0.0,
            "mean_analysis_metric_delta": (sum(metric_deltas) / len(metric_deltas)) if metric_deltas else 0.0,
            "structure_linked_cases": with_structure,
            "flat_cases": flat_cases,
            "iteration_zero_best_cases": iteration_zero_best_cases,
            "guidance_active_cases": guidance_active_cases,
            "guidance_activation_rate": guidance_active_cases / rows_count,
            "spp_term_present_cases": spp_present_cases,
            "spp_term_presence_rate": spp_present_cases / rows_count,
            "property_improved_cases": property_improved_cases,
            "property_improved_case_rate": property_improved_cases / rows_count,
            "total_objective_improved_cases": objective_improved_cases,
            "total_objective_improved_case_rate": objective_improved_cases / rows_count,
            "analysis_metric_improved_cases": metric_improved_cases,
            "analysis_metric_improved_case_rate": metric_improved_cases / rows_count,
            "total_flat_property_gain_cases": total_flat_property_gain_cases,
            "total_flat_property_gain_rate": total_flat_property_gain_cases / rows_count,
            "spp_richer_exploration_cases": spp_richer_cases,
            "spp_richer_exploration_rate": spp_richer_cases / rows_count,
            "dominance_warning_cases": dominance_warning_cases,
            "dominance_warning_rate": dominance_warning_cases / rows_count,
            "structure_changed_cases": structure_changed_cases,
            "structure_changed_case_rate": structure_changed_cases / rows_count,
            "hypothesis_switch_cases": hypothesis_switch_cases,
            "hypothesis_switch_case_rate": hypothesis_switch_cases / rows_count,
            "unique_hypotheses_tried_count": len(hypothesis_coverage),
            "unique_hypotheses_tried": sorted(hypothesis_coverage),
            "multi_weighting_profile_cases": multi_weighting_cases,
            "multi_weighting_profile_case_rate": multi_weighting_cases / rows_count,
            "multi_perturbation_profile_cases": multi_perturb_cases,
            "multi_perturbation_profile_case_rate": multi_perturb_cases / rows_count,
            "multi_template_seed_profile_cases": multi_seed_cases,
            "multi_template_seed_profile_case_rate": multi_seed_cases / rows_count,
            "multi_lattice_candidate_profile_cases": multi_lattice_cases,
            "multi_lattice_candidate_profile_case_rate": multi_lattice_cases / rows_count,
            "multi_symmetry_relaxation_profile_cases": multi_symmetry_cases,
            "multi_symmetry_relaxation_profile_case_rate": multi_symmetry_cases / rows_count,
            "multi_ordering_perturbation_profile_cases": multi_ordering_cases,
            "multi_ordering_perturbation_profile_case_rate": multi_ordering_cases / rows_count,
        },
    }


def _apply_action_profile(
    settings: Settings,
    *,
    mode: str,
    action_profile: str,
    include_baseline_control: bool,
) -> dict[str, object]:
    profile = {"name": action_profile}
    if action_profile == "live_assisted" and mode == "live":
        settings.optimization_exploration_rate = max(float(settings.optimization_exploration_rate), 0.35)
        settings.optimization_stagnation_window = max(int(settings.optimization_stagnation_window), 4)
        settings.optimization_allow_midloop_clarification = True
        profile.update(
            {
                "exploration_rate": settings.optimization_exploration_rate,
                "stagnation_window": settings.optimization_stagnation_window,
                "allow_midloop_clarification": settings.optimization_allow_midloop_clarification,
            }
        )
    if action_profile == "live_structural":
        settings.optimization_exploration_rate = max(float(settings.optimization_exploration_rate), 0.2)
        settings.optimization_stagnation_window = max(int(settings.optimization_stagnation_window), 4)
        settings.optimization_allow_midloop_clarification = mode != "live"
        settings.optimization_selection_metric_view = "property_aware"
        max_iters = max(1, int(settings.optimization_max_iterations))
        if not settings.optimization_action_allowlist:
            settings.optimization_action_allowlist = [
                "guided_property_push",
                "guided_hybrid_balanced",
            ]
        if include_baseline_control and "baseline_control" not in settings.optimization_action_allowlist:
            settings.optimization_action_allowlist = list(settings.optimization_action_allowlist) + ["baseline_control"]
        settings.optimization_action_family_limits = {
            "baseline_control": 1 if include_baseline_control else 0,
            "guided_exploit": max_iters,
            "guided_explore": max(1, int(max_iters / 2)),
            "retrieval_explore": 0,
            "cell_policy": 0,
        }
        profile.update(
            {
                "exploration_rate": settings.optimization_exploration_rate,
                "stagnation_window": settings.optimization_stagnation_window,
                "allow_midloop_clarification": settings.optimization_allow_midloop_clarification,
                "action_family_limits": dict(settings.optimization_action_family_limits),
                "action_allowlist": list(settings.optimization_action_allowlist),
                "prioritized_structural_dimensions": ["qlip_guidance"],
                "selection_metric_view": settings.optimization_selection_metric_view,
                "include_baseline_control": bool(include_baseline_control),
            }
        )
    if action_profile == "spp_deep_explore":
        settings.optimization_exploration_rate = max(float(settings.optimization_exploration_rate), 0.35)
        settings.optimization_stagnation_window = max(int(settings.optimization_stagnation_window), 4)
        settings.optimization_allow_midloop_clarification = mode != "live"
        settings.optimization_selection_metric_view = "property_decomp_aware"
        max_iters = max(2, int(settings.optimization_max_iterations))
        if not settings.optimization_action_allowlist:
            settings.optimization_action_allowlist = [
                "guided_property_push",
                "guided_hybrid_balanced",
                "guided_corpus_branch",
                "guided_payload_probe",
                "guided_extreme_structure_probe",
            ]
        if include_baseline_control and "baseline_control" not in settings.optimization_action_allowlist:
            settings.optimization_action_allowlist = list(settings.optimization_action_allowlist) + ["baseline_control"]
        settings.optimization_action_family_limits = {
            "baseline_control": 1 if include_baseline_control else 0,
            "guided_exploit": max_iters,
            "guided_explore": max_iters,
            "retrieval_explore": max(1, int(max_iters / 2)),
            "cell_policy": 0,
        }
        profile.update(
            {
                "exploration_rate": settings.optimization_exploration_rate,
                "stagnation_window": settings.optimization_stagnation_window,
                "allow_midloop_clarification": settings.optimization_allow_midloop_clarification,
                "action_family_limits": dict(settings.optimization_action_family_limits),
                "action_allowlist": list(settings.optimization_action_allowlist),
                "prioritized_structural_dimensions": [
                    "qlip_guidance",
                    "spp_corpus_strategy",
                    "spp_payload_profile",
                    "weighting_profile",
                    "structure_perturbation_profile",
                    "template_seed_profile",
                    "lattice_candidate_profile",
                    "symmetry_relaxation_profile",
                    "ordering_perturbation_profile",
                ],
                "selection_metric_view": settings.optimization_selection_metric_view,
                "include_baseline_control": bool(include_baseline_control),
            }
        )
    if action_profile == "hard_structure_probe":
        settings.optimization_exploration_rate = max(float(settings.optimization_exploration_rate), 0.45)
        settings.optimization_stagnation_window = max(int(settings.optimization_stagnation_window), 3)
        settings.optimization_allow_midloop_clarification = mode != "live"
        settings.optimization_selection_metric_view = "property_decomp_aware"
        max_iters = max(2, int(settings.optimization_max_iterations))
        if not settings.optimization_action_allowlist:
            settings.optimization_action_allowlist = [
                "guided_extreme_structure_probe",
                "guided_property_push",
                "guided_corpus_branch",
                "guided_hybrid_balanced",
            ]
        if include_baseline_control and "baseline_control" not in settings.optimization_action_allowlist:
            settings.optimization_action_allowlist = list(settings.optimization_action_allowlist) + ["baseline_control"]
        settings.optimization_action_family_limits = {
            "baseline_control": 1 if include_baseline_control else 0,
            "guided_exploit": max_iters,
            "guided_explore": max_iters,
            "retrieval_explore": max(1, int(max_iters / 2)),
            "cell_policy": max(1, int(max_iters / 2)),
        }
        profile.update(
            {
                "exploration_rate": settings.optimization_exploration_rate,
                "stagnation_window": settings.optimization_stagnation_window,
                "allow_midloop_clarification": settings.optimization_allow_midloop_clarification,
                "action_family_limits": dict(settings.optimization_action_family_limits),
                "action_allowlist": list(settings.optimization_action_allowlist),
                "prioritized_structural_dimensions": [
                    "qlip_guidance",
                    "structure_perturbation_profile",
                    "template_seed_profile",
                    "lattice_candidate_profile",
                    "symmetry_relaxation_profile",
                    "ordering_perturbation_profile",
                ],
                "selection_metric_view": settings.optimization_selection_metric_view,
                "include_baseline_control": bool(include_baseline_control),
            }
        )
    if action_profile == "multi_hypothesis_branching":
        settings.optimization_exploration_rate = max(float(settings.optimization_exploration_rate), 0.4)
        settings.optimization_stagnation_window = max(int(settings.optimization_stagnation_window), 3)
        settings.optimization_allow_midloop_clarification = mode != "live"
        settings.optimization_selection_metric_view = "property_decomp_aware"
        max_iters = max(3, int(settings.optimization_max_iterations))
        if not settings.optimization_action_allowlist:
            settings.optimization_action_allowlist = [
                "guided_property_push",
                "guided_hybrid_balanced",
                "guided_corpus_branch",
                "guided_payload_probe",
                "guided_extreme_structure_probe",
                "retrieval_text_explore",
            ]
        if include_baseline_control and "baseline_control" not in settings.optimization_action_allowlist:
            settings.optimization_action_allowlist = list(settings.optimization_action_allowlist) + ["baseline_control"]
        settings.optimization_action_family_limits = {
            "baseline_control": 1 if include_baseline_control else 0,
            "guided_exploit": max_iters,
            "guided_explore": max_iters,
            "retrieval_explore": max(1, int(max_iters / 2)),
            "cell_policy": max(1, int(max_iters / 3)),
        }
        profile.update(
            {
                "exploration_rate": settings.optimization_exploration_rate,
                "stagnation_window": settings.optimization_stagnation_window,
                "allow_midloop_clarification": settings.optimization_allow_midloop_clarification,
                "action_family_limits": dict(settings.optimization_action_family_limits),
                "action_allowlist": list(settings.optimization_action_allowlist),
                "prioritized_structural_dimensions": [
                    "hypothesis_family",
                    "qlip_guidance",
                    "spp_corpus_strategy",
                    "spp_payload_profile",
                    "weighting_profile",
                    "structure_perturbation_profile",
                    "template_seed_profile",
                    "lattice_candidate_profile",
                    "symmetry_relaxation_profile",
                    "ordering_perturbation_profile",
                ],
                "selection_metric_view": settings.optimization_selection_metric_view,
                "include_baseline_control": bool(include_baseline_control),
            }
        )
    return profile


def run_first_crystal_experiment(
    *,
    case_file: Path,
    mode: str,
    workspace: Path,
    settings: Settings,
    max_iterations: int = 4,
    reward_version: str = "v1",
    action_profile: str = "default",
    analysis_metric_view: str = "score",
    run_tag: str | None = None,
    include_baseline_control: bool = False,
    clarification_answers: list[str] | None = None,
    executor_factory: Any = None,
    strict_phase1_benchmark_mode: bool = False,
) -> dict[str, Any]:
    metric_view = _validate_metric_view(analysis_metric_view)
    cases = load_case_set(case_file)
    pack_meta = _case_pack_metadata(case_file)
    for case in cases:
        validate_case(case)
        _validate_case_phase1_property(case, strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode))

    exp_id = _experiment_id(
        case_file=case_file,
        mode=mode,
        max_iterations=max_iterations,
        reward_version=reward_version,
        action_profile=action_profile,
        run_tag=run_tag,
        analysis_metric_view=metric_view,
        include_baseline_control=include_baseline_control,
        selection_metric_view=str(settings.optimization_selection_metric_view),
        strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
    )
    exp_dir = workspace / "experiments" / "first_crystal" / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    case_bindings: list[dict[str, Any]] = []
    for case in cases:
        case_settings = copy.deepcopy(settings)
        case_settings.optimization_max_iterations = int(max_iterations)
        case_settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
        case_settings.allowed_write_roots = [workspace.resolve()]
        profile_meta = _apply_action_profile(
            case_settings,
            mode=mode,
            action_profile=action_profile,
            include_baseline_control=include_baseline_control,
        )
        query = _query_for_case(case)
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
            seed_hint=f"first_crystal:{run_tag or 'default'}:{case['case_id']}",
            clarification_answers=clarification_answers,
            case_metadata=case,
            strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
        )
        report = regenerate_report_from_session_artifacts(start.session_path)
        row = _first_crystal_row_from_report(
            case,
            start.session_path,
            report,
            analysis_metric_view=metric_view,
        )
        row["profile"] = profile_meta
        row["clarification_answers"] = list(clarification_answers or [])
        row["run_tag"] = run_tag
        rows.append(row)
        case_bindings.append(
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
                "hypotheses": _normalized_hypotheses(case),
                "session_id": row["session_id"],
                "session_path": row["session_path"],
                "profile": profile_meta,
                "run_tag": run_tag,
            }
        )

    summary = build_first_crystal_summary(
        experiment_id=exp_id,
        case_file=case_file,
        rows=rows,
        reward_version=reward_version,
        action_profile=action_profile,
        analysis_metric_view=metric_view,
        case_pack_metadata=pack_meta,
    )
    summary_path = exp_dir / "first_crystal_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": "first_crystal.experiment.v1",
        "experiment_id": exp_id,
        "mode": mode,
        "case_file": str(case_file.resolve()),
        "max_iterations": int(max_iterations),
        "reward_version": reward_version,
        "action_profile": action_profile,
        "analysis_metric_view": metric_view,
        "run_tag": run_tag,
        "include_baseline_control": bool(include_baseline_control),
        "clarification_answers": list(clarification_answers or []),
        "strict_phase1_benchmark_mode": bool(strict_phase1_benchmark_mode),
        "case_pack_metadata": pack_meta,
        "summary_path": str(summary_path),
        "cases": case_bindings,
    }
    manifest_path = exp_dir / "experiment_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "experiment_id": exp_id,
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
    }


def regenerate_first_crystal_summary(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_file = Path(str(manifest["case_file"]))
    metric_view = _validate_metric_view(str(manifest.get("analysis_metric_view", "score")))
    pack_meta = (
        dict(manifest.get("case_pack_metadata", {}))
        if isinstance(manifest.get("case_pack_metadata"), dict)
        else _case_pack_metadata(case_file)
    )
    rows: list[dict[str, Any]] = []
    case_map = {str(case["case_id"]): case for case in load_case_set(case_file)}
    for item in manifest.get("cases", []):
        case_id = str(item["case_id"])
        report = regenerate_report_from_session_artifacts(Path(str(item["session_path"])))
        case = case_map.get(
            case_id,
            {
                "case_id": case_id,
                "case_class": item.get("case_class"),
                "challenge_class": item.get("challenge_class"),
                "guidance_rationale": item.get("guidance_rationale"),
                "recommended_guidance_focus": item.get("recommended_guidance_focus"),
                "suggested_structural_dimensions": item.get("suggested_structural_dimensions"),
                "suggested_corpus_bias": item.get("suggested_corpus_bias"),
                "suggested_perturbation_bias": item.get("suggested_perturbation_bias"),
                "hypotheses": item.get("hypotheses"),
            },
        )
        row = _first_crystal_row_from_report(
            case,
            Path(str(item["session_path"])),
            report,
            analysis_metric_view=metric_view,
        )
        row["profile"] = item.get("profile", {"name": manifest.get("action_profile", "default")})
        row["clarification_answers"] = list(manifest.get("clarification_answers", []))
        row["run_tag"] = manifest.get("run_tag")
        rows.append(row)
    return build_first_crystal_summary(
        experiment_id=str(manifest["experiment_id"]),
        case_file=case_file,
        rows=rows,
        reward_version=str(manifest.get("reward_version", "v1")),
        action_profile=str(manifest.get("action_profile", "default")),
        analysis_metric_view=metric_view,
        case_pack_metadata=pack_meta,
    )


def build_repeated_first_crystal_summary(
    *,
    repeated_experiment_id: str,
    case_file: Path,
    run_summaries: list[dict[str, Any]],
    reward_version: str,
    action_profile: str,
    analysis_metric_view: str,
) -> dict[str, Any]:
    metric_view = _validate_metric_view(analysis_metric_view)
    all_rows: list[dict[str, Any]] = []
    run_table: list[dict[str, Any]] = []
    per_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in run_summaries:
        idx = int(run.get("repeat_index", 0))
        summary = run.get("summary", {})
        rows = summary.get("rows", []) if isinstance(summary, dict) else []
        if not isinstance(rows, list):
            rows = []
        run_rows_count = 0
        run_guidance = 0
        run_property_improved = 0
        run_total_improved = 0
        run_metric_improved = 0
        run_metric_values: list[float] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            run_rows_count += 1
            if bool(row.get("guidance_active", False)):
                run_guidance += 1
            if bool(row.get("property_x_improved", False)):
                run_property_improved += 1
            if bool(row.get("objective_total_improved", False)):
                run_total_improved += 1
            if bool(row.get("analysis_metric_improved", False)):
                run_metric_improved += 1
            metric_final = _safe_float(row.get("analysis_metric_final_best"))
            if metric_final is not None:
                run_metric_values.append(metric_final)
            tagged = dict(row)
            tagged["repeat_index"] = idx
            tagged["run_manifest_path"] = run.get("manifest_path")
            tagged["run_summary_path"] = run.get("summary_path")
            all_rows.append(tagged)
            case_id = str(row.get("case_id"))
            per_case[case_id].append(tagged)
        run_table.append(
            {
                "repeat_index": idx,
                "run_manifest_path": run.get("manifest_path"),
                "run_summary_path": run.get("summary_path"),
                "rows": run_rows_count,
                "guidance_active_cases": run_guidance,
                "property_improved_cases": run_property_improved,
                "total_objective_improved_cases": run_total_improved,
                "analysis_metric_improved_cases": run_metric_improved,
                "mean_analysis_metric_final_best": (sum(run_metric_values) / len(run_metric_values))
                if run_metric_values
                else None,
            }
        )

    case_rows: list[dict[str, Any]] = []
    for case_id in sorted(per_case):
        rows = sorted(per_case[case_id], key=lambda item: int(item.get("repeat_index", 0)))
        first = rows[0] if rows else {}
        analysis_values = [_safe_float(row.get("analysis_metric_final_best")) for row in rows]
        analysis_numeric = [float(value) for value in analysis_values if isinstance(value, (int, float))]
        first_metric = analysis_numeric[0] if analysis_numeric else None
        last_metric = analysis_numeric[-1] if analysis_numeric else None
        case_rows.append(
            {
                "case_id": case_id,
                "case_class": first.get("case_class"),
                "run_count": len(rows),
                "guidance_active_count": sum(1 for row in rows if bool(row.get("guidance_active", False))),
                "spp_term_present_count": sum(1 for row in rows if int(row.get("spp_term_present_count", 0) or 0) > 0),
                "property_improved_count": sum(1 for row in rows if bool(row.get("property_x_improved", False))),
                "total_objective_improved_count": sum(1 for row in rows if bool(row.get("objective_total_improved", False))),
                "analysis_metric_improved_count": sum(1 for row in rows if bool(row.get("analysis_metric_improved", False))),
                "total_flat_property_gain_count": sum(1 for row in rows if bool(row.get("total_flat_property_gain", False))),
                "dominance_warning_count": sum(1 for row in rows if bool(row.get("dominance_warning", False))),
                "structure_changed_run_count": sum(
                    1
                    for row in rows
                    if isinstance(row.get("structure_change_rate"), (int, float))
                    and float(row.get("structure_change_rate")) > 0.0
                ),
                "best_action_ids_seen": sorted(
                    {str(row.get("best_action_id")) for row in rows if isinstance(row.get("best_action_id"), str)}
                ),
                "best_action_families_seen": sorted(
                    {str(row.get("best_action_family")) for row in rows if isinstance(row.get("best_action_family"), str)}
                ),
                "analysis_metric_first_run_final_best": first_metric,
                "analysis_metric_last_run_final_best": last_metric,
                "analysis_metric_trend_delta": _metric_delta(first_metric, last_metric),
            }
        )

    total_rows = len(all_rows)
    total_rows_denom = max(1, total_rows)
    first_run_metric = run_table[0].get("mean_analysis_metric_final_best") if run_table else None
    last_run_metric = run_table[-1].get("mean_analysis_metric_final_best") if run_table else None
    trend_delta = _metric_delta(_safe_float(first_run_metric), _safe_float(last_run_metric))
    run_indices = sorted({int(item.get("repeat_index", 0)) for item in run_table})

    def _mean_final_for_view(field: str, idx: int) -> float | None:
        values = [
            float(value)
            for value in (
                _safe_float(row.get(field))
                for row in all_rows
                if int(row.get("repeat_index", 0)) == idx
            )
            if value is not None
        ]
        return (sum(values) / len(values)) if values else None

    def _best_curve(series: list[float | None]) -> list[float | None]:
        best: float | None = None
        curve: list[float | None] = []
        for value in series:
            if isinstance(value, (int, float)):
                if best is None or float(value) > best:
                    best = float(value)
            curve.append(best)
        return curve

    objective_series = [_mean_final_for_view("final_best_objective_total", idx) for idx in run_indices]
    property_series = [_mean_final_for_view("final_best_property_x", idx) for idx in run_indices]
    objective_curve = _best_curve(objective_series)
    property_curve = _best_curve(property_series)
    objective_delta = _metric_delta(
        _safe_float(objective_curve[0]) if objective_curve else None,
        _safe_float(objective_curve[-1]) if objective_curve else None,
    )
    property_delta = _metric_delta(
        _safe_float(property_curve[0]) if property_curve else None,
        _safe_float(property_curve[-1]) if property_curve else None,
    )

    preferred_variant_by_run: list[dict[str, Any]] = []
    for idx in run_indices:
        action_counts: dict[str, int] = {}
        for row in all_rows:
            if int(row.get("repeat_index", 0)) != idx:
                continue
            action_id = row.get("best_action_id")
            if not isinstance(action_id, str):
                continue
            action_counts[action_id] = action_counts.get(action_id, 0) + 1
        if not action_counts:
            preferred_variant_by_run.append({"repeat_index": idx, "preferred_action_id": None, "count": 0})
            continue
        preferred = sorted(action_counts.items(), key=lambda item: (-item[1], item[0]))[0]
        preferred_variant_by_run.append(
            {"repeat_index": idx, "preferred_action_id": preferred[0], "count": int(preferred[1])}
        )
    preferred_ids = [item.get("preferred_action_id") for item in preferred_variant_by_run]
    preferred_ids_clean = [str(item) for item in preferred_ids if isinstance(item, str)]
    preferred_counts: dict[str, int] = {}
    for action_id in preferred_ids_clean:
        preferred_counts[action_id] = preferred_counts.get(action_id, 0) + 1
    stabilization_rate = (
        max(preferred_counts.values()) / len(preferred_ids_clean) if preferred_ids_clean else 0.0
    )
    churn_count = 0
    prev_action: str | None = None
    for item in preferred_variant_by_run:
        action_id = item.get("preferred_action_id")
        if not isinstance(action_id, str):
            continue
        if prev_action is not None and action_id != prev_action:
            churn_count += 1
        prev_action = action_id
    return {
        "schema_version": "first_crystal.repeated.summary.v1",
        "repeated_experiment_id": repeated_experiment_id,
        "case_file": str(case_file.resolve()),
        "reward_version": reward_version,
        "action_profile": action_profile,
        "analysis_metric_view": metric_view,
        "run_table": run_table,
        "per_case_table": case_rows,
        "run_case_rows": all_rows,
        "aggregate": {
            "total_runs": len(run_summaries),
            "total_case_runs": total_rows,
            "guidance_activation_rate": sum(1 for row in all_rows if bool(row.get("guidance_active", False)))
            / total_rows_denom,
            "spp_term_presence_rate": sum(
                1 for row in all_rows if int(row.get("spp_term_present_count", 0) or 0) > 0
            )
            / total_rows_denom,
            "property_improved_case_run_rate": sum(
                1 for row in all_rows if bool(row.get("property_x_improved", False))
            )
            / total_rows_denom,
            "total_objective_improved_case_run_rate": sum(
                1 for row in all_rows if bool(row.get("objective_total_improved", False))
            )
            / total_rows_denom,
            "analysis_metric_improved_case_run_rate": sum(
                1 for row in all_rows if bool(row.get("analysis_metric_improved", False))
            )
            / total_rows_denom,
            "total_flat_property_gain_case_run_rate": sum(
                1 for row in all_rows if bool(row.get("total_flat_property_gain", False))
            )
            / total_rows_denom,
            "spp_richer_exploration_case_run_rate": sum(
                1 for row in all_rows if bool(row.get("spp_richer_exploration_detected", False))
            )
            / total_rows_denom,
            "dominance_warning_case_run_rate": sum(
                1 for row in all_rows if bool(row.get("dominance_warning", False))
            )
            / total_rows_denom,
            "structure_changed_case_run_rate": sum(
                1
                for row in all_rows
                if isinstance(row.get("structure_change_rate"), (int, float))
                and float(row.get("structure_change_rate")) > 0.0
            )
            / total_rows_denom,
            "multi_weighting_profile_case_run_rate": sum(
                1
                for row in all_rows
                if isinstance(row.get("weighting_profiles_tried"), list)
                and len(row.get("weighting_profiles_tried")) > 1
            )
            / total_rows_denom,
            "multi_perturbation_profile_case_run_rate": sum(
                1
                for row in all_rows
                if isinstance(row.get("structure_perturbation_profiles_tried"), list)
                and len(row.get("structure_perturbation_profiles_tried")) > 1
            )
            / total_rows_denom,
            "mean_structure_change_rate": (
                sum(
                    float(row.get("structure_change_rate"))
                    for row in all_rows
                    if isinstance(row.get("structure_change_rate"), (int, float))
                )
                / max(
                    1,
                    sum(1 for row in all_rows if isinstance(row.get("structure_change_rate"), (int, float))),
                )
            ),
            "mean_analysis_metric_final_best_trend_delta": trend_delta,
            "evidence_of_learning_signal": bool(isinstance(trend_delta, (int, float)) and trend_delta > 1e-12),
            "view_summary": {
                "total_objective": {
                    "run_mean_series": objective_series,
                    "best_so_far_curve": objective_curve,
                    "best_so_far_delta": objective_delta,
                    "evidence_of_learning_signal": bool(
                        isinstance(objective_delta, (int, float)) and objective_delta > 1e-12
                    ),
                },
                "property_aware": {
                    "run_mean_series": property_series,
                    "best_so_far_curve": property_curve,
                    "best_so_far_delta": property_delta,
                    "evidence_of_learning_signal": bool(
                        isinstance(property_delta, (int, float)) and property_delta > 1e-12
                    ),
                },
            },
            "preferred_variant_by_run": preferred_variant_by_run,
            "preferred_variant_stabilization_rate": stabilization_rate,
            "preferred_variant_churn_count": churn_count,
        },
    }


def run_repeated_first_crystal_analysis(
    *,
    case_file: Path,
    mode: str,
    workspace: Path,
    settings: Settings,
    repeats: int = 3,
    max_iterations: int = 4,
    reward_version: str = "v1",
    action_profile: str = "default",
    analysis_metric_view: str = "score",
    include_baseline_control: bool = False,
    clarification_answers: list[str] | None = None,
    executor_factory: Any = None,
    strict_phase1_benchmark_mode: bool = False,
) -> dict[str, Any]:
    if int(repeats) < 1:
        raise ValueError("repeats must be >= 1")
    metric_view = _validate_metric_view(analysis_metric_view)
    repeated_id = _repeated_experiment_id(
        case_file=case_file,
        mode=mode,
        repeats=int(repeats),
        max_iterations=int(max_iterations),
        reward_version=reward_version,
        action_profile=action_profile,
        analysis_metric_view=metric_view,
        include_baseline_control=include_baseline_control,
        selection_metric_view=str(settings.optimization_selection_metric_view),
        strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
    )
    exp_dir = workspace / "experiments" / "first_crystal_repeated" / repeated_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    run_items: list[dict[str, Any]] = []
    for idx in range(1, int(repeats) + 1):
        run_tag = f"repeat-{idx:02d}"
        result = run_first_crystal_experiment(
            case_file=case_file,
            mode=mode,
            workspace=workspace,
            settings=copy.deepcopy(settings),
            max_iterations=max_iterations,
            reward_version=reward_version,
            action_profile=action_profile,
            analysis_metric_view=metric_view,
            run_tag=run_tag,
            include_baseline_control=include_baseline_control,
            clarification_answers=clarification_answers,
            executor_factory=executor_factory,
            strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
        )
        summary_payload = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
        run_items.append(
            {
                "repeat_index": idx,
                "run_tag": run_tag,
                "experiment_id": result["experiment_id"],
                "manifest_path": result["manifest_path"],
                "summary_path": result["summary_path"],
                "summary": summary_payload,
            }
        )
    summary = build_repeated_first_crystal_summary(
        repeated_experiment_id=repeated_id,
        case_file=case_file,
        run_summaries=run_items,
        reward_version=reward_version,
        action_profile=action_profile,
        analysis_metric_view=metric_view,
    )
    summary_path = exp_dir / "first_crystal_repeated_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "first_crystal.repeated.experiment.v1",
        "repeated_experiment_id": repeated_id,
        "mode": mode,
        "case_file": str(case_file.resolve()),
        "repeats": int(repeats),
        "max_iterations": int(max_iterations),
        "reward_version": reward_version,
        "action_profile": action_profile,
        "analysis_metric_view": metric_view,
        "include_baseline_control": bool(include_baseline_control),
        "clarification_answers": list(clarification_answers or []),
        "strict_phase1_benchmark_mode": bool(strict_phase1_benchmark_mode),
        "summary_path": str(summary_path),
        "runs": [
            {
                "repeat_index": int(item["repeat_index"]),
                "run_tag": str(item["run_tag"]),
                "experiment_id": str(item["experiment_id"]),
                "manifest_path": str(item["manifest_path"]),
                "summary_path": str(item["summary_path"]),
            }
            for item in run_items
        ],
    }
    manifest_path = exp_dir / "repeated_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "repeated_experiment_id": repeated_id,
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
    }


def regenerate_repeated_first_crystal_summary(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_file = Path(str(manifest["case_file"]))
    metric_view = _validate_metric_view(str(manifest.get("analysis_metric_view", "score")))
    run_items: list[dict[str, Any]] = []
    for run in manifest.get("runs", []):
        if not isinstance(run, dict):
            continue
        run_manifest = Path(str(run["manifest_path"]))
        run_summary = regenerate_first_crystal_summary(run_manifest)
        run_items.append(
            {
                "repeat_index": int(run.get("repeat_index", len(run_items) + 1)),
                "run_tag": str(run.get("run_tag", "")),
                "experiment_id": str(run.get("experiment_id", "")),
                "manifest_path": str(run_manifest),
                "summary_path": str(run.get("summary_path", "")),
                "summary": run_summary,
            }
        )
    return build_repeated_first_crystal_summary(
        repeated_experiment_id=str(manifest.get("repeated_experiment_id", "")),
        case_file=case_file,
        run_summaries=run_items,
        reward_version=str(manifest.get("reward_version", "v1")),
        action_profile=str(manifest.get("action_profile", "default")),
        analysis_metric_view=metric_view,
    )
