from __future__ import annotations

from sok_llm_orchestrator.contracts.qlip_builders_v2 import build_solve_request_v2
from sok_llm_orchestrator.orchestrator.cell_selection import default_cell_candidates
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle
from sok_llm_orchestrator.spp.artifact_schema import SPPArtifactManifest


def _fixture_inputs() -> tuple[object, RetrievalBundle, SPPArtifactManifest]:
    spec = task_spec_from_query("TiO2")
    retrieval = RetrievalBundle(
        retrieval_id="r-weight",
        mode="metadata",
        fusion_notes=[],
        items=[
            {
                "structure_id": "mp-1",
                "provenance": "db",
                "scores": {"score": 0.9},
                "modality": "metadata",
                "identity": None,
                "cell_hint": None,
                "why_returned": "composition",
            }
        ],
    )
    artifact = SPPArtifactManifest(
        artifact_id="a-weight",
        corpus_hash="h",
        weighting_policy="linear",
        bin_policy={},
        smoothing_params={},
        calibration_summary={},
        neighbor_policy="first_shell",
        cutoff_policy="bandpass",
        shrink_protection={},
        metadata={"spp_package_path": "SPPs/test"},
    )
    return spec, retrieval, artifact


def test_dynamic_weighting_profiles_materialize_in_guidance_payload() -> None:
    spec, retrieval, artifact = _fixture_inputs()
    req_base, _ = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        retrieval,
        artifact,
        guidance_mode="guidance_only",
        guidance_config={"lambda_override": 0.5, "base_weight_scale": 1.2, "guidance_weight_scale": 0.7},
        weighting_profile="base_dominant",
        structure_perturbation_profile="minimal",
    )
    req_guided, _ = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        retrieval,
        artifact,
        guidance_mode="guidance_only",
        guidance_config={"lambda_override": 1.6, "base_weight_scale": 0.8, "guidance_weight_scale": 1.8},
        weighting_profile="guidance_dominant",
        structure_perturbation_profile="minimal",
    )
    base_params = req_base["guidance"][0]["params"]
    guided_params = req_guided["guidance"][0]["params"]
    assert base_params["weighting_profile"] == "base_dominant"
    assert guided_params["weighting_profile"] == "guidance_dominant"
    assert float(guided_params["lambda_override"]) > float(base_params["lambda_override"])
    assert float(guided_params["guidance_weight_scale"]) > float(base_params["guidance_weight_scale"])
