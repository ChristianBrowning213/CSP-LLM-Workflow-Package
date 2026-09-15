from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.optimization.reporting import build_optimization_report
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession


def test_dominance_warning_reduction_by_regime(workdir: Path) -> None:
    a1 = workdir / "dominance_regime" / "a1.cif"
    a2 = workdir / "dominance_regime" / "a2.cif"
    b1 = workdir / "dominance_regime" / "b1.cif"
    b2 = workdir / "dominance_regime" / "b2.cif"
    a1.parent.mkdir(parents=True, exist_ok=True)
    a1.write_text("data_a\n_cell_length_a 4.0\n", encoding="utf-8")
    a2.write_text("data_a\n_cell_length_a 4.0\n", encoding="utf-8")
    b1.write_text("data_b1\n_cell_length_a 5.0\n", encoding="utf-8")
    b2.write_text("data_b2\n_cell_length_a 5.4\n", encoding="utf-8")
    weak = {
        "weighting_profile": "base_dominant",
        "structure_perturbation_profile": "minimal",
        "template_seed_profile": "canonical",
        "lattice_candidate_profile": "narrow",
        "symmetry_relaxation_profile": "strict",
        "ordering_perturbation_profile": "none",
    }
    moving = {
        "weighting_profile": "experimental_extreme",
        "structure_perturbation_profile": "template_shuffle",
        "template_seed_profile": "ordering_bias",
        "lattice_candidate_profile": "multibasin",
        "symmetry_relaxation_profile": "relaxed",
        "ordering_perturbation_profile": "cation_swap_bias",
    }
    history = [
        {
            "iteration_index": 0,
            "action_id": "weak-a",
            "action_family": "guided_explore",
            "score": 0.1,
            "reward": {"property_estimate": 0.61},
            "objective_audit": {"objective_total": -1.53, "objective_terms_signature": "w0"},
            "request_trace": {"effective_overrides": weak, "guidance_structure_signature": "gw0"},
            "run_reference": {"structure_artifact_path": str(a1)},
        },
        {
            "iteration_index": 1,
            "action_id": "weak-b",
            "action_family": "guided_explore",
            "score": 0.1,
            "reward": {"property_estimate": 0.61},
            "objective_audit": {"objective_total": -1.53, "objective_terms_signature": "w1"},
            "request_trace": {"effective_overrides": weak, "guidance_structure_signature": "gw1"},
            "run_reference": {"structure_artifact_path": str(a2)},
        },
        {
            "iteration_index": 2,
            "action_id": "move-a",
            "action_family": "guided_explore",
            "score": 0.2,
            "reward": {"property_estimate": 0.72},
            "objective_audit": {"objective_total": -1.53, "objective_terms_signature": "m0"},
            "request_trace": {"effective_overrides": moving, "guidance_structure_signature": "gm0"},
            "run_reference": {"structure_artifact_path": str(b1)},
        },
        {
            "iteration_index": 3,
            "action_id": "move-b",
            "action_family": "guided_explore",
            "score": 0.25,
            "reward": {"property_estimate": 0.74},
            "objective_audit": {"objective_total": -1.53, "objective_terms_signature": "m1"},
            "request_trace": {"effective_overrides": moving, "guidance_structure_signature": "gm1"},
            "run_reference": {"structure_artifact_path": str(b2)},
        },
    ]
    session = OptimizationSession(
        session_id="sess-dominance-regime",
        status="STOPPED",
        task_spec={"query_text": "dominance by regime"},
        clarification_state={},
        optimization_plan=None,
        budget_state={},
        iteration_history=history,
        best_so_far={"iteration_index": 3, "score": 0.25},
        policy_state={},
    )
    report = build_optimization_report(session)
    regime = report["regime_level_summary"]
    rows = regime.get("rows", [])
    assert isinstance(rows, list) and rows
    weak_row = next(row for row in rows if row.get("weighting_profile") == "base_dominant")
    move_row = next(row for row in rows if row.get("weighting_profile") == "experimental_extreme")
    assert float(move_row.get("structure_change_rate", 0.0)) > 0.0
    assert float(move_row.get("dominance_warning_rate", 1.0)) <= float(weak_row.get("dominance_warning_rate", 1.0))
    recommended = list(regime.get("recommended_structure_moving_regimes", []))
    assert recommended
    assert str(move_row.get("regime_id")) in recommended
