from __future__ import annotations

from sok_llm_orchestrator.optimization.backend_sensitivity import classify_dimension_roles


def test_dimension_role_classification() -> None:
    roles = classify_dimension_roles(
        [
            {"dimension": "qlip_guidance", "propagation_classification": "propagates_to_request_structure"},
            {"dimension": "retrieval_policy", "propagation_classification": "changes_request_metadata_only"},
            {"dimension": "spp_weighting_calibration", "propagation_classification": "dropped_before_request"},
            {"dimension": "cell_selection", "propagation_classification": "unclear"},
        ]
    )
    assert roles["qlip_guidance"] == "backend_structural"
    assert roles["retrieval_policy"] == "orchestration_metadata_only"
    assert roles["spp_weighting_calibration"] == "metadata_only_demoted"
    assert roles["cell_selection"] == "unresolved"

