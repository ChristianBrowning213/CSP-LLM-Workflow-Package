from __future__ import annotations

from sok_llm_orchestrator.optimization.stop_hook import evaluate_stop_hook


def test_stop_hook_can_continue_without_asking_user() -> None:
    decision = evaluate_stop_hook(
        llm_client=None,
        context={
            "infeasible_streak": 2,
            "recovery_stage": 1,
            "recovery_regime": "symmetry_soften_feasibility",
            "recovery_attempt_count": 1,
            "recovery_exhausted": False,
            "remaining_iterations": 4,
            "hard_constraint_boundary_reached": False,
            "task_meaning_ambiguity": False,
            "stuck_reason": "repeated_infeasibility",
        },
        allow_user_clarification=True,
    )
    assert decision.decision in {"continue_autonomously", "continue_with_recovery_regime"}
    assert decision.decision != "ask_user_clarification"
