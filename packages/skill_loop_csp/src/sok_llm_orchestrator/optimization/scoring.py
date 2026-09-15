from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.optimization.reward_schema import RewardRecord


def score_reward(
    reward: RewardRecord,
    *,
    objective_direction: str = "maximize",
    novelty_weight: float = 0.0,
    infeasible_penalty: float = 1_000.0,
) -> float:
    objective = reward.primary_objective
    if objective is None:
        return -infeasible_penalty

    base = float(objective)
    if objective_direction == "minimize":
        base = -base
    if not reward.feasibility:
        base -= infeasible_penalty
    if reward.novelty is not None and novelty_weight != 0.0:
        base += novelty_weight * float(reward.novelty)
    return base


def score_reward_with_view(
    reward: RewardRecord,
    *,
    selection_metric_view: str = "objective_total",
    objective_audit: dict[str, Any] | None = None,
    request_trace: dict[str, Any] | None = None,
    infeasible_penalty: float = 1_000.0,
) -> tuple[float, dict[str, Any]]:
    view = str(selection_metric_view or "objective_total").strip().lower()
    objective_score = score_reward(
        reward,
        objective_direction="maximize",
        novelty_weight=0.0,
        infeasible_penalty=infeasible_penalty,
    )
    if view not in {"property_aware", "property_decomp_aware"}:
        return objective_score, {
            "selection_metric_view": "objective_total",
            "objective_score": objective_score,
            "property_score": reward.property_estimate if isinstance(reward.property_estimate, (int, float)) else None,
            "guidance_active": False,
            "spp_term_present": False,
            "spp_term": None,
            "composite_score": objective_score,
        }

    property_score = (
        float(reward.property_estimate)
        if isinstance(reward.property_estimate, (int, float))
        else float(reward.primary_objective)
        if isinstance(reward.primary_objective, (int, float))
        else -infeasible_penalty
    )
    req = request_trace if isinstance(request_trace, dict) else {}
    guidance_ids = req.get("request_guidance_ids", [])
    guidance_active = isinstance(guidance_ids, list) and any(isinstance(item, str) and item for item in guidance_ids)
    audit = objective_audit if isinstance(objective_audit, dict) else {}
    spp_term = audit.get("spp_term")
    spp_term_num = float(spp_term) if isinstance(spp_term, (int, float)) else None
    spp_term_present = spp_term_num is not None
    objective_total = (
        float(audit.get("objective_total"))
        if isinstance(audit.get("objective_total"), (int, float))
        else float(reward.primary_objective)
        if isinstance(reward.primary_objective, (int, float))
        else None
    )
    objective_terms = audit.get("objective_terms", [])
    objective_term_count = (
        sum(1 for term in objective_terms if isinstance(term, dict))
        if isinstance(objective_terms, list)
        else 0
    )
    guidance_terms = audit.get("guidance_terms", [])
    guidance_term_count = (
        sum(1 for term in guidance_terms if isinstance(term, dict))
        if isinstance(guidance_terms, list)
        else 0
    )

    composite = property_score
    if guidance_active:
        composite += 0.05
    if spp_term_present:
        composite += 0.05
        composite += min(0.05, abs(float(spp_term_num)) * 0.005)
    if isinstance(objective_total, (int, float)):
        composite += 0.001 * float(objective_total)
    if view == "property_decomp_aware":
        # In this view, keep property as primary but explicitly favor
        # non-trivial decomposition/guidance structure when present.
        if objective_term_count > 1:
            composite += min(0.04, 0.01 * float(objective_term_count - 1))
        if guidance_term_count > 0:
            composite += min(0.03, 0.01 * float(guidance_term_count))
        if spp_term_present:
            composite += min(0.05, abs(float(spp_term_num)) * 0.01)
        if isinstance(objective_total, (int, float)):
            # keep total objective as small tie-break signal.
            composite += 0.0005 * float(objective_total)
    if not reward.feasibility:
        composite -= infeasible_penalty

    return composite, {
        "selection_metric_view": view,
        "objective_score": objective_score,
        "property_score": property_score,
        "guidance_active": bool(guidance_active),
        "spp_term_present": bool(spp_term_present),
        "spp_term": spp_term_num,
        "objective_total": objective_total,
        "objective_term_count": objective_term_count,
        "guidance_term_count": guidance_term_count,
        "composite_score": composite,
    }
