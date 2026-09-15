from __future__ import annotations

from sok_llm_orchestrator.optimization.bandit import EpsilonGreedyBandit
from sok_llm_orchestrator.optimization.best_result import promote_best_result
from sok_llm_orchestrator.optimization.reward_schema import RewardRecord
from sok_llm_orchestrator.optimization.scoring import score_reward


def test_feasible_better_objective_beats_feasible_worse() -> None:
    better = RewardRecord(action_id="a", action_family="f", primary_objective=0.8, feasibility=True)
    worse = RewardRecord(action_id="b", action_family="f", primary_objective=0.3, feasibility=True)
    assert score_reward(better) > score_reward(worse)


def test_infeasible_penalty_applies() -> None:
    feasible = RewardRecord(action_id="a", action_family="f", primary_objective=0.4, feasibility=True)
    infeasible = RewardRecord(action_id="b", action_family="f", primary_objective=0.9, feasibility=False)
    assert score_reward(feasible) > score_reward(infeasible)


def test_invalid_run_excluded_from_learning_updates() -> None:
    bandit = EpsilonGreedyBandit(epsilon=0.0, seed=0)
    valid = RewardRecord(action_id="a", action_family="f", primary_objective=0.5, feasibility=True, valid_for_learning=True)
    invalid = RewardRecord(action_id="a", action_family="f", primary_objective=1.0, feasibility=True, valid_for_learning=False)
    if valid.valid_for_learning:
        bandit.update(valid.action_id, score_reward(valid))
    if invalid.valid_for_learning:
        bandit.update(invalid.action_id, score_reward(invalid))
    state = bandit.to_dict()["arms"]["a"]
    assert state["pulls"] == 1
    assert abs(state["total_reward"] - score_reward(valid)) < 1e-12


def test_tie_behavior_is_deterministic() -> None:
    first, _ = promote_best_result(None, {"action_id": "a", "score": 0.7})
    second, improved = promote_best_result(first, {"action_id": "b", "score": 0.7})
    assert improved is False
    assert second["action_id"] == "a"


def test_novelty_placeholder_off_by_default() -> None:
    base = RewardRecord(action_id="a", action_family="f", primary_objective=0.5, feasibility=True, novelty=None)
    with_novelty = RewardRecord(action_id="b", action_family="f", primary_objective=0.5, feasibility=True, novelty=0.99)
    assert score_reward(base) == score_reward(with_novelty)
    assert score_reward(with_novelty, novelty_weight=0.5) > score_reward(with_novelty, novelty_weight=0.0)

