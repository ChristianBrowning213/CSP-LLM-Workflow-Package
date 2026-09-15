from __future__ import annotations

from sok_llm_orchestrator.optimization.stop_hook import evaluate_stop_hook


def test_stop_hook_question_contains_evidence_summary() -> None:
    decision = evaluate_stop_hook(
        llm_client=None,
        context={
            "infeasible_streak": 6,
            "recovery_stage": 3,
            "recovery_regime": "strong_structure_perturbation",
            "recovery_regimes_tried": [
                "symmetry_soften_feasibility",
                "broadened_retrieval_and_templates",
                "strong_structure_perturbation",
            ],
            "recovery_attempt_count": 9,
            "recovery_exhausted": True,
            "remaining_iterations": 3,
            "hard_constraint_boundary_reached": False,
            "task_meaning_ambiguity": False,
            "stuck_reason": "repeated_infeasibility",
        },
        allow_user_clarification=True,
    )
    assert decision.decision == "ask_user_clarification"
    assert isinstance(decision.question, str) and decision.question
    assert "I tried recovery regimes" in decision.question
    assert "infeasible_streak=6" in decision.evidence_summary
