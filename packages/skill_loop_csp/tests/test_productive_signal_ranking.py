from __future__ import annotations

from sok_llm_orchestrator.experiments.guided_sweep import rank_guided_variants


def test_productive_signal_ranking_property_aware() -> None:
    ranked = rank_guided_variants(
        [
            {
                "action_id": "baseline_control",
                "mean_property_x": 0.61,
                "property_gain_vs_baseline_rate": 0.0,
                "term_signature_changed_vs_baseline_rate": 0.0,
                "mean_objective_total": -1.53,
                "property_x_stdev": 0.0,
            },
            {
                "action_id": "guided_hybrid_balanced",
                "mean_property_x": 0.78,
                "property_gain_vs_baseline_rate": 1.0,
                "term_signature_changed_vs_baseline_rate": 1.0,
                "mean_objective_total": -1.53,
                "property_x_stdev": 0.01,
            },
        ],
        metric_view="property_aware",
    )
    assert ranked[0]["action_id"] == "guided_hybrid_balanced"


def test_productive_signal_ranking_decomposition_aware() -> None:
    ranked = rank_guided_variants(
        [
            {
                "action_id": "guided_variant_a",
                "mean_property_x": 0.70,
                "mean_abs_spp_term": 1.2,
                "spp_presence_rate": 1.0,
                "term_signature_changed_vs_baseline_rate": 1.0,
                "property_x_stdev": 0.02,
            },
            {
                "action_id": "guided_variant_b",
                "mean_property_x": 0.72,
                "mean_abs_spp_term": 0.1,
                "spp_presence_rate": 0.2,
                "term_signature_changed_vs_baseline_rate": 0.0,
                "property_x_stdev": 0.01,
            },
        ],
        metric_view="decomposition_aware",
    )
    assert ranked[0]["action_id"] == "guided_variant_a"
