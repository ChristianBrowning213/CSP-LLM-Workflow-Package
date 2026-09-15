from __future__ import annotations

from sok_llm_orchestrator.contracts.qlip_builders_v2 import build_solve_request_v2
from sok_llm_orchestrator.orchestrator.cell_selection import default_cell_candidates
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle
from sok_llm_orchestrator.spp.artifact_schema import SPPArtifactManifest


def _fixture_inputs() -> tuple[object, RetrievalBundle, SPPArtifactManifest]:
    spec = task_spec_from_query("TiO2")
    retrieval = RetrievalBundle(
        retrieval_id="r-perturb",
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
        artifact_id="a-perturb",
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


def test_structure_perturbation_profiles_change_request_structure() -> None:
    spec, retrieval, artifact = _fixture_inputs()
    req_min, _ = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        retrieval,
        artifact,
        weighting_profile="balanced",
        structure_perturbation_profile="minimal",
    )
    req_aggr, _ = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        retrieval,
        artifact,
        weighting_profile="balanced",
        structure_perturbation_profile="aggressive",
    )
    lattice_min = req_min["problem"]["design_space"]["template"]["lattice"]
    lattice_aggr = req_aggr["problem"]["design_space"]["template"]["lattice"]
    assert lattice_min != lattice_aggr
    density_min = req_min["problem"]["design_space"]["sites"]["uniform_grid"]["density"]
    density_aggr = req_aggr["problem"]["design_space"]["sites"]["uniform_grid"]["density"]
    assert int(density_aggr) > int(density_min)
    constraint_ids = [str(item.get("id")) for item in req_aggr.get("constraints", []) if isinstance(item, dict)]
    assert "constraint.structure_perturbation_profile" in constraint_ids
