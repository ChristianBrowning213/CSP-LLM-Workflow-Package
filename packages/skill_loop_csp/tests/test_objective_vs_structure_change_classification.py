from __future__ import annotations

from sok_llm_orchestrator.optimization.reporting import build_optimization_report
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession


def test_objective_vs_structure_change_classification(workdir) -> None:  # type: ignore[no-untyped-def]
    same = workdir / "same.cif"
    chg1 = workdir / "chg1.cif"
    chg2 = workdir / "chg2.cif"
    same.write_text("data_same\n_cell_length_a 4.0\n", encoding="utf-8")
    chg1.write_text("data_chg1\n_cell_length_a 5.0\n", encoding="utf-8")
    chg2.write_text("data_chg2\n_cell_length_a 6.0\n", encoding="utf-8")
    history = [
        {
            "iteration_index": 0,
            "action_id": "baseline_control",
            "action_family": "baseline_control",
            "score": 0.2,
            "primary_objective": -1.53,
            "reward": {"property_estimate": 0.60},
            "objective_audit": {"objective_total": -1.53, "objective_terms_signature": "sig-a"},
            "request_trace": {"guidance_structure_signature": "g-a"},
            "run_reference": {"structure_artifact_path": str(same)},
        },
        {
            "iteration_index": 1,
            "action_id": "guided_hybrid_balanced",
            "action_family": "guided_exploit",
            "score": 0.21,
            "primary_objective": -1.52,
            "reward": {"property_estimate": 0.60},
            "objective_audit": {"objective_total": -1.52, "objective_terms_signature": "sig-b"},
            "request_trace": {"guidance_structure_signature": "g-b"},
            "run_reference": {"structure_artifact_path": str(same)},
        },
        {
            "iteration_index": 2,
            "action_id": "guided_payload_probe",
            "action_family": "guided_explore",
            "score": 0.22,
            "primary_objective": -1.52,
            "reward": {"property_estimate": 0.60},
            "objective_audit": {"objective_total": -1.52, "objective_terms_signature": "sig-b"},
            "request_trace": {"guidance_structure_signature": "g-b"},
            "run_reference": {"structure_artifact_path": str(chg1)},
        },
        {
            "iteration_index": 3,
            "action_id": "guided_property_push",
            "action_family": "guided_exploit",
            "score": 0.30,
            "primary_objective": -1.50,
            "reward": {"property_estimate": 0.75},
            "objective_audit": {"objective_total": -1.50, "objective_terms_signature": "sig-c"},
            "request_trace": {"guidance_structure_signature": "g-c"},
            "run_reference": {"structure_artifact_path": str(chg2)},
        },
    ]
    session = OptimizationSession(
        session_id="sess-objective-vs-structure",
        status="STOPPED",
        task_spec={"query_text": "test"},
        clarification_state={},
        optimization_plan=None,
        budget_state={},
        iteration_history=history,
        best_so_far={"iteration_index": 3, "score": 0.30},
        policy_state={},
    )
    report = build_optimization_report(session)
    trace = [item["classification"] for item in report["objective_vs_structure_trace"]]
    assert trace[0] == "initial"
    assert "objective_changed_structure_unchanged" in trace
    assert "structure_changed_no_property_gain" in trace
    assert "structure_changed_property_gain" in trace
