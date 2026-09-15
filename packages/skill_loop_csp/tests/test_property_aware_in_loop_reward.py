from __future__ import annotations

from sok_llm_orchestrator.optimization.reward_schema import RewardRecord
from sok_llm_orchestrator.optimization.scoring import score_reward_with_view


def test_property_decomp_aware_prefers_decomposition_rich_guided_outcome() -> None:
    base = RewardRecord(
        action_id="guided_hybrid_balanced",
        action_family="guided_exploit",
        primary_objective=-1.53,
        feasibility=True,
        property_estimate=0.78,
    )
    richer = RewardRecord(
        action_id="guided_property_push",
        action_family="guided_exploit",
        primary_objective=-1.53,
        feasibility=True,
        property_estimate=0.78,
    )
    base_score, _ = score_reward_with_view(
        base,
        selection_metric_view="property_decomp_aware",
        objective_audit={
            "objective_total": -1.53,
            "objective_terms": [{"term": "baseline", "value": -1.53}],
            "guidance_terms": [],
            "spp_term": None,
        },
        request_trace={"request_guidance_ids": []},
    )
    richer_score, richer_components = score_reward_with_view(
        richer,
        selection_metric_view="property_decomp_aware",
        objective_audit={
            "objective_total": -1.53,
            "objective_terms": [
                {"term": "baseline", "value": -1.53},
                {"term": "spp", "value": -0.2},
            ],
            "guidance_terms": [{"term": "objective.energy_spp", "value": -0.2}],
            "spp_term": -0.2,
        },
        request_trace={"request_guidance_ids": ["objective.energy_spp"]},
    )
    assert richer_score > base_score
    assert richer_components["selection_metric_view"] == "property_decomp_aware"
    assert int(richer_components["objective_term_count"]) >= 2


def test_property_decomp_aware_still_penalizes_infeasible() -> None:
    reward = RewardRecord(
        action_id="guided_property_push",
        action_family="guided_exploit",
        primary_objective=-1.53,
        feasibility=False,
        property_estimate=0.9,
    )
    score, _ = score_reward_with_view(
        reward,
        selection_metric_view="property_decomp_aware",
        objective_audit={"objective_total": -1.53, "objective_terms": [], "guidance_terms": [], "spp_term": None},
        request_trace={"request_guidance_ids": ["objective.energy_spp"]},
    )
    assert float(score) < -100.0
