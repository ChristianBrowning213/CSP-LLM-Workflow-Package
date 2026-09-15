from __future__ import annotations

from sok_llm_orchestrator.optimization.backend_sensitivity import summarize_action_library_relevance


def test_action_library_relevance_summary_groups_dimensions() -> None:
    summary = summarize_action_library_relevance(
        [
            {"dimension": "retrieval_policy", "classification": "objective_coupled"},
            {"dimension": "spp_corpus_strategy", "classification": "request_changes_no_objective_effect"},
            {"dimension": "qlip_guidance", "classification": "same_effective_request"},
            {"dimension": "cell_selection", "classification": "metadata_only"},
            {"dimension": "spp_weighting_calibration", "classification": "unclear"},
        ]
    )
    assert "retrieval_policy" in summary["likely_useful_for_objective_optimization"]
    assert "spp_corpus_strategy" in summary["likely_inert_under_current_backend"]
    assert "cell_selection" in summary["likely_inert_under_current_backend"]
    assert "qlip_guidance" in summary["needs_stronger_compile_coupling"]
    assert "spp_weighting_calibration" in summary["metadata_only_demoted"]
