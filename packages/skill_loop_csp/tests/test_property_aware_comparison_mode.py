from __future__ import annotations

from sok_llm_orchestrator.experiments.first_crystal import classify_progress_signal


def test_property_aware_mode_detects_flat_total_with_property_gain() -> None:
    out = classify_progress_signal(
        guidance_active=True,
        objective_total_delta=0.0,
        property_delta=0.12,
        objective_term_signature_diversity_count=2,
    )
    assert out == "total_flat_property_gain"


def test_property_aware_mode_detects_no_structural_guidance() -> None:
    out = classify_progress_signal(
        guidance_active=False,
        objective_total_delta=0.0,
        property_delta=0.25,
        objective_term_signature_diversity_count=1,
    )
    assert out == "no_structural_guidance_used"
