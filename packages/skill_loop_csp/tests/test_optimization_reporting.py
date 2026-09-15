from __future__ import annotations

from sok_llm_orchestrator.optimization.reporting import build_optimization_report
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession


def test_optimization_report_has_curves_and_trace() -> None:
    session = OptimizationSession(
        session_id="s1",
        status="STOPPED",
        task_spec={"query_text": "TiO2"},
        clarification_state={"ready": True},
        optimization_plan={"schema_version": "optimization.plan.v1"},
        budget_state={
            "config": {
                "max_iterations": 3,
                "max_solver_calls": 8,
                "max_retrieval_calls": 7,
                "max_failed_iterations": 2,
                "max_recovery_attempts": 4,
                "stagnation_window": 2,
            },
            "iterations_used": 2,
            "solver_calls_used": 4,
            "retrieval_calls_used": 3,
            "failed_iterations_used": 1,
            "recovery_attempts_used": 1,
        },
        iteration_history=[
            {"iteration_index": 0, "action_family": "f1", "score": 0.1},
            {"iteration_index": 1, "action_family": "f1", "score": 0.2},
        ],
        best_so_far={"score": 0.2},
        termination_reason="budget_exhausted:max_iterations",
    )
    report = build_optimization_report(session)
    assert report["schema_version"] == "optimization.report.v1"
    assert report["reward_trace"] == [0.1, 0.2]
    assert report["best_so_far_curve"][-1] == 0.2
    assert report["solver_call_count"] == 4
    assert report["recovery_attempt_count"] == 1
    assert report["budget_accounting"]["iterations_used"] == 2
    assert report["budget_accounting"]["remaining_solver_calls"] == 4
    assert report["budget_accounting"]["remaining_recovery_attempts"] == 3
