from __future__ import annotations

from sok_llm_orchestrator.experiments.guided_sweep import build_guided_variant_sweep_report


def test_guided_variant_sweep_summary_aggregates_variants() -> None:
    raw = {
        "schema_version": "guided_variant_sweep.run.v1",
        "sweep_id": "guided-sweep-test",
        "mode": "stub",
        "case_file": "x.json",
        "repeats": 2,
        "metric_view": "property_aware",
        "variant_action_ids": ["baseline_control", "guided_hybrid_balanced"],
        "rows": [
            {
                "repeat_index": 1,
                "case_id": "c1",
                "action_id": "baseline_control",
                "action_family": "baseline_control",
                "property_x": 0.61,
                "objective_total": -1.53,
                "spp_term": None,
                "objective_terms_signature": "base",
                "guidance_active": False,
            },
            {
                "repeat_index": 1,
                "case_id": "c1",
                "action_id": "guided_hybrid_balanced",
                "action_family": "guided_exploit",
                "property_x": 0.78,
                "objective_total": -1.53,
                "spp_term": -4.36,
                "objective_terms_signature": "guided",
                "guidance_active": True,
            },
            {
                "repeat_index": 2,
                "case_id": "c1",
                "action_id": "baseline_control",
                "action_family": "baseline_control",
                "property_x": 0.61,
                "objective_total": -1.53,
                "spp_term": None,
                "objective_terms_signature": "base",
                "guidance_active": False,
            },
            {
                "repeat_index": 2,
                "case_id": "c1",
                "action_id": "guided_hybrid_balanced",
                "action_family": "guided_exploit",
                "property_x": 0.79,
                "objective_total": -1.53,
                "spp_term": -4.35,
                "objective_terms_signature": "guided",
                "guidance_active": True,
            },
        ],
    }
    report = build_guided_variant_sweep_report(raw)
    assert report["schema_version"] == "guided_variant_sweep.report.v1"
    assert report["aggregate"]["best_variant_action_id"] == "guided_hybrid_balanced"
    assert float(report["aggregate"]["guidance_activation_rate"]) > 0.0
    per_variant = {row["action_id"]: row for row in report["per_variant_table"]}
    assert per_variant["guided_hybrid_balanced"]["property_gain_vs_baseline_rate"] > 0.0
