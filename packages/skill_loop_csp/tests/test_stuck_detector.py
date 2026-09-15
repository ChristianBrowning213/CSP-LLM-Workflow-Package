from __future__ import annotations

from sok_llm_orchestrator.optimization.stuck_detector import detect_stuck


def test_stuck_detector_stagnation() -> None:
    stuck = detect_stuck(
        [
            {"primary_objective": 0.1, "feasible": True},
            {"primary_objective": 0.1, "feasible": True},
            {"primary_objective": 0.1, "feasible": True},
        ],
        stagnation_window=3,
    )
    assert stuck.stuck is True
    assert stuck.reason == "stagnation"

