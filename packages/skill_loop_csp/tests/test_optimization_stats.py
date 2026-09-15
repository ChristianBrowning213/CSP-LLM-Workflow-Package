from __future__ import annotations

from sok_llm_orchestrator.optimization.stats import summarize_action_families


def test_action_family_stats_summary() -> None:
    summary = summarize_action_families(
        [
            {"action_family": "guided_exploit", "score": 1.0, "feasible": True},
            {"action_family": "guided_exploit", "score": 2.0, "feasible": False},
            {"action_family": "cell_policy", "score": 0.5, "feasible": True},
        ]
    )
    assert summary["guided_exploit"]["count"] == 2
    assert summary["guided_exploit"]["feasible_count"] == 1
    assert summary["cell_policy"]["mean_reward"] == 0.5

