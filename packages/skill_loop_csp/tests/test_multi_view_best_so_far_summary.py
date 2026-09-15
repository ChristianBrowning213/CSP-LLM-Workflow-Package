from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.experiments.first_crystal import build_repeated_first_crystal_summary


def test_multi_view_best_so_far_summary_distinguishes_objective_vs_property() -> None:
    case_file = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    run_summaries = [
        {
            "repeat_index": 1,
            "manifest_path": "m1.json",
            "summary_path": "s1.json",
            "summary": {
                "rows": [
                    {
                        "case_id": "case-a",
                        "case_class": "easy-improvement",
                        "guidance_active": True,
                        "spp_term_present_count": 2,
                        "property_x_improved": True,
                        "objective_total_improved": False,
                        "analysis_metric_improved": True,
                        "total_flat_property_gain": True,
                        "analysis_metric_final_best": 0.70,
                        "final_best_objective_total": -1.53,
                        "final_best_property_x": 0.70,
                        "best_action_id": "guided_hybrid_balanced",
                        "best_action_family": "guided_exploit",
                    }
                ]
            },
        },
        {
            "repeat_index": 2,
            "manifest_path": "m2.json",
            "summary_path": "s2.json",
            "summary": {
                "rows": [
                    {
                        "case_id": "case-a",
                        "case_class": "easy-improvement",
                        "guidance_active": True,
                        "spp_term_present_count": 2,
                        "property_x_improved": True,
                        "objective_total_improved": False,
                        "analysis_metric_improved": True,
                        "total_flat_property_gain": True,
                        "analysis_metric_final_best": 0.79,
                        "final_best_objective_total": -1.53,
                        "final_best_property_x": 0.79,
                        "best_action_id": "guided_property_push",
                        "best_action_family": "guided_exploit",
                    }
                ]
            },
        },
    ]
    summary = build_repeated_first_crystal_summary(
        repeated_experiment_id="repeat-test",
        case_file=case_file,
        run_summaries=run_summaries,
        reward_version="v1",
        action_profile="live_structural",
        analysis_metric_view="property_x",
    )

    total_view = summary["aggregate"]["view_summary"]["total_objective"]
    property_view = summary["aggregate"]["view_summary"]["property_aware"]
    assert bool(total_view["evidence_of_learning_signal"]) is False
    assert bool(property_view["evidence_of_learning_signal"]) is True
    assert float(property_view["best_so_far_delta"]) > 0.0

