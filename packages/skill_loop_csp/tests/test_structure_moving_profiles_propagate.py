from __future__ import annotations

from sok_llm_orchestrator.contracts.qlip_builders_v2 import build_solve_request_v2
from sok_llm_orchestrator.orchestrator.cell_selection import default_cell_candidates
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle
from sok_llm_orchestrator.spp.artifact_schema import SPPArtifactManifest


def _inputs() -> tuple[object, RetrievalBundle, SPPArtifactManifest]:
    spec = task_spec_from_query("SrTiO3 symmetry Pm-3m hard")
    retrieval = RetrievalBundle(
        retrieval_id="r-structure-moving",
        mode="hybrid",
        fusion_notes=[],
        items=[
            {
                "structure_id": "mp-100",
                "provenance": "db",
                "scores": {"score": 0.9},
                "modality": "metadata",
                "identity": None,
                "cell_hint": None,
                "why_returned": "test",
            }
        ],
    )
    artifact = SPPArtifactManifest(
        artifact_id="a-structure-moving",
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


def test_structure_moving_profiles_materialize_request_structure() -> None:
    spec, retrieval, artifact = _inputs()
    req_a, _ = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        retrieval,
        artifact,
        guidance_mode="guidance_only",
        weighting_profile="balanced",
        structure_perturbation_profile="minimal",
        template_seed_profile="canonical",
        lattice_candidate_profile="narrow",
        symmetry_relaxation_profile="strict",
        ordering_perturbation_profile="none",
    )
    req_b, _ = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        retrieval,
        artifact,
        guidance_mode="guidance_only",
        weighting_profile="guidance_dominant",
        structure_perturbation_profile="template_shuffle",
        template_seed_profile="ordering_bias",
        lattice_candidate_profile="multibasin",
        symmetry_relaxation_profile="relaxed",
        ordering_perturbation_profile="cation_swap_bias",
    )

    ds_a = req_a["problem"]["design_space"]
    ds_b = req_b["problem"]["design_space"]
    assert ds_a["template"]["lattice"] != ds_b["template"]["lattice"]
    assert ds_a["template"]["seed_profile"] == "canonical"
    assert ds_b["template"]["seed_profile"] == "ordering_bias"
    assert len(ds_b["template_candidates"]) > len(ds_a["template_candidates"])
    assert ds_a["sites"]["mode"] == "uniform_grid"
    assert ds_b["sites"]["mode"] == "ordered_priors"

    constraints_b = [str(item.get("id")) for item in req_b.get("constraints", []) if isinstance(item, dict)]
    assert "constraint.ordering_perturbation_profile" in constraints_b

    params_b = req_b["guidance"][0]["params"]
    assert params_b["template_seed_profile"] == "ordering_bias"
    assert params_b["lattice_candidate_profile"] == "multibasin"
    assert params_b["symmetry_relaxation_profile"] == "relaxed"
    assert params_b["ordering_perturbation_profile"] == "cation_swap_bias"
