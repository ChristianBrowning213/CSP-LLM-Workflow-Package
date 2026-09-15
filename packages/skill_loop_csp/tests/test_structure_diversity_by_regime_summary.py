from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.optimization.reporting import build_optimization_report
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession


def test_structure_diversity_by_regime_summary(workdir: Path) -> None:
    s1 = workdir / "regime_diversity" / "a.cif"
    s2 = workdir / "regime_diversity" / "b.cif"
    s3 = workdir / "regime_diversity" / "c.cif"
    s1.parent.mkdir(parents=True, exist_ok=True)
    s1.write_text("data_a\n_cell_length_a 4.0\n", encoding="utf-8")
    s2.write_text("data_b\n_cell_length_a 5.1\n", encoding="utf-8")
    s3.write_text("data_c\n_cell_length_a 4.0\n", encoding="utf-8")
    history = [
        {
            "iteration_index": 0,
            "action_id": "guided_extreme_structure_probe",
            "action_family": "guided_explore",
            "score": 0.4,
            "reward": {"property_estimate": 0.4},
            "objective_audit": {"objective_total": 0.4, "objective_terms_signature": "o-a"},
            "request_trace": {
                "effective_overrides": {
                    "weighting_profile": "experimental_extreme",
                    "structure_perturbation_profile": "template_shuffle",
                    "template_seed_profile": "ordering_bias",
                    "lattice_candidate_profile": "multibasin",
                    "symmetry_relaxation_profile": "relaxed",
                    "ordering_perturbation_profile": "cation_swap_bias",
                },
                "guidance_structure_signature": "g-a",
            },
            "run_reference": {"structure_artifact_path": str(s1)},
        },
        {
            "iteration_index": 1,
            "action_id": "guided_extreme_structure_probe",
            "action_family": "guided_explore",
            "score": 0.6,
            "reward": {"property_estimate": 0.6},
            "objective_audit": {"objective_total": 0.6, "objective_terms_signature": "o-b"},
            "request_trace": {
                "effective_overrides": {
                    "weighting_profile": "experimental_extreme",
                    "structure_perturbation_profile": "template_shuffle",
                    "template_seed_profile": "ordering_bias",
                    "lattice_candidate_profile": "multibasin",
                    "symmetry_relaxation_profile": "relaxed",
                    "ordering_perturbation_profile": "cation_swap_bias",
                },
                "guidance_structure_signature": "g-b",
            },
            "run_reference": {"structure_artifact_path": str(s2)},
        },
        {
            "iteration_index": 2,
            "action_id": "guided_payload_probe",
            "action_family": "guided_explore",
            "score": 0.2,
            "reward": {"property_estimate": 0.2},
            "objective_audit": {"objective_total": 0.2, "objective_terms_signature": "o-c"},
            "request_trace": {
                "effective_overrides": {
                    "weighting_profile": "base_dominant",
                    "structure_perturbation_profile": "minimal",
                    "template_seed_profile": "canonical",
                    "lattice_candidate_profile": "narrow",
                    "symmetry_relaxation_profile": "strict",
                    "ordering_perturbation_profile": "none",
                },
                "guidance_structure_signature": "g-c",
            },
            "run_reference": {"structure_artifact_path": str(s3)},
        },
    ]
    session = OptimizationSession(
        session_id="sess-regime-diversity",
        status="STOPPED",
        task_spec={"query_text": "regime diversity"},
        clarification_state={},
        optimization_plan=None,
        budget_state={},
        iteration_history=history,
        best_so_far={"iteration_index": 1, "score": 0.6},
        policy_state={},
    )
    report = build_optimization_report(session)
    regime = report["regime_level_summary"]
    by_regime = regime["unique_structure_signature_count_by_regime"]
    assert by_regime
    assert any(int(v) >= 1 for v in by_regime.values())
    assert isinstance(regime.get("structure_change_rate_by_regime"), dict)
    assert isinstance(regime.get("property_gain_by_regime"), dict)
    assert isinstance(regime.get("dominance_warning_by_regime"), dict)
    assert isinstance(regime.get("recommended_structure_moving_regimes"), list)
