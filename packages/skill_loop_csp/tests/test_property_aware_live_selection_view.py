from __future__ import annotations

from sok_llm_orchestrator.optimization.reward_schema import RewardRecord
from sok_llm_orchestrator.optimization.scoring import score_reward_with_view


def test_property_aware_selection_prefers_guided_property_signal() -> None:
    baseline = RewardRecord(
        action_id="baseline_control",
        action_family="baseline_control",
        primary_objective=-1.53,
        feasibility=True,
        property_estimate=0.61,
    )
    guided = RewardRecord(
        action_id="guided_property_push",
        action_family="guided_exploit",
        primary_objective=-1.53,
        feasibility=True,
        property_estimate=0.78,
    )

    baseline_score, baseline_components = score_reward_with_view(
        baseline,
        selection_metric_view="property_aware",
        objective_audit={
            "objective_total": -1.53,
            "spp_term": None,
        },
        request_trace={"request_guidance_ids": []},
    )
    guided_score, guided_components = score_reward_with_view(
        guided,
        selection_metric_view="property_aware",
        objective_audit={
            "objective_total": -1.53,
            "spp_term": -4.36,
        },
        request_trace={"request_guidance_ids": ["objective.energy_spp"]},
    )

    assert guided_score > baseline_score
    assert bool(guided_components["guidance_active"])
    assert bool(guided_components["spp_term_present"])


def test_objective_total_view_ignores_property_delta_when_objective_is_flat() -> None:
    reward = RewardRecord(
        action_id="guided_property_push",
        action_family="guided_exploit",
        primary_objective=-1.53,
        feasibility=True,
        property_estimate=0.78,
    )
    score, components = score_reward_with_view(
        reward,
        selection_metric_view="objective_total",
        objective_audit={"objective_total": -1.53, "spp_term": -4.36},
        request_trace={"request_guidance_ids": ["objective.energy_spp"]},
    )
    assert components["selection_metric_view"] == "objective_total"
    assert float(score) == -1.53

