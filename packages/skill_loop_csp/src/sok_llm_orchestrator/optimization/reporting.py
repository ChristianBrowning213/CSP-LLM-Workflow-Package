from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.optimization.ablation import classify_ablation_change
from sok_llm_orchestrator.optimization.backend_sensitivity import (
    action_dimensions_from_compiled,
    build_sensitivity_trace_matrix,
    classify_backend_sensitivity,
    compiled_config_signature,
    objective_audit_from_run_dir,
    request_trace_from_run_dir,
    summarize_dimension_sensitivity,
)
from sok_llm_orchestrator.optimization.failure_taxonomy import classify_failure_taxonomy
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession
from sok_llm_orchestrator.optimization.stats import summarize_action_families
from sok_llm_orchestrator.orchestrator.logging import canonical_json, sha256_text
from sok_llm_orchestrator.verification.qlip_outputs import structure_signature_from_cif_path


def _first_improvement_iteration(iteration_history: list[dict[str, Any]]) -> int | None:
    for row in iteration_history:
        idx = row.get("iteration_index")
        if not isinstance(idx, int) or idx <= 0:
            continue
        if bool(row.get("best_updated", False)):
            return idx
    return None


def _flatness_reason(
    *,
    unique_action_ids: int,
    unique_action_families: int,
    unique_compiled_signatures: int,
    unique_executable_signatures: int,
    unique_score_values: int,
) -> str | None:
    if unique_score_values > 1:
        return None
    if unique_compiled_signatures == 0 and unique_executable_signatures == 0:
        return "missing_config_signature_data"
    if unique_action_ids <= 1:
        return "repeated_same_action"
    if unique_compiled_signatures <= 1 or unique_executable_signatures <= 1:
        return "different_actions_same_effective_config"
    if unique_action_families <= 1:
        return "no_legal_diversity_explored"
    return "backend_objective_invariant_under_tested_actions"


def _fallback_executable_signature(*, query_text: str, compiled: dict[str, Any]) -> str:
    payload = {
        "query": query_text,
        "query_suffix": compiled.get("query_suffix"),
        "guided_with_spp": compiled.get("guided_with_spp"),
        "baseline_overrides": compiled.get("baseline_overrides"),
        "guided_overrides": compiled.get("guided_overrides"),
    }
    return sha256_text(canonical_json(payload))


def _row_compiled_signature(row: dict[str, Any]) -> str | None:
    if isinstance(row.get("compiled_config_signature"), str):
        return str(row["compiled_config_signature"])
    compiled = row.get("compiled_action")
    if isinstance(compiled, dict):
        return compiled_config_signature(compiled, include_action_identity=False)
    return None


def _row_executable_signature(row: dict[str, Any], *, query_text: str) -> str | None:
    if isinstance(row.get("executable_signature"), str):
        return str(row["executable_signature"])
    compiled = row.get("compiled_action")
    if isinstance(compiled, dict):
        return _fallback_executable_signature(query_text=query_text, compiled=compiled)
    return None


