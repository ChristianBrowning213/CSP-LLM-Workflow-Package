from __future__ import annotations

from sok_llm_orchestrator.optimization.action_schema import OptimizationAction, validate_optimization_action


def test_action_schema_valid() -> None:
    action = OptimizationAction(
        action_id="a",
        action_family="guided_exploit",
        retrieval_policy="hybrid",
        corpus_strategy="top_k",
        spp_calibration_mode="balanced",
        qlip_guidance_mode="guidance_only",
        cell_selection_policy="retrieval_informed",
        rationale="r",
        expected_risk_reward={"risk": "medium", "reward": "medium"},
    )
    validate_optimization_action(action.to_dict())

