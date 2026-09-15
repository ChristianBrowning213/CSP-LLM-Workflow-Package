from __future__ import annotations

from sok_llm_orchestrator.optimization.bandit import EpsilonGreedyBandit


def test_bandit_updates_reward_stats() -> None:
    bandit = EpsilonGreedyBandit(epsilon=0.0, seed=0)
    choice, _ = bandit.select(["a", "b"])
    assert choice in {"a", "b"}
    bandit.update("a", 1.0)
    ranked = bandit.rank(["a", "b"])
    assert ranked[0] == "a"

