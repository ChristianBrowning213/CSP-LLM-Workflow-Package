from __future__ import annotations

from sok_llm_orchestrator.experiments.guided_sweep import classify_structural_variant


def test_structural_variant_classification_likely_productive() -> None:
    baseline = {"mean_property_x": 0.61, "mean_objective_total": -1.53}
    cls = classify_structural_variant(
        {
            "unstable": False,
            "property_gain_vs_baseline_rate": 0.8,
            "term_signature_changed_vs_baseline_rate": 1.0,
            "guidance_activation_rate": 1.0,
            "mean_property_x": 0.79,
            "mean_objective_total": -1.53,
        },
        baseline_summary=baseline,
    )
    assert cls == "likely_productive"


def test_structural_variant_classification_term_movement_without_property_gain() -> None:
    baseline = {"mean_property_x": 0.61, "mean_objective_total": -1.53}
    cls = classify_structural_variant(
        {
            "unstable": False,
            "property_gain_vs_baseline_rate": 0.0,
            "term_signature_changed_vs_baseline_rate": 1.0,
            "guidance_activation_rate": 1.0,
            "mean_property_x": 0.61,
            "mean_objective_total": -1.53,
        },
        baseline_summary=baseline,
    )
    assert cls == "term_movement_without_property_gain"


def test_structural_variant_classification_unstable() -> None:
    baseline = {"mean_property_x": 0.61, "mean_objective_total": -1.53}
    cls = classify_structural_variant(
        {
            "unstable": True,
            "property_gain_vs_baseline_rate": 1.0,
            "term_signature_changed_vs_baseline_rate": 1.0,
            "guidance_activation_rate": 1.0,
            "mean_property_x": 0.8,
            "mean_objective_total": -1.53,
        },
        baseline_summary=baseline,
    )
    assert cls == "unstable_variant"
