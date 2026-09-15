from __future__ import annotations

from sok_llm_orchestrator.optimization.reporting import build_optimization_report
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession


def test_base_weight_dominance_warning_triggered(workdir) -> None:  # type: ignore[no-untyped-def]
    structure = workdir / "same.cif"
    structure.write_text("data_same\n_cell_length_a 4.0\n", encoding="utf-8")
    history = [
        {
            "iteration_index": 0,
            "action_id": "guided_hybrid_balanced",
            "action_family": "guided_exploit",
            "score": 0.3,
            "primary_objective": -1.53,
            "reward": {"property_estimate": 0.61},
            "objective_audit": {"objective_total": -1.53, "objective_terms_signature": "obj-0"},
            "request_trace": {
                "guidance_structure_signature": "guide-0",
                "builder_input_trace": {"builder_inputs": {"guidance_payload": {"lambda_override": 0.4}}},
            },
            "run_reference": {"structure_artifact_path": str(structure)},
        },
        {
            "iteration_index": 1,
            "action_id": "guided_property_push",
            "action_family": "guided_exploit",
            "score": 0.31,
            "primary_objective": -1.53,
            "reward": {"property_estimate": 0.61},
            "objective_audit": {"objective_total": -1.53, "objective_terms_signature": "obj-1"},
            "request_trace": {
                "guidance_structure_signature": "guide-1",
                "builder_input_trace": {"builder_inputs": {"guidance_payload": {"lambda_override": 1.2}}},
            },
            "run_reference": {"structure_artifact_path": str(structure)},
        },
    ]
    session = OptimizationSession(
        session_id="sess-dominance",
        status="STOPPED",
        task_spec={"query_text": "dominance check"},
        clarification_state={},
        optimization_plan=None,
        budget_state={},
        iteration_history=history,
        best_so_far={"iteration_index": 1, "score": 0.31},
        policy_state={},
    )
    report = build_optimization_report(session)
    diag = report["diagnostics"]["structure_diversity_summary"]
    assert bool(diag["dominance_warning"]) is True
    assert str(diag["dominance_recommendation"]) == "likely_base_weight_or_constraint_dominance"
