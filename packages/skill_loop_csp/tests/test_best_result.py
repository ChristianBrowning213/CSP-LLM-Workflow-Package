from __future__ import annotations

from sok_llm_orchestrator.optimization.best_result import promote_best_result


def test_best_result_promotes_higher_score() -> None:
    best, improved = promote_best_result(None, {"score": 0.1, "action_id": "a"})
    assert improved is True
    best2, improved2 = promote_best_result(best, {"score": 0.2, "action_id": "b"})
    assert improved2 is True
    assert best2["action_id"] == "b"

