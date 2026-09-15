from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.experiments.first_crystal import build_first_crystal_summary


def test_guidance_usage_summary_aggregate_fields() -> None:
    summary = build_first_crystal_summary(
        experiment_id="exp-1",
        case_file=Path("docs/branch/benchmarks/first_crystal_cases.json"),
        rows=[
            {
                "improvement_delta": 0.0,
                "analysis_metric_delta": 0.1,
                "best_structure_artifact_path": "a.cif",
                "flat_objective_flag": True,
                "best_remained_iteration_zero": False,
                "guidance_active": True,
                "spp_term_present_count": 1,
                "property_x_improved": True,
                "objective_total_improved": False,
                "analysis_metric_improved": True,
                "total_flat_property_gain": True,
            },
            {
                "improvement_delta": 0.0,
                "analysis_metric_delta": 0.0,
                "best_structure_artifact_path": "b.cif",
                "flat_objective_flag": True,
                "best_remained_iteration_zero": True,
                "guidance_active": False,
                "spp_term_present_count": 0,
                "property_x_improved": False,
                "objective_total_improved": False,
                "analysis_metric_improved": False,
                "total_flat_property_gain": False,
            },
        ],
        reward_version="v1",
        action_profile="live_structural",
        analysis_metric_view="property_x",
    )
    agg = summary["aggregate"]
    assert agg["guidance_active_cases"] == 1
    assert agg["spp_term_present_cases"] == 1
    assert agg["property_improved_cases"] == 1
    assert agg["total_objective_improved_cases"] == 0
    assert agg["analysis_metric_improved_cases"] == 1
    assert agg["total_flat_property_gain_cases"] == 1
