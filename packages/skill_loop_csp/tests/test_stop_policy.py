from __future__ import annotations

from sok_llm_orchestrator.optimization.stop_policy import evaluate_stop_policy


def test_stop_policy_budget_exhausted() -> None:
    dec = evaluate_stop_policy(
        budget_exhausted_reason="budget_exhausted:max_iterations",
        stuck_reason=None,
        target_threshold=None,
        best_score=None,
    )
    assert dec.stop is True
    assert dec.reason == "budget_exhausted:max_iterations"

