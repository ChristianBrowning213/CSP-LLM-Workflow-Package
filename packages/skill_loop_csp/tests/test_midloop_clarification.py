from __future__ import annotations

from sok_llm_orchestrator.optimization.midloop_clarification import evaluate_midloop_clarification


def test_midloop_clarification_on_stagnation() -> None:
    decision = evaluate_midloop_clarification(
        recent_iterations=[
            {"primary_objective": 0.5, "feasible": True},
            {"primary_objective": 0.5, "feasible": True},
            {"primary_objective": 0.5, "feasible": True},
        ],
        stagnation_window=3,
        max_repeated_infeasible=3,
    )
    assert decision.should_trigger is True
    assert decision.reason == "stagnation"


def test_midloop_clarification_on_repeated_infeasible() -> None:
    decision = evaluate_midloop_clarification(
        recent_iterations=[
            {"primary_objective": None, "feasible": False},
            {"primary_objective": None, "feasible": False},
            {"primary_objective": None, "feasible": False},
        ],
        stagnation_window=3,
        max_repeated_infeasible=2,
    )
    assert decision.should_trigger is True
    assert decision.reason == "repeated_infeasibility"

