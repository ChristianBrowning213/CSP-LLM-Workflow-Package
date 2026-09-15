from __future__ import annotations

from sok_llm_orchestrator.optimization.failure_taxonomy import classify_failure_taxonomy


def test_failure_taxonomy_repeated_infeasibility() -> None:
    out = classify_failure_taxonomy(
        status="WAITING_CLARIFICATION",
        termination_reason="midloop_clarification_required",
        blocked_state={"reason": "repeated_infeasibility"},
        iteration_trace=[],
    )
    assert out["primary_category"] == "repeated_infeasibility"
    assert "blocked-clarification-needed" in out["categories"]


def test_failure_taxonomy_stagnation() -> None:
    out = classify_failure_taxonomy(
        status="WAITING_CLARIFICATION",
        termination_reason="midloop_clarification_required",
        blocked_state={"reason": "stagnation"},
        iteration_trace=[],
    )
    assert out["primary_category"] == "stagnation"
    assert out["recommended_next_step"] == "increase_exploration_or_request_midloop_guidance"


def test_failure_taxonomy_invalid_action_rejection() -> None:
    out = classify_failure_taxonomy(
        status="STOPPED",
        termination_reason="budget_exhausted:max_iterations",
        blocked_state=None,
        iteration_trace=[
            {"arbitration": {"gate": {"via_fallback": True}, "llm_proposal": {"action_id": "invalid"}}}
        ],
    )
    assert "invalid-action rejection" in out["categories"]


def test_failure_taxonomy_budget_exhaustion() -> None:
    out = classify_failure_taxonomy(
        status="STOPPED",
        termination_reason="budget_exhausted:max_iterations",
        blocked_state=None,
        iteration_trace=[],
    )
    assert out["primary_category"] == "budget_exhaustion"


def test_failure_taxonomy_blocked_clarification_needed() -> None:
    out = classify_failure_taxonomy(
        status="WAITING_CLARIFICATION",
        termination_reason="midloop_clarification_required",
        blocked_state=None,
        iteration_trace=[],
    )
    assert out["primary_category"] == "blocked-clarification-needed"


def test_failure_taxonomy_oscillation() -> None:
    out = classify_failure_taxonomy(
        status="STOPPED",
        termination_reason="budget_exhausted:max_iterations",
        blocked_state=None,
        iteration_trace=[
            {"action_family": "A"},
            {"action_family": "B"},
            {"action_family": "A"},
            {"action_family": "B"},
        ],
    )
    assert "oscillation" in out["categories"]

