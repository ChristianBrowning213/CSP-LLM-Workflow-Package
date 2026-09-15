from __future__ import annotations

from sok_llm_orchestrator.optimization.reporting import build_optimization_report
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession


def test_flatness_diagnostics_for_action_variation_without_score_gain() -> None:
    session = OptimizationSession(
        session_id="flat-s1",
        status="STOPPED",
        task_spec={"query_text": "TiO2 optimize high property x"},
        clarification_state={"ready": True},
        optimization_plan={"schema_version": "optimization.plan.v1"},
        budget_state={"config": {"max_iterations": 3}},
        iteration_history=[
            {
                "iteration_index": 0,
                "action_id": "guided_hybrid_balanced",
                "action_family": "guided_exploit",
                "compiled_config_signature": "cfg-a",
                "executable_signature": "exec-a",
                "score": 0.2,
                "primary_objective": 0.2,
                "best_updated": True,
            },
            {
                "iteration_index": 1,
                "action_id": "guided_property_push",
                "action_family": "retrieval_explore",
                "compiled_config_signature": "cfg-b",
                "executable_signature": "exec-b",
                "score": 0.2,
                "primary_objective": 0.2,
                "best_updated": False,
            },
        ],
        best_so_far={"score": 0.2, "iteration_index": 0, "action_id": "guided_hybrid_balanced"},
        termination_reason="budget_exhausted:max_iterations",
    )
    report = build_optimization_report(session)
    diagnostics = report["diagnostics"]
    assert diagnostics["flat_objective_flag"] is True
    assert diagnostics["unique_action_id_count"] == 2
    assert diagnostics["unique_compiled_config_signature_count"] == 2
    assert diagnostics["unique_score_value_count"] == 1
    assert diagnostics["first_improvement_iteration"] is None
    assert diagnostics["best_remained_iteration_zero"] is True
    assert diagnostics["likely_flatness_reason"] == "backend_objective_invariant_under_tested_actions"
