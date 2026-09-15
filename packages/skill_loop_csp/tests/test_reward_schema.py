from __future__ import annotations

from sok_llm_orchestrator.optimization.reward_schema import RewardRecord, validate_reward_record


def test_reward_schema_valid() -> None:
    reward = RewardRecord(
        action_id="guided_hybrid_balanced",
        action_family="guided_exploit",
        primary_objective=0.5,
        feasibility=True,
        solver_stability=1.0,
    )
    validate_reward_record(reward.to_dict())

