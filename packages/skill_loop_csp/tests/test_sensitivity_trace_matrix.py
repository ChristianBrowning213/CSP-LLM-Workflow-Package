from __future__ import annotations

from sok_llm_orchestrator.optimization.backend_sensitivity import build_sensitivity_trace_matrix


def test_sensitivity_trace_matrix_tracks_dimension_changes() -> None:
    previous = {
        "action_dimensions": {
            "retrieval_policy": "metadata",
            "spp_corpus_strategy": "composition_tight",
            "spp_weighting_calibration": "conservative",
            "qlip_guidance": "none",
            "cell_selection": "baseline_default",
        },
        "request_trace": {"effective_overrides": {"retrieval_mode": "metadata", "guidance_mode": "none"}},
        "objective_audit": {"objective_total": 0.1, "objective_terms_signature": "t1"},
    }
    current = {
        "action_dimensions": {
            "retrieval_policy": "hybrid",
            "spp_corpus_strategy": "top_k",
            "spp_weighting_calibration": "balanced",
            "qlip_guidance": "guidance_only",
            "cell_selection": "retrieval_informed",
        },
        "request_trace": {"effective_overrides": {"retrieval_mode": "hybrid", "guidance_mode": "guidance_only"}},
        "objective_audit": {"objective_total": 0.2, "objective_terms_signature": "t2"},
    }
    matrix = build_sensitivity_trace_matrix(previous, current)
    assert matrix["retrieval_policy"]["action_changed"] is True
    assert matrix["retrieval_policy"]["request_changed"] is True
    assert matrix["retrieval_policy"]["objective_changed"] is True
    assert matrix["qlip_guidance"]["request_changed"] is True

