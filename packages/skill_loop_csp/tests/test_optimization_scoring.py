from __future__ import annotations

from sok_llm_orchestrator.optimization.reward_schema import RewardRecord
from sok_llm_orchestrator.optimization.scoring import score_reward


def test_scoring_primary_objective_only() -> None:
    reward = RewardRecord(
        action_id="a",
        action_family="f",
        primary_objective=0.8,
        feasibility=True,
    )
    assert score_reward(reward) == 0.8


def test_scoring_penalizes_infeasible() -> None:
    reward = RewardRecord(
        action_id="a",
        action_family="f",
        primary_objective=0.8,
        feasibility=False,
    )
    assert score_reward(reward) < 0.0

