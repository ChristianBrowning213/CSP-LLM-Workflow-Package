from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.optimization.reporting import build_optimization_report
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession


def test_regime_level_structure_change_summary(workdir: Path) -> None:
    s1 = workdir / "r1.cif"
    s2 = workdir / "r2.cif"
    s1.write_text("data_r1\n_cell_length_a 4.0\n", encoding="utf-8")
    s2.write_text("data_r2\n_cell_length_a 5.0\n", encoding="utf-8")
    history = [
        {
            "iteration_index": 0,
            "action_id": "a1",
            "action_family": "guided_exploit",
            "score": 0.5,
            "reward": {"property_estimate": 0.5},
            "objective_audit": {"objective_total": 0.5, "objective_terms_signature": "o1"},
            "request_trace": {
                "effective_overrides": {
                    "weighting_profile": "balanced",
                    "structure_perturbation_profile": "minimal",
                },
                "guidance_structure_signature": "g1",
            },
            "run_reference": {"structure_artifact_path": str(s1)},
        },
        {
            "iteration_index": 1,
            "action_id": "a2",
            "action_family": "guided_explore",
            "score": 0.8,
            "reward": {"property_estimate": 0.8},
            "objective_audit": {"objective_total": 0.8, "objective_terms_signature": "o2"},
            "request_trace": {
                "effective_overrides": {
                    "weighting_profile": "experimental_extreme",
                    "structure_perturbation_profile": "template_shuffle",
                },
                "guidance_structure_signature": "g2",
            },
            "run_reference": {"structure_artifact_path": str(s2)},
        },
    ]
    session = OptimizationSession(
        session_id="sess-regime",
        status="STOPPED",
        task_spec={"query_text": "regime"},
        clarification_state={},
        optimization_plan=None,
        budget_state={},
        iteration_history=history,
        best_so_far={"iteration_index": 1, "score": 0.8},
        policy_state={},
    )
    report = build_optimization_report(session)
    regime = report["regime_level_summary"]
    assert "rows" in regime
    assert len(regime["rows"]) >= 2
    assert "experimental_extreme" in regime["unique_weighting_profiles"]
