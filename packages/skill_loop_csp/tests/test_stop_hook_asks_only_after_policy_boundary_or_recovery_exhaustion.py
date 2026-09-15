from __future__ import annotations

from sok_llm_orchestrator.optimization.stop_hook import evaluate_stop_hook


def test_stop_hook_asks_only_after_policy_boundary_or_recovery_exhaustion() -> None:
    normal = evaluate_stop_hook(
        llm_client=None,
        context={
            "infeasible_streak": 1,
            "recovery_stage": 1,
            "recovery_attempt_count": 1,
            "max_recovery_attempts": 3,
            "recovery_exhausted": False,
            "remaining_iterations": 4,
            "remaining_solver_calls": 6,
            "remaining_recovery_attempts": 2,
            "hard_constraint_boundary_reached": False,
            "task_meaning_ambiguity": False,
            "stuck_reason": "repeated_infeasibility",
        },
        allow_user_clarification=True,
    )
    assert normal.decision != "ask_user_clarification"

    boundary = evaluate_stop_hook(
        llm_client=None,
        context={
            "infeasible_streak": 4,
            "recovery_stage": 2,
            "recovery_attempt_count": 3,
            "max_recovery_attempts": 4,
            "recovery_exhausted": False,
            "remaining_iterations": 3,
            "remaining_solver_calls": 4,
            "remaining_recovery_attempts": 1,
            "hard_constraint_boundary_reached": True,
            "task_meaning_ambiguity": False,
            "stuck_reason": "repeated_infeasibility",
        },
        allow_user_clarification=True,
    )
    assert boundary.decision == "ask_user_clarification"

    exhausted = evaluate_stop_hook(
        llm_client=None,
        context={
            "infeasible_streak": 5,
            "recovery_stage": 3,
            "recovery_attempt_count": 8,
            "max_recovery_attempts": 8,
            "recovery_exhausted": True,
            "remaining_iterations": 2,
            "remaining_solver_calls": 2,
            "remaining_recovery_attempts": 0,
            "hard_constraint_boundary_reached": False,
            "task_meaning_ambiguity": False,
            "stuck_reason": "repeated_infeasibility",
        },
        allow_user_clarification=True,
    )
    assert exhausted.decision == "ask_user_clarification"
    assert "remaining_recovery_attempts=0" in exhausted.evidence_summary
    assert "max_recovery_attempts=8" in exhausted.evidence_summary
