from __future__ import annotations

from sok_llm_orchestrator.spp.artifact_schema import SPPArtifactManifest, validate_spp_artifact


def test_spp_artifact_schema_and_hash() -> None:
    artifact = SPPArtifactManifest(
        artifact_id="spp-1",
        corpus_hash="abc",
        weighting_policy="linear_rank",
        bin_policy={"bin_width": 0.1},
        smoothing_params={"sigma": 0.2},
        calibration_summary={"recommended_weight": 0.3},
        neighbor_policy="first_shell",
        cutoff_policy="bandpass",
        shrink_protection={"min_distance": 1.2},
        metadata={"spp_package_path": "SPPs/spp-1"},
    )
    payload = artifact.to_dict()
    validate_spp_artifact(payload)
    assert artifact.content_hash
