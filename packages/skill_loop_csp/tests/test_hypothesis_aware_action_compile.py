from __future__ import annotations

from sok_llm_orchestrator.optimization.action_compile import compile_action
from sok_llm_orchestrator.optimization.action_registry import get_action


def test_hypothesis_aware_action_compile_applies_consistent_biases() -> None:
    action = get_action("guided_hybrid_balanced")
    baseline = compile_action(action).to_dict()
    framework_hypothesis = {
        "hypothesis_id": "h_framework",
        "label": "Framework competitor",
        "hypothesis_family": "framework_broad",
        "challenge_type": "framework_sensitive",
        "suggested_corpus_bias": "family_biased",
        "suggested_perturbation_bias": "symmetry_relaxation_and_template",
    }
    compiled = compile_action(action, hypothesis=framework_hypothesis).to_dict()

    assert compiled["guided_overrides"]["corpus_strategy"] == "family_biased"
    assert compiled["guided_overrides"]["template_seed_profile"] == "framework_bias"
    assert compiled["guided_overrides"]["lattice_candidate_profile"] == "multibasin"
    assert compiled["guided_overrides"]["symmetry_relaxation_profile"] == "relaxed"
    assert "Framework competitor" in compiled["query_suffix"]

    assert baseline["guided_overrides"]["template_seed_profile"] != compiled["guided_overrides"]["template_seed_profile"]