def _row_objective_audit(row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(row.get("objective_audit"), dict):
        return dict(row["objective_audit"])
    run_reference = row.get("run_reference", {})
    if isinstance(run_reference, dict):
        guided_run_dir = run_reference.get("guided_run_dir")
        if isinstance(guided_run_dir, str) and guided_run_dir:
            audit = objective_audit_from_run_dir(Path(guided_run_dir))
            if isinstance(audit, dict):
                return audit
    primary = row.get("primary_objective")
    value = float(primary) if isinstance(primary, (int, float)) else None
    terms = [{"term": "objective_total", "value": value}] if value is not None else []
    return {
        "objective_total": value,
        "objective_terms": terms,
        "objective_terms_signature": sha256_text(canonical_json(terms)),
        "baseline_term": None,
        "spp_term": None,
        "guidance_terms": [],
        "solver_summary": {},
    }


def _row_request_trace(row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(row.get("request_trace"), dict):
        return dict(row["request_trace"])
    run_reference = row.get("run_reference", {})
    if isinstance(run_reference, dict):
        guided_run_dir = run_reference.get("guided_run_dir")
        if isinstance(guided_run_dir, str) and guided_run_dir:
            return request_trace_from_run_dir(Path(guided_run_dir))
    compiled = row.get("compiled_action")
    if isinstance(compiled, dict):
        return {"effective_overrides": dict(compiled.get("guided_overrides", {}))}
    return {}


def _row_structure_tracking(row: dict[str, Any]) -> dict[str, Any]:
    run_reference = row.get("run_reference", {})
    if not isinstance(run_reference, dict):
        run_reference = {}
    path_val = (
        row.get("structure_artifact_path")
        if isinstance(row.get("structure_artifact_path"), str)
        else run_reference.get("structure_artifact_path")
    )
    structure_tracking = (
        dict(run_reference.get("structure_tracking", {}))
        if isinstance(run_reference.get("structure_tracking"), dict)
        else {}
    )
    signature = row.get("structure_signature")
    if not isinstance(signature, str):
        maybe = structure_tracking.get("structure_signature")
        signature = maybe if isinstance(maybe, str) else None
    if not isinstance(signature, str):
        computed = structure_signature_from_cif_path(path_val if isinstance(path_val, str) else None)
        signature = computed.get("structure_signature") if isinstance(computed.get("structure_signature"), str) else None
        structure_tracking = {
            "structure_source": computed.get("structure_source"),
            "structure_content_hash": computed.get("structure_content_hash"),
            "formula_signature": computed.get("formula_signature"),
            "lattice_signature": computed.get("lattice_signature"),
            "path_exists": bool(computed.get("path_exists", False)),
        }
    return {
        "structure_artifact_path": path_val if isinstance(path_val, str) else None,
        "structure_signature": signature if isinstance(signature, str) else None,
        "structure_source": (
            row.get("structure_source")
            if isinstance(row.get("structure_source"), str)
            else structure_tracking.get("structure_source")
        ),
        "structure_content_hash": (
            row.get("structure_content_hash")
            if isinstance(row.get("structure_content_hash"), str)
            else structure_tracking.get("structure_content_hash")
        ),
        "formula_signature": (
            row.get("formula_signature")
            if isinstance(row.get("formula_signature"), str)
            else structure_tracking.get("formula_signature")
        ),
        "lattice_signature": (
            row.get("lattice_signature")
            if isinstance(row.get("lattice_signature"), str)
            else structure_tracking.get("lattice_signature")
        ),
    }


def _objective_vs_structure_trace(iteration_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    prev_audit_sig: str | None = None
    prev_guidance_sig: str | None = None
    prev_structure_sig: str | None = None
    prev_property: float | None = None
    for row in iteration_history:
        first_row = len(out) == 0
        idx = row.get("iteration_index")
        objective = row.get("objective_vs_structure_change", {})
        if not isinstance(objective, dict):
            objective = {}
        audit = _row_objective_audit(row)
        audit_sig = audit.get("objective_terms_signature")
        request_trace = _row_request_trace(row)
        effective_overrides = (
            dict(request_trace.get("effective_overrides", {}))
            if isinstance(request_trace.get("effective_overrides"), dict)
            else {}
        )
        weighting_profile = str(
            row.get("weighting_profile")
            if isinstance(row.get("weighting_profile"), str)
            else effective_overrides.get("weighting_profile", "balanced")
        ).strip().lower()
        perturbation_profile = str(
            row.get("structure_perturbation_profile")
            if isinstance(row.get("structure_perturbation_profile"), str)
            else effective_overrides.get("structure_perturbation_profile", "minimal")
        ).strip().lower()
        template_seed_profile = str(
            row.get("template_seed_profile")
            if isinstance(row.get("template_seed_profile"), str)
            else effective_overrides.get("template_seed_profile", "canonical")
        ).strip().lower()
        lattice_candidate_profile = str(
            row.get("lattice_candidate_profile")
            if isinstance(row.get("lattice_candidate_profile"), str)
            else effective_overrides.get("lattice_candidate_profile", "narrow")
        ).strip().lower()
        symmetry_relaxation_profile = str(
            row.get("symmetry_relaxation_profile")
            if isinstance(row.get("symmetry_relaxation_profile"), str)
            else effective_overrides.get("symmetry_relaxation_profile", "strict")
        ).strip().lower()
        ordering_perturbation_profile = str(
            row.get("ordering_perturbation_profile")
            if isinstance(row.get("ordering_perturbation_profile"), str)
            else effective_overrides.get("ordering_perturbation_profile", "none")
        ).strip().lower()
        guidance_sig = request_trace.get("guidance_structure_signature")
        structure = _row_structure_tracking(row)
        structure_sig = structure.get("structure_signature")
        reward = row.get("reward", {})
        property_value = (
            reward.get("property_estimate")
            if isinstance(reward, dict)
            else None
        )
        property_delta = (
            float(property_value) - float(prev_property)
            if isinstance(property_value, (int, float)) and isinstance(prev_property, (int, float))
            else None
        )
        objective_changed = (
            bool(objective.get("objective_changed"))
            if "objective_changed" in objective
            else isinstance(audit_sig, str) and isinstance(prev_audit_sig, str) and audit_sig != prev_audit_sig
        )
        guidance_changed = (
            bool(objective.get("guidance_changed"))
            if "guidance_changed" in objective
            else isinstance(guidance_sig, str) and isinstance(prev_guidance_sig, str) and guidance_sig != prev_guidance_sig
        )
        structure_changed = (
            bool(objective.get("structure_changed"))
            if "structure_changed" in objective
            else isinstance(structure_sig, str) and isinstance(prev_structure_sig, str) and structure_sig != prev_structure_sig
        )
        if prev_structure_sig is None and isinstance(structure_sig, str):
            structure_changed = True
        if first_row:
            objective_changed = False
            guidance_changed = False
            structure_changed = False
        classification = objective.get("classification")
        if not isinstance(classification, str):
            if first_row:
                classification = "initial"
            elif objective_changed and not structure_changed:
                classification = "objective_changed_structure_unchanged"
            elif guidance_changed and not structure_changed:
                classification = "guidance_changed_structure_unchanged"
            elif structure_changed and isinstance(property_delta, (int, float)) and float(property_delta) > 1e-12:
                classification = "structure_changed_property_gain"
            elif structure_changed:
                classification = "structure_changed_no_property_gain"
            else:
                classification = "no_meaningful_change"
        out.append(
            {
                "iteration_index": idx,
                "classification": classification,
                "objective_changed": bool(objective_changed),
                "guidance_changed": bool(guidance_changed),
                "structure_changed": bool(structure_changed),
                "property_delta_vs_previous": property_delta,
                "structure_signature": structure_sig,
                "structure_artifact_path": structure.get("structure_artifact_path"),
            }
        )
        prev_audit_sig = audit_sig if isinstance(audit_sig, str) else prev_audit_sig
        prev_guidance_sig = guidance_sig if isinstance(guidance_sig, str) else prev_guidance_sig
        prev_structure_sig = structure_sig if isinstance(structure_sig, str) else prev_structure_sig
        prev_property = float(property_value) if isinstance(property_value, (int, float)) else prev_property
    return out


def _iteration_effectiveness_trace(iteration_history: list[dict[str, Any]], *, query_text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    prev_input: dict[str, Any] | None = None
    for row in iteration_history:
        arbitration = row.get("arbitration", {})
        if not isinstance(arbitration, dict):
            arbitration = {}
        details = arbitration.get("details", {})
        llm = arbitration.get("llm_proposal", {})
        gate = arbitration.get("gate", {})
        objective_audit = _row_objective_audit(row)
        request_trace = _row_request_trace(row)
        action_dimensions = (
            dict(row.get("action_dimensions", {}))
            if isinstance(row.get("action_dimensions"), dict)
            else action_dimensions_from_compiled(row.get("compiled_action", {}))
            if isinstance(row.get("compiled_action"), dict)
            else {}
        )
        sensitivity_matrix = (
            dict(row.get("sensitivity_trace_matrix", {}))
            if isinstance(row.get("sensitivity_trace_matrix"), dict)
            else {}
        )
        if not sensitivity_matrix:
            sensitivity_matrix = build_sensitivity_trace_matrix(
                prev_input,
                {
                    "action_dimensions": action_dimensions,
                    "request_trace": request_trace,
                    "objective_audit": objective_audit,
                },
            )
        objective_total = objective_audit.get("objective_total")
        score_value = row.get("score")
        score_minus_objective = (
            float(score_value) - float(objective_total)
            if isinstance(score_value, (int, float)) and isinstance(objective_total, (int, float))
            else None
        )
        structure = _row_structure_tracking(row)
        objective_vs_structure = (
            dict(row.get("objective_vs_structure_change", {}))
            if isinstance(row.get("objective_vs_structure_change"), dict)
            else {}
        )
        effective_overrides = (
            dict(request_trace.get("effective_overrides", {}))
            if isinstance(request_trace.get("effective_overrides"), dict)
            else {}
        )
        weighting_profile = str(
            row.get("weighting_profile")
            if isinstance(row.get("weighting_profile"), str)
            else effective_overrides.get("weighting_profile", "balanced")
        ).strip().lower()
        perturbation_profile = str(
            row.get("structure_perturbation_profile")
            if isinstance(row.get("structure_perturbation_profile"), str)
            else effective_overrides.get("structure_perturbation_profile", "minimal")
        ).strip().lower()
        template_seed_profile = str(
            row.get("template_seed_profile")
            if isinstance(row.get("template_seed_profile"), str)
            else effective_overrides.get("template_seed_profile", "canonical")
        ).strip().lower()
        lattice_candidate_profile = str(
            row.get("lattice_candidate_profile")
            if isinstance(row.get("lattice_candidate_profile"), str)
            else effective_overrides.get("lattice_candidate_profile", "narrow")
        ).strip().lower()
        symmetry_relaxation_profile = str(
            row.get("symmetry_relaxation_profile")
            if isinstance(row.get("symmetry_relaxation_profile"), str)
            else effective_overrides.get("symmetry_relaxation_profile", "strict")
        ).strip().lower()
        ordering_perturbation_profile = str(
            row.get("ordering_perturbation_profile")
            if isinstance(row.get("ordering_perturbation_profile"), str)
            else effective_overrides.get("ordering_perturbation_profile", "none")
        ).strip().lower()
        entry = {
            "iteration_index": row.get("iteration_index"),
            "chosen_action_id": row.get("action_id"),
            "chosen_action_family": row.get("action_family"),
            "active_hypothesis_id": row.get("active_hypothesis_id"),
            "active_hypothesis_label": row.get("active_hypothesis_label"),
            "active_hypothesis_family": row.get("active_hypothesis_family"),
            "candidate_action_ids": list(row.get("candidate_action_ids", []))
            if isinstance(row.get("candidate_action_ids"), list)
            else [],
            "bandit_ranked": list(arbitration.get("bandit_ranked", []))
            if isinstance(arbitration.get("bandit_ranked"), list)
            else [],
            "llm_action_id": llm.get("action_id") if isinstance(llm, dict) else None,
            "llm_ranked_action_ids": list(llm.get("ranked_action_ids", []))
            if isinstance(llm, dict) and isinstance(llm.get("ranked_action_ids"), list)
            else [],
            "gate_reason": gate.get("reason") if isinstance(gate, dict) else None,
            "compiled_delta": row.get("compiled_delta"),
            "material_config_change": bool(row.get("material_config_change", False)),
            "material_executable_change": bool(row.get("material_executable_change", False)),
            "compiled_config_signature": _row_compiled_signature(row),
            "executable_signature": _row_executable_signature(row, query_text=query_text),
            "request_trace": request_trace,
            "weighting_profile": weighting_profile,
            "structure_perturbation_profile": perturbation_profile,
            "template_seed_profile": template_seed_profile,
            "lattice_candidate_profile": lattice_candidate_profile,
            "symmetry_relaxation_profile": symmetry_relaxation_profile,
            "ordering_perturbation_profile": ordering_perturbation_profile,
            "action_dimensions": action_dimensions,
            "structure_artifact_path": structure.get("structure_artifact_path"),
            "structure_signature": structure.get("structure_signature"),
            "structure_source": structure.get("structure_source"),
            "score": row.get("score"),
            "score_delta_vs_previous": row.get("score_delta_vs_previous"),
            "primary_objective": row.get("primary_objective"),
            "objective_audit": objective_audit,
            "score_minus_objective_total": score_minus_objective,
            "objective_delta_vs_previous": row.get("objective_delta_vs_previous"),
            "best_updated": bool(row.get("best_updated", False)),
            "combined_ranked": list(details.get("combined_ranked", []))
            if isinstance(details, dict) and isinstance(details.get("combined_ranked"), list)
            else [],
            "sensitivity_trace_matrix": sensitivity_matrix,
            "objective_vs_structure_change": objective_vs_structure,
        }
        out.append(entry)
        prev_input = {
            "action_dimensions": action_dimensions,
            "request_trace": request_trace,
            "objective_audit": objective_audit,
        }
    return out


def _spp_exploration_summary(iteration_effectiveness_trace: list[dict[str, Any]]) -> dict[str, Any]:
    retrieval_modes: set[str] = set()
    corpus_strategies: set[str] = set()
    selected_corpus_ids: set[str] = set()
    corpus_candidate_ids: set[str] = set()
    selected_package_variants: set[str] = set()
    package_candidate_ids: set[str] = set()
    payload_signatures: set[str] = set()
    guidance_weights: set[float] = set()
    lambda_sources: set[str] = set()
    top_k_breakdowns: set[int] = set()
    iteration_trace: list[dict[str, Any]] = []
    branch_count = 0
    previous_tuple: tuple[str | None, str | None, str | None] | None = None

    for row in iteration_effectiveness_trace:
        req = row.get("request_trace", {})
        if not isinstance(req, dict):
            req = {}
        overrides = req.get("effective_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        builder = req.get("builder_input_trace", {})
        if not isinstance(builder, dict):
            builder = {}
        builder_inputs = builder.get("builder_inputs", {})
        if not isinstance(builder_inputs, dict):
            builder_inputs = {}

        retrieval_mode = overrides.get("retrieval_mode")
        if isinstance(retrieval_mode, str):
            retrieval_modes.add(retrieval_mode)
        corpus_strategy = overrides.get("corpus_strategy")
        if isinstance(corpus_strategy, str):
            corpus_strategies.add(corpus_strategy)

        selected_corpus = builder_inputs.get("selected_corpus_candidate_id")
        if isinstance(selected_corpus, str):
            selected_corpus_ids.add(selected_corpus)
        raw_corpus_candidates = builder_inputs.get("corpus_candidate_ids", [])
        if isinstance(raw_corpus_candidates, list):
            for item in raw_corpus_candidates:
                if isinstance(item, str):
                    corpus_candidate_ids.add(item)

        selected_variant = builder_inputs.get("selected_spp_package_variant")
        if isinstance(selected_variant, str):
            selected_package_variants.add(selected_variant)
        raw_package_candidates = builder_inputs.get("spp_package_candidate_ids", [])
        if isinstance(raw_package_candidates, list):
            for item in raw_package_candidates:
                if isinstance(item, str):
                    package_candidate_ids.add(item)

        payload = builder_inputs.get("guidance_payload", {})
        if not isinstance(payload, dict):
            payload = {}
        payload_sig = sha256_text(canonical_json(payload)) if payload else None
        if isinstance(payload_sig, str):
            payload_signatures.add(payload_sig)
        weight = payload.get("lambda_override")
        if isinstance(weight, (int, float)):
            guidance_weights.add(float(weight))
        lambda_source = builder_inputs.get("spp_lambda_source")
        if isinstance(lambda_source, str) and lambda_source.strip():
            lambda_sources.add(lambda_source.strip())
        top_k = payload.get("top_k_breakdown")
        if isinstance(top_k, int):
            top_k_breakdowns.add(int(top_k))

        current_tuple = (
            selected_corpus if isinstance(selected_corpus, str) else None,
            selected_variant if isinstance(selected_variant, str) else None,
            payload_sig if isinstance(payload_sig, str) else None,
        )
        branched = previous_tuple is not None and current_tuple != previous_tuple
        if branched:
            branch_count += 1
        previous_tuple = current_tuple
        iteration_trace.append(
            {
                "iteration_index": row.get("iteration_index"),
                "retrieval_mode": retrieval_mode,
                "corpus_strategy": corpus_strategy,
                "selected_corpus_candidate_id": selected_corpus,
                "selected_spp_package_variant": selected_variant,
                "guidance_payload_signature": payload_sig,
                "guidance_weight": float(weight) if isinstance(weight, (int, float)) else None,
                "spp_lambda_source": lambda_source if isinstance(lambda_source, str) else None,
                "top_k_breakdown": int(top_k) if isinstance(top_k, int) else None,
                "branched_from_previous": bool(branched),
            }
        )

    return {
        "unique_retrieval_mode_count": len(retrieval_modes),
        "unique_retrieval_modes": sorted(retrieval_modes),
        "unique_corpus_strategy_count": len(corpus_strategies),
        "unique_corpus_strategies": sorted(corpus_strategies),
        "unique_selected_corpus_candidate_count": len(selected_corpus_ids),
        "unique_selected_corpus_candidate_ids": sorted(selected_corpus_ids),
        "unique_corpus_candidate_pool_count": len(corpus_candidate_ids),
        "unique_corpus_candidate_pool_ids": sorted(corpus_candidate_ids),
        "unique_spp_package_variant_count": len(selected_package_variants),
        "unique_spp_package_variants": sorted(selected_package_variants),
        "unique_spp_package_candidate_pool_count": len(package_candidate_ids),
        "unique_spp_package_candidate_pool_ids": sorted(package_candidate_ids),
        "unique_spp_payload_signature_count": len(payload_signatures),
        "guidance_weight_values": sorted(guidance_weights),
        "spp_lambda_sources": sorted(lambda_sources),
        "top_k_breakdown_values": sorted(top_k_breakdowns),
        "branch_count": int(branch_count),
        "richer_exploration_detected": bool(
            len(selected_corpus_ids) > 1
            or len(selected_package_variants) > 1
            or len(payload_signatures) > 1
            or branch_count > 0
        ),
        "iteration_spp_trace": iteration_trace,
    }


def _structure_diversity_and_dominance(
    *,
    iteration_effectiveness_trace: list[dict[str, Any]],
    objective_vs_structure_trace: list[dict[str, Any]],
    unique_objective_term_signatures: int,
    spp_exploration_summary: dict[str, Any],
) -> dict[str, Any]:
    structure_signatures = sorted(
        {
            str(item.get("structure_signature"))
            for item in iteration_effectiveness_trace
            if isinstance(item.get("structure_signature"), str)
        }
    )
    structure_change_count = sum(
        1
        for item in objective_vs_structure_trace
        if bool(item.get("structure_changed", False))
    )
    objective_changed_structure_unchanged = sum(
        1
        for item in objective_vs_structure_trace
        if str(item.get("classification")) == "objective_changed_structure_unchanged"
    )
    guidance_changed_structure_unchanged = sum(
        1
        for item in objective_vs_structure_trace
        if str(item.get("classification")) == "guidance_changed_structure_unchanged"
    )
    payload_diversity = int(spp_exploration_summary.get("unique_spp_payload_signature_count", 0) or 0)
    structure_diversity = len(structure_signatures)
    no_move_rate = (
        float(objective_changed_structure_unchanged + guidance_changed_structure_unchanged)
        / float(max(1, len(objective_vs_structure_trace)))
    )
    dominance_warning = bool(
        (
            payload_diversity > 1
            and structure_diversity <= 1
            and (objective_changed_structure_unchanged + guidance_changed_structure_unchanged) > 0
        )
        or (unique_objective_term_signatures > 1 and structure_diversity <= 1)
    )
    if dominance_warning:
        recommendation = "likely_base_weight_or_constraint_dominance"
    elif structure_diversity > 1:
        recommendation = "structure_changes_observed_check_gain_alignment"
    else:
        recommendation = "insufficient_structure_signal"

    return {
        "unique_structure_signatures": structure_signatures,
        "unique_structure_signature_count": structure_diversity,
        "structure_change_count": structure_change_count,
        "structure_change_rate": structure_change_count / float(max(1, len(objective_vs_structure_trace))),
        "objective_changed_structure_unchanged_count": objective_changed_structure_unchanged,
        "guidance_changed_structure_unchanged_count": guidance_changed_structure_unchanged,
        "same_structure_despite_guidance_variation_rate": no_move_rate,
        "payload_diversity_vs_structure_diversity": {
            "payload_signature_count": payload_diversity,
            "structure_signature_count": structure_diversity,
        },
        "objective_term_diversity_vs_structure_diversity": {
            "objective_term_signature_count": int(unique_objective_term_signatures),
            "structure_signature_count": structure_diversity,
        },
        "dominance_warning": dominance_warning,
        "dominance_recommendation": recommendation,
    }


def _regime_level_summary(
    *,
    iteration_effectiveness_trace: list[dict[str, Any]],
    objective_vs_structure_trace: list[dict[str, Any]],
) -> dict[str, Any]:
    by_iteration_index = {
        int(item.get("iteration_index")): item
        for item in objective_vs_structure_trace
        if isinstance(item.get("iteration_index"), int)
    }
    regimes: dict[str, dict[str, Any]] = {}
    for row in iteration_effectiveness_trace:
        idx = row.get("iteration_index")
        if not isinstance(idx, int):
            continue
        weighting = str(row.get("weighting_profile", "balanced")).strip().lower()
        perturb = str(row.get("structure_perturbation_profile", "minimal")).strip().lower()
        seed = str(row.get("template_seed_profile", "canonical")).strip().lower()
        lattice_profile = str(row.get("lattice_candidate_profile", "narrow")).strip().lower()
        symmetry_profile = str(row.get("symmetry_relaxation_profile", "strict")).strip().lower()
        ordering_profile = str(row.get("ordering_perturbation_profile", "none")).strip().lower()
        regime_id = f"{weighting}|{perturb}|{seed}|{lattice_profile}|{symmetry_profile}|{ordering_profile}"
        bucket = regimes.setdefault(
            regime_id,
            {
                "weighting_profile": weighting,
                "structure_perturbation_profile": perturb,
                "template_seed_profile": seed,
                "lattice_candidate_profile": lattice_profile,
                "symmetry_relaxation_profile": symmetry_profile,
                "ordering_perturbation_profile": ordering_profile,
                "iterations": 0,
                "structure_changed_count": 0,
                "objective_changed_structure_unchanged_count": 0,
                "guidance_changed_structure_unchanged_count": 0,
                "property_gain_count": 0,
                "dominance_warning_count": 0,
                "structure_signatures": set(),
                "scores": [],
            },
        )
        bucket["iterations"] = int(bucket["iterations"]) + 1
        ovs = by_iteration_index.get(idx, {})
        if bool(ovs.get("structure_changed", False)):
            bucket["structure_changed_count"] = int(bucket["structure_changed_count"]) + 1
        structure_sig = ovs.get("structure_signature")
        if isinstance(structure_sig, str) and structure_sig:
            cast_set = bucket.get("structure_signatures")
            if isinstance(cast_set, set):
                cast_set.add(structure_sig)
        cls = str(ovs.get("classification", ""))
        if cls == "objective_changed_structure_unchanged":
            bucket["objective_changed_structure_unchanged_count"] = int(bucket["objective_changed_structure_unchanged_count"]) + 1
            bucket["dominance_warning_count"] = int(bucket["dominance_warning_count"]) + 1
        if cls == "guidance_changed_structure_unchanged":
            bucket["guidance_changed_structure_unchanged_count"] = int(bucket["guidance_changed_structure_unchanged_count"]) + 1
            bucket["dominance_warning_count"] = int(bucket["dominance_warning_count"]) + 1
        prop_delta = ovs.get("property_delta_vs_previous")
        if isinstance(prop_delta, (int, float)) and float(prop_delta) > 1e-12:
            bucket["property_gain_count"] = int(bucket["property_gain_count"]) + 1
        score = row.get("score")
        if isinstance(score, (int, float)):
            bucket["scores"].append(float(score))

    rows: list[dict[str, Any]] = []
    for regime_id in sorted(regimes):
        item = regimes[regime_id]
        iterations = max(1, int(item["iterations"]))
        rows.append(
            {
                "regime_id": regime_id,
                "weighting_profile": item["weighting_profile"],
                "structure_perturbation_profile": item["structure_perturbation_profile"],
                "template_seed_profile": item["template_seed_profile"],
                "lattice_candidate_profile": item["lattice_candidate_profile"],
                "symmetry_relaxation_profile": item["symmetry_relaxation_profile"],
                "ordering_perturbation_profile": item["ordering_perturbation_profile"],
                "iterations": int(item["iterations"]),
                "structure_changed_count": int(item["structure_changed_count"]),
                "structure_change_rate": float(item["structure_changed_count"]) / float(iterations),
                "unique_structure_signature_count": len(item["structure_signatures"]) if isinstance(item.get("structure_signatures"), set) else 0,
                "objective_changed_structure_unchanged_count": int(item["objective_changed_structure_unchanged_count"]),
                "guidance_changed_structure_unchanged_count": int(item["guidance_changed_structure_unchanged_count"]),
                "property_gain_count": int(item["property_gain_count"]),
                "property_gain_rate": float(item["property_gain_count"]) / float(iterations),
                "dominance_warning_count": int(item["dominance_warning_count"]),
                "dominance_warning_rate": float(item["dominance_warning_count"]) / float(iterations),
                "mean_score": (
                    sum(float(v) for v in item["scores"]) / len(item["scores"])
                    if item["scores"]
                    else None
                ),
            }
        )

    recommended = None
    if rows:
        ranked = sorted(
            rows,
            key=lambda r: (
                -float(r.get("structure_change_rate", 0.0)),
                -float(r.get("unique_structure_signature_count", 0.0)),
                -float(r.get("property_gain_rate", 0.0)),
                float(r.get("dominance_warning_rate", 1.0)),
                str(r.get("regime_id")),
            ),
        )
        recommended = str(ranked[0].get("regime_id"))

    structure_change_rate_by_regime = {
        str(row.get("regime_id")): float(row.get("structure_change_rate", 0.0))
        for row in rows
    }
    unique_structure_signature_count_by_regime = {
        str(row.get("regime_id")): int(row.get("unique_structure_signature_count", 0))
        for row in rows
    }
    property_gain_by_regime = {
        str(row.get("regime_id")): float(row.get("property_gain_rate", 0.0))
        for row in rows
    }
    dominance_warning_by_regime = {
        str(row.get("regime_id")): float(row.get("dominance_warning_rate", 0.0))
        for row in rows
    }
    recommended_structure_moving_regimes = [
        str(row.get("regime_id"))
        for row in sorted(
            rows,
            key=lambda r: (
                -float(r.get("structure_change_rate", 0.0)),
                -float(r.get("unique_structure_signature_count", 0.0)),
                -float(r.get("property_gain_rate", 0.0)),
                float(r.get("dominance_warning_rate", 1.0)),
                str(r.get("regime_id")),
            ),
        )[:3]
    ]

    return {
        "rows": rows,
        "unique_weighting_profiles": sorted({str(r["weighting_profile"]) for r in rows}),
        "unique_structure_perturbation_profiles": sorted({str(r["structure_perturbation_profile"]) for r in rows}),
        "unique_template_seed_profiles": sorted({str(r["template_seed_profile"]) for r in rows}),
        "unique_lattice_candidate_profiles": sorted({str(r["lattice_candidate_profile"]) for r in rows}),
        "unique_symmetry_relaxation_profiles": sorted({str(r["symmetry_relaxation_profile"]) for r in rows}),
        "unique_ordering_perturbation_profiles": sorted({str(r["ordering_perturbation_profile"]) for r in rows}),
        "unique_structure_signature_count_by_regime": unique_structure_signature_count_by_regime,
        "structure_change_rate_by_regime": structure_change_rate_by_regime,
        "property_gain_by_regime": property_gain_by_regime,
        "dominance_warning_by_regime": dominance_warning_by_regime,
        "recommended_structure_moving_regimes": recommended_structure_moving_regimes,
        "recommended_next_regime": recommended,
    }


def _hypothesis_branch_summary(
    *,
    iteration_effectiveness_trace: list[dict[str, Any]],
    objective_vs_structure_trace: list[dict[str, Any]],
    hypothesis_state: dict[str, Any] | None,
) -> dict[str, Any]:
    by_iteration_index = {
        int(item.get("iteration_index")): item
        for item in objective_vs_structure_trace
        if isinstance(item.get("iteration_index"), int)
    }
    buckets: dict[str, dict[str, Any]] = {}
    for row in iteration_effectiveness_trace:
        hyp_id_raw = row.get("active_hypothesis_id")
        if not isinstance(hyp_id_raw, str) or not hyp_id_raw:
            hyp_id_raw = "__none__"
        hyp_id = str(hyp_id_raw)
        bucket = buckets.setdefault(
            hyp_id,
            {
                "hypothesis_id": None if hyp_id == "__none__" else hyp_id,
                "hypothesis_label": row.get("active_hypothesis_label"),
                "hypothesis_family": row.get("active_hypothesis_family"),
                "iterations": 0,
                "best_score": None,
                "best_iteration_index": None,
                "best_action_id": None,
                "structure_signatures": set(),
                "structure_changed_count": 0,
                "property_gain_count": 0,
            },
        )
        bucket["iterations"] = int(bucket["iterations"]) + 1
        idx = row.get("iteration_index")
        ovs = by_iteration_index.get(int(idx)) if isinstance(idx, int) else {}
        if bool(ovs.get("structure_changed", False)):
            bucket["structure_changed_count"] = int(bucket["structure_changed_count"]) + 1
        structure_sig = row.get("structure_signature")
        if isinstance(structure_sig, str) and structure_sig:
            sigs = bucket.get("structure_signatures")
            if isinstance(sigs, set):
                sigs.add(structure_sig)
        prop_delta = ovs.get("property_delta_vs_previous")
        if isinstance(prop_delta, (int, float)) and float(prop_delta) > 1e-12:
            bucket["property_gain_count"] = int(bucket["property_gain_count"]) + 1
        score = row.get("score")
        if isinstance(score, (int, float)):
            best_score = bucket.get("best_score")
            if not isinstance(best_score, (int, float)) or float(score) > float(best_score):
                bucket["best_score"] = float(score)
                bucket["best_iteration_index"] = idx
                bucket["best_action_id"] = row.get("chosen_action_id")

    rows: list[dict[str, Any]] = []
    for key in sorted(buckets):
        item = buckets[key]
        iterations = max(1, int(item["iterations"]))
        rows.append(
            {
                "hypothesis_id": item["hypothesis_id"],
                "hypothesis_label": item["hypothesis_label"],
                "hypothesis_family": item["hypothesis_family"],
                "iterations": int(item["iterations"]),
                "best_score": item["best_score"],
                "best_iteration_index": item["best_iteration_index"],
                "best_action_id": item["best_action_id"],
                "unique_structure_signature_count": (
                    len(item["structure_signatures"]) if isinstance(item.get("structure_signatures"), set) else 0
                ),
                "structure_change_rate": float(item["structure_changed_count"]) / float(iterations),
                "property_gain_rate": float(item["property_gain_count"]) / float(iterations),
            }
        )

    best_hypothesis_id: str | None = None
    if rows:
        ranked = sorted(
            rows,
            key=lambda row: (
                -float(row.get("best_score", float("-inf")) if isinstance(row.get("best_score"), (int, float)) else float("-inf")),
                -float(row.get("property_gain_rate", 0.0)),
                -float(row.get("structure_change_rate", 0.0)),
                str(row.get("hypothesis_id")),
            ),
        )
        best = ranked[0]
        if isinstance(best.get("hypothesis_id"), str):
            best_hypothesis_id = str(best["hypothesis_id"])

    state = hypothesis_state if isinstance(hypothesis_state, dict) else {}
    switch_events = list(state.get("switch_events", [])) if isinstance(state.get("switch_events"), list) else []
    tried = [str(item) for item in state.get("tried_hypothesis_ids", []) if isinstance(item, str)]
    available = [
        str(item.get("hypothesis_id"))
        for item in state.get("available_hypotheses", [])
        if isinstance(item, dict) and isinstance(item.get("hypothesis_id"), str)
    ] if isinstance(state.get("available_hypotheses"), list) else []
    active_by_iteration = [
        {
            "iteration_index": item.get("iteration_index"),
            "hypothesis_id": item.get("active_hypothesis_id"),
            "hypothesis_label": item.get("active_hypothesis_label"),
            "hypothesis_family": item.get("active_hypothesis_family"),
        }
        for item in iteration_effectiveness_trace
    ]
    return {
        "available_hypothesis_ids": available,
        "hypotheses_tried": sorted(set(tried)),
        "active_hypothesis_by_iteration": active_by_iteration,
        "branch_switch_count": len(switch_events),
        "branch_switch_events": switch_events,
        "best_hypothesis_id": best_hypothesis_id,
        "rows": rows,
    }


def build_optimization_report(session: OptimizationSession) -> dict[str, Any]:
    budget_state = session.budget_state if isinstance(session.budget_state, dict) else {}
    budget_config = budget_state.get("config", {}) if isinstance(budget_state.get("config"), dict) else {}
    iterations_used = int(budget_state.get("iterations_used", len(session.iteration_history)) or 0)
    solver_calls_used = int(budget_state.get("solver_calls_used", 0) or 0)
    retrieval_calls_used = int(budget_state.get("retrieval_calls_used", 0) or 0)
    failed_iterations_used = int(budget_state.get("failed_iterations_used", 0) or 0)
    recovery_attempts_used = int(
        budget_state.get(
            "recovery_attempts_used",
            len(
                [
                    item
                    for item in session.iteration_history
                    if isinstance(item.get("recovery_stage"), int) and int(item.get("recovery_stage", 0)) > 0
                ]
            ),
        )
        or 0
    )
    max_iterations = int(budget_config.get("max_iterations", iterations_used) or 0)
    max_solver_calls = int(budget_config.get("max_solver_calls", solver_calls_used) or 0)
    max_retrieval_calls = int(budget_config.get("max_retrieval_calls", retrieval_calls_used) or 0)
    max_recovery_attempts = int(
        budget_config.get(
            "max_recovery_attempts",
            max(2, int(budget_config.get("max_failed_iterations", 0) or 0) + int(budget_config.get("stagnation_window", 0) or 0)),
        )
        or 0
    )
    reward_trace: list[float | None] = []
    best_curve: list[float | None] = []
    best_so_far: float | None = None
    for item in session.iteration_history:
        score = item.get("score")
        reward_trace.append(float(score) if isinstance(score, (int, float)) else None)
        if isinstance(score, (int, float)):
            if best_so_far is None or float(score) > best_so_far:
                best_so_far = float(score)
        best_curve.append(best_so_far)
    initial_score = reward_trace[0] if reward_trace else None
    final_score = best_curve[-1] if best_curve else None
    improvement_delta = None
    if isinstance(initial_score, (int, float)) and isinstance(final_score, (int, float)):
        improvement_delta = float(final_score) - float(initial_score)

    action_ablation_trace: list[dict[str, Any]] = []
    prev_compiled: dict[str, Any] | None = None
    for idx, item in enumerate(session.iteration_history):
        compiled = item.get("compiled_action")
        if isinstance(compiled, dict):
            delta = classify_ablation_change(prev_compiled, compiled)
            action_ablation_trace.append(
                {
                    "iteration_index": idx,
                    "action_id": item.get("action_id"),
                    "delta": delta.to_dict(),
                }
            )
            prev_compiled = compiled
        else:
            action_ablation_trace.append(
                {"iteration_index": idx, "action_id": item.get("action_id"), "delta": {"changed_knobs": [], "category": "missing_compiled_action"}}
            )

    failure_taxonomy = classify_failure_taxonomy(
        status=session.status,
        termination_reason=session.termination_reason,
        blocked_state=session.blocked_state,
        iteration_trace=session.iteration_history,
    )
    llm_selected = 0
    fallback_selected = 0
    llm_ranked_candidates: list[dict[str, Any]] = []
    for item in session.iteration_history:
        arbitration = item.get("arbitration", {})
        if not isinstance(arbitration, dict):
            continue
        gate = arbitration.get("gate", {})
        proposal = arbitration.get("llm_proposal", {})
        details = arbitration.get("details", {})
        if isinstance(gate, dict):
            if bool(gate.get("via_fallback", False)):
                fallback_selected += 1
            else:
                llm_selected += 1
        if isinstance(proposal, dict):
            llm_ranked_candidates.append(
                {
                    "iteration_index": item.get("iteration_index"),
                    "llm_action_id": proposal.get("action_id"),
                    "llm_ranked_action_ids": list(proposal.get("ranked_action_ids", []))
                    if isinstance(proposal.get("ranked_action_ids"), list)
                    else [],
                    "combined_ranked": list(details.get("combined_ranked", []))
                    if isinstance(details, dict) and isinstance(details.get("combined_ranked"), list)
                    else [],
                }
            )

    best_iteration_index: int | None = None
    best_action_id: str | None = None
    best_action_family: str | None = None
    best_structure_artifact_path: str | None = None
    best_linkage: dict[str, Any] | None = None
    if isinstance(session.best_so_far, dict):
        idx = session.best_so_far.get("iteration_index")
        if isinstance(idx, int) and 0 <= idx < len(session.iteration_history):
            best_iteration_index = idx
            best_row = session.iteration_history[idx]
            best_action_id = str(best_row.get("action_id")) if best_row.get("action_id") is not None else None
            best_action_family = (
                str(best_row.get("action_family")) if best_row.get("action_family") is not None else None
            )
            run_reference = best_row.get("run_reference", {})
            if isinstance(run_reference, dict):
                path_val = run_reference.get("structure_artifact_path")
                if isinstance(path_val, str) and path_val:
                    best_structure_artifact_path = path_val
                best_linkage = {
                    "session_id": session.session_id,
                    "iteration_index": best_iteration_index,
                    "action_id": best_action_id,
                    "action_family": best_action_family,
                    "score": session.best_so_far.get("score"),
                    "pair_id": run_reference.get("pair_id"),
                    "guided_run_id": run_reference.get("guided_run_id"),
                    "baseline_run_id": run_reference.get("baseline_run_id"),
                    "structure_artifact_path": best_structure_artifact_path,
                }

    unique_action_ids = sorted(
        {
            str(item.get("action_id"))
            for item in session.iteration_history
            if isinstance(item.get("action_id"), str)
        }
    )
    unique_action_families = sorted(
        {
            str(item.get("action_family"))
            for item in session.iteration_history
            if isinstance(item.get("action_family"), str)
        }
    )
    unique_compiled_config_signatures = sorted(
        {
            str(sig)
            for sig in (_row_compiled_signature(item) for item in session.iteration_history)
            if isinstance(sig, str)
        }
    )
    unique_executable_signatures = sorted(
        {
            str(sig)
            for sig in (
                _row_executable_signature(item, query_text=str(session.task_spec.get("query_text", "")))
                for item in session.iteration_history
            )
            if isinstance(sig, str)
        }
    )
    unique_scores = sorted(
        {
            round(float(item.get("score")), 12)
            for item in session.iteration_history
            if isinstance(item.get("score"), (int, float))
        }
    )
    objective_audits = [_row_objective_audit(item) for item in session.iteration_history]
    unique_objective_totals = sorted(
        {
            round(float(audit.get("objective_total")), 12)
            for audit in objective_audits
            if isinstance(audit.get("objective_total"), (int, float))
        }
    )
    unique_objective_term_signatures = sorted(
        {
            str(audit.get("objective_terms_signature"))
            for audit in objective_audits
            if isinstance(audit.get("objective_terms_signature"), str)
        }
    )
    first_improvement_iteration = _first_improvement_iteration(session.iteration_history)
    flat_reason = _flatness_reason(
        unique_action_ids=len(unique_action_ids),
        unique_action_families=len(unique_action_families),
        unique_compiled_signatures=len(unique_compiled_config_signatures),
        unique_executable_signatures=len(unique_executable_signatures),
        unique_score_values=len(unique_scores),
    )
    iteration_effectiveness_trace = _iteration_effectiveness_trace(
        session.iteration_history,
        query_text=str(session.task_spec.get("query_text", "")),
    )
    objective_vs_structure_trace = _objective_vs_structure_trace(session.iteration_history)
    spp_exploration = _spp_exploration_summary(iteration_effectiveness_trace)
    structure_diagnostics = _structure_diversity_and_dominance(
        iteration_effectiveness_trace=iteration_effectiveness_trace,
        objective_vs_structure_trace=objective_vs_structure_trace,
        unique_objective_term_signatures=len(unique_objective_term_signatures),
        spp_exploration_summary=spp_exploration,
    )
    hypothesis_branch_summary = _hypothesis_branch_summary(
        iteration_effectiveness_trace=iteration_effectiveness_trace,
        objective_vs_structure_trace=objective_vs_structure_trace,
        hypothesis_state=session.hypothesis_state if isinstance(session.hypothesis_state, dict) else {},
    )
    regime_summary = _regime_level_summary(
        iteration_effectiveness_trace=iteration_effectiveness_trace,
        objective_vs_structure_trace=objective_vs_structure_trace,
    )
    backend_sensitivity_classification = classify_backend_sensitivity(
        unique_action_ids=len(unique_action_ids),
        unique_compiled_signatures=len(unique_compiled_config_signatures),
        unique_executable_signatures=len(unique_executable_signatures),
        unique_objective_totals=len(unique_objective_totals),
        unique_objective_term_signatures=len(unique_objective_term_signatures),
    )
    dimension_sensitivity = summarize_dimension_sensitivity(iteration_effectiveness_trace)
    best_remained_iteration_zero = (
        bool(session.iteration_history)
        and best_iteration_index == 0
        and first_improvement_iteration is None
    )
    recovery_rows = [
        item
        for item in session.iteration_history
        if isinstance(item.get("recovery_stage"), int) and int(item.get("recovery_stage", 0)) > 0
    ]
    recovery_regimes_tried = sorted(
        {
            str(item.get("recovery_regime"))
            for item in recovery_rows
            if isinstance(item.get("recovery_regime"), str) and str(item.get("recovery_regime")).strip()
        }
    )
    recovery_attempt_count = recovery_attempts_used
    first_feasible_iteration: int | None = None
    first_feasible_regime: str | None = None
    for row in session.iteration_history:
        idx = row.get("iteration_index")
        if not isinstance(idx, int):
            continue
        if bool(row.get("feasible", False)):
            first_feasible_iteration = idx
            regime = row.get("recovery_regime")
            first_feasible_regime = str(regime) if isinstance(regime, str) else None
            break
    stop_hook_invocations = (
        list(session.policy_state.get("stop_hook_invocations", []))
        if isinstance(session.policy_state.get("stop_hook_invocations"), list)
        else []
    )
    last_stop_hook = stop_hook_invocations[-1] if stop_hook_invocations else {}
    if not isinstance(last_stop_hook, dict):
        last_stop_hook = {}
    clarification_policy_effects = (
        list(session.policy_state.get("clarification_policy_effects", []))
        if isinstance(session.policy_state.get("clarification_policy_effects"), list)
        else []
    )
    clarification_answer_applied = bool(
        session.clarification_state.get("answer_applied", False)
    ) or any(
        isinstance(item, dict) and isinstance(item.get("effects"), dict) and bool(item.get("effects"))
        for item in clarification_policy_effects
    )
    clarification_policy_effects_payload = [
        dict(item)
        for item in clarification_policy_effects
        if isinstance(item, dict)
    ]
    controller_output_stats = (
        dict(session.policy_state.get("controller_output_stats", {}))
        if isinstance(session.policy_state.get("controller_output_stats"), dict)
        else {}
    )

    return {
        "schema_version": "optimization.report.v1",
        "session_id": session.session_id,
        "status": session.status,
        "termination_reason": session.termination_reason,
        "failure_taxonomy": failure_taxonomy,
        "iteration_trace": list(session.iteration_history),
        "iteration_count": len(session.iteration_history),
        "solver_call_count": solver_calls_used,
        "recovery_attempt_count": recovery_attempt_count,
        "budget_accounting": {
            "iteration_count": len(session.iteration_history),
            "iterations_used": iterations_used,
            "max_iterations": max_iterations,
            "remaining_iterations": max(0, max_iterations - iterations_used),
            "solver_call_count": solver_calls_used,
            "max_solver_calls": max_solver_calls,
            "remaining_solver_calls": max(0, max_solver_calls - solver_calls_used),
            "retrieval_call_count": retrieval_calls_used,
            "max_retrieval_calls": max_retrieval_calls,
            "remaining_retrieval_calls": max(0, max_retrieval_calls - retrieval_calls_used),
            "failed_iteration_count": failed_iterations_used,
            "max_failed_iterations": int(budget_config.get("max_failed_iterations", failed_iterations_used) or 0),
            "recovery_attempt_count": recovery_attempt_count,
            "max_recovery_attempts": max_recovery_attempts,
            "remaining_recovery_attempts": max(0, max_recovery_attempts - recovery_attempt_count),
        },
        "reward_trace": reward_trace,
        "best_so_far_curve": best_curve,
        "initial_score": initial_score,
        "final_best_score": final_score,
        "improvement_delta": improvement_delta,
        "action_ablation_trace": action_ablation_trace,
        "action_family_summary": summarize_action_families(session.iteration_history),
        "best_so_far": session.best_so_far,
        "best_iteration_index": best_iteration_index,
        "best_action_id": best_action_id,
        "best_action_family": best_action_family,
        "best_structure_artifact_path": best_structure_artifact_path,
        "best_structure_linkage": best_linkage,
        "clarification_defaults_used": list(session.clarification_state.get("defaults_used", [])),
        "clarification_deferred_questions": list(session.clarification_state.get("deferred_questions", [])),
        "clarification_assumptions_log": list(session.clarification_state.get("assumptions_log", [])),
        "recovery_regimes_tried": recovery_regimes_tried,
        "recovery_attempt_count": recovery_attempt_count,
        "first_feasible_iteration": first_feasible_iteration,
        "first_feasible_regime": first_feasible_regime,
        "stop_hook_invocations": stop_hook_invocations,
        "stop_hook_decision": last_stop_hook.get("decision"),
        "stop_hook_reason": last_stop_hook.get("reason"),
        "clarification_trigger_class": (
            session.clarification_state.get("clarification_trigger_class")
            if isinstance(session.clarification_state.get("clarification_trigger_class"), str)
            else last_stop_hook.get("trigger_class")
        ),
        "clarification_answer_applied": clarification_answer_applied,
        "clarification_policy_effects": clarification_policy_effects_payload,
        "controller_output_stats": controller_output_stats,
        "selection_metric_view": str(
            session.policy_state.get("selection_metric_view")
            if isinstance(session.policy_state.get("selection_metric_view"), str)
            else "objective_total"
        ),
        "llm_selection_summary": {
            "llm_selected_iterations": llm_selected,
            "fallback_selected_iterations": fallback_selected,
        },
        "llm_ranked_candidates": llm_ranked_candidates,
        "hypothesis_state": dict(session.hypothesis_state) if isinstance(session.hypothesis_state, dict) else {},
        "iteration_effectiveness_trace": iteration_effectiveness_trace,
        "objective_vs_structure_trace": objective_vs_structure_trace,
        "structure_diversity_summary": structure_diagnostics,
        "hypothesis_branch_summary": hypothesis_branch_summary,
        "regime_level_summary": regime_summary,
        "spp_exploration_summary": spp_exploration,
        "objective_audit_trace": objective_audits,
        "diagnostics": {
            "unique_action_ids": unique_action_ids,
            "unique_action_id_count": len(unique_action_ids),
            "unique_action_families": unique_action_families,
            "unique_action_family_count": len(unique_action_families),
            "unique_compiled_config_signatures": unique_compiled_config_signatures,
            "unique_compiled_config_signature_count": len(unique_compiled_config_signatures),
            "unique_executable_signatures": unique_executable_signatures,
            "unique_executable_signature_count": len(unique_executable_signatures),
            "unique_score_values": unique_scores,
            "unique_score_value_count": len(unique_scores),
            "unique_objective_total_values": unique_objective_totals,
            "unique_objective_total_value_count": len(unique_objective_totals),
            "unique_objective_term_signatures": unique_objective_term_signatures,
            "unique_objective_term_signature_count": len(unique_objective_term_signatures),
            "first_improvement_iteration": first_improvement_iteration,
            "best_remained_iteration_zero": best_remained_iteration_zero,
            "flat_objective_flag": flat_reason is not None,
            "likely_flatness_reason": flat_reason,
            "iteration_zero_remained_best": best_remained_iteration_zero,
            "backend_sensitivity_classification": backend_sensitivity_classification,
            "dimension_sensitivity_summary": dimension_sensitivity,
            "spp_exploration_summary": spp_exploration,
            "structure_diversity_summary": structure_diagnostics,
            "hypothesis_branch_summary": hypothesis_branch_summary,
            "regime_level_summary": regime_summary,
            "dominance_warning": structure_diagnostics.get("dominance_warning"),
            "dominance_recommendation": structure_diagnostics.get("dominance_recommendation"),
            "hypotheses_tried": list(hypothesis_branch_summary.get("hypotheses_tried", [])),
            "branch_switch_count": int(hypothesis_branch_summary.get("branch_switch_count", 0)),
            "best_hypothesis_id": hypothesis_branch_summary.get("best_hypothesis_id"),
            "selection_metric_view": str(
                session.policy_state.get("selection_metric_view")
                if isinstance(session.policy_state.get("selection_metric_view"), str)
                else "objective_total"
            ),
            "recovery_regimes_tried": recovery_regimes_tried,
            "recovery_attempt_count": recovery_attempt_count,
            "solver_call_count": solver_calls_used,
            "budget_accounting": {
                "iterations_used": iterations_used,
                "solver_calls_used": solver_calls_used,
                "retrieval_calls_used": retrieval_calls_used,
                "failed_iterations_used": failed_iterations_used,
                "recovery_attempts_used": recovery_attempt_count,
            },
            "first_feasible_iteration": first_feasible_iteration,
            "first_feasible_regime": first_feasible_regime,
            "stop_hook_invocation_count": len(stop_hook_invocations),
            "stop_hook_last_decision": last_stop_hook.get("decision"),
            "stop_hook_last_reason": last_stop_hook.get("reason"),
            "clarification_trigger_class": (
                session.clarification_state.get("clarification_trigger_class")
                if isinstance(session.clarification_state.get("clarification_trigger_class"), str)
                else last_stop_hook.get("trigger_class")
            ),
            "clarification_answer_applied": clarification_answer_applied,
            "clarification_policy_effects": clarification_policy_effects_payload,
            "controller_output_stats": controller_output_stats,
        },
    }


def regenerate_report_from_session_artifacts(session_path: Path) -> dict[str, Any]:
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    session = OptimizationSession.from_dict(payload)
    return build_optimization_report(session)


def write_optimization_report(session: OptimizationSession, session_dir: Path) -> Path:
    report = build_optimization_report(session)
    report_path = session_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path
