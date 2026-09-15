from __future__ import annotations

from sok_llm_orchestrator.contracts.qlip_builders_v2 import build_solve_request_v2
from sok_llm_orchestrator.orchestrator.cell_selection import default_cell_candidates
from sok_llm_orchestrator.orchestrator.task_spec import TaskSpec, task_spec_from_payload, task_spec_from_query
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle
from sok_llm_orchestrator.spp.artifact_schema import SPPArtifactManifest


def test_qlip_builder_v2_builds_strict_request() -> None:
    spec = task_spec_from_query("TiO2")
    retrieval = RetrievalBundle(
        retrieval_id="r1",
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
        artifact_id="a1",
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
    req, meta = build_solve_request_v2(spec, default_cell_candidates(), retrieval, artifact)
    assert req["version"] == "1.0"
    assert req["guidance"][0]["id"] == "objective.energy_spp"
    assert meta["retrieval_id"] == "r1"


def test_qlip_builder_v2_accepts_direct_structured_energy_objective() -> None:
    spec = TaskSpec(
        query_text="TiO2",
        composition_target="TiO2",
        qlip_objective={"type": "spp_energy"},
    )
    req, meta = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        RetrievalBundle(retrieval_id="r-energy", mode="metadata", fusion_notes=[], items=[]),
        None,
        guidance_mode="none",
    )
    assert "objective" not in req
    assert req["problem"]["objective"] == {"type": "spp_energy"}
    assert req["problem"]["chemistry"]["formula"] == "TiO2"
    assert req["solver"] == {"name": "gurobi"}
    assert meta["qlip_objective"] == {"type": "spp_energy"}


def test_qlip_builder_v2_writes_symmetry_and_prototype_scaffold() -> None:
    spec = task_spec_from_payload(
        {
            "query_text": "Generate BaTiO3 perovskite",
            "composition_target": "BaTiO3",
            "target_space_group": "Pm-3m",
            "target_space_group_number": 221,
            "target_crystal_system": "cubic",
            "target_structure_family": "perovskite",
            "prototype": "perovskite",
        }
    )

    req, meta = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        RetrievalBundle(retrieval_id="r-sym", mode="metadata", fusion_notes=[], items=[]),
        None,
        guidance_mode="none",
    )

    assert req["problem"]["symmetry"]["requested_space_group"] == "Pm-3m"
    assert req["problem"]["symmetry"]["requested_space_group_number"] == "221"
    assert req["problem"]["prototype"]["requested_family"] == "perovskite"
    assert req["problem"]["design_space"]["sites"]["mode"] == "prototype_scaffold"
    assert req["problem"]["design_space"]["sites"]["candidate_site_source"] == "prototype_scaffold"
    assert {item["id"] for item in req["constraints"]} == {"constraint.space_group", "constraint.prototype_scaffold"}
    assert meta["active_symmetry_mode"] == "prototype_scaffold"


def test_qlip_builder_v2_writes_prototype_orbit_mode_when_requested() -> None:
    spec = task_spec_from_payload(
        {
            "query_text": "Generate CeO2 fluorite",
            "composition_target": "CeO2",
            "target_space_group": "Fm-3m",
            "target_space_group_number": 225,
            "target_crystal_system": "cubic",
            "target_structure_family": "fluorite",
            "prototype": "fluorite",
        }
    )

    req, meta = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        RetrievalBundle(retrieval_id="r-orbit", mode="metadata", fusion_notes=[], items=[]),
        None,
        guidance_mode="none",
        active_symmetry_mode="prototype_orbit_qlip",
    )

    sites = req["problem"]["design_space"]["sites"]
    assert sites["mode"] == "prototype_orbit_qlip"
    assert sites["site_mode"] == "prototype_orbit"
    assert sites["candidate_site_source"] == "prototype_orbit_scaffold"
    assert sites["orbit_count"] == 2
    assert sites["site_count"] == 12
    assert [(orbit["preferred_species"], orbit["multiplicity"]) for orbit in sites["orbits"]] == [("Ce", 4), ("O", 8)]
    assert [selector["selection_scope"] for selector in sites["orbit_selectors"]] == ["orbit", "orbit"]
    assert all(selector["fixed_selected"] is True for selector in sites["orbit_selectors"])
    assert sites["selected_orbits"] == ["ce_4a", "o_8c"]
    assert len(sites["selected_sites"]) == 12
    assert req["constraints"][1]["params"]["enforcement"] == "closed_wyckoff_orbit_selection"
    assert meta["active_symmetry_mode"] == "prototype_orbit_qlip"


def test_qlip_builder_v2_writes_variable_prototype_orbit_mode_when_requested() -> None:
    spec = task_spec_from_payload(
        {
            "query_text": "Generate CaTiO3 perovskite",
            "composition_target": "CaTiO3",
            "target_space_group": "Pm-3m",
            "target_space_group_number": 221,
            "target_crystal_system": "cubic",
            "target_structure_family": "perovskite",
            "prototype": "perovskite",
        }
    )

    req, meta = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        RetrievalBundle(retrieval_id="r-variable-orbit", mode="metadata", fusion_notes=[], items=[]),
        None,
        guidance_mode="none",
        active_symmetry_mode="prototype_orbit_variable_qlip",
    )

    sites = req["problem"]["design_space"]["sites"]
    assert sites["mode"] == "prototype_orbit_variable_qlip"
    assert sites["site_mode"] == "prototype_orbit_variable"
    assert sites["candidate_site_source"] == "prototype_orbit_variable_scaffold"
    assert sites["orbit_count"] == 3
    assert sites["site_count"] == 5
    assert sites["orbit_variable_selection"] is True
    assert sites["formula_constraints"]["target_counts"] == {"Ca": 1, "Ti": 1, "O": 3}
    assert sites["selected_species_by_orbit"] == {"ba_1a": "Ca", "ti_1b": "Ti", "o_3c": "O"}
    assert sites["orbit_assignment_solver"] == "enumeration_backed_qlip_style_selector"
    assert len(sites["species_orbit_variables"]) == 5
    assert [selector["selection_scope"] for selector in sites["orbit_selectors"]] == ["orbit", "orbit", "orbit"]
    assert all(selector["fixed_selected"] is False for selector in sites["orbit_selectors"])
    assert req["constraints"][1]["params"]["enforcement"] == "variable_closed_wyckoff_orbit_selection"
    assert meta["active_symmetry_mode"] == "prototype_orbit_variable_qlip"


def test_qlip_builder_v2_writes_variable_spp_prototype_orbit_mode_when_requested() -> None:
    spec = task_spec_from_payload(
        {
            "query_text": "Generate BaTiO3 perovskite",
            "composition_target": "BaTiO3",
            "target_space_group": "Pm-3m",
            "target_space_group_number": 221,
            "target_crystal_system": "cubic",
            "target_structure_family": "perovskite",
            "prototype": "perovskite",
        }
    )

    req, meta = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        RetrievalBundle(retrieval_id="r-variable-spp-orbit", mode="metadata", fusion_notes=[], items=[]),
        None,
        guidance_mode="none",
        active_symmetry_mode="prototype_orbit_variable_spp_qlip",
    )

    sites = req["problem"]["design_space"]["sites"]
    assert sites["mode"] == "prototype_orbit_variable_spp_qlip"
    assert sites["site_mode"] == "prototype_orbit_variable"
    assert sites["orbit_variable_selection"] is True
    assert sites["spp_objective_enabled"] is False
    assert sites["spp_scoring_status"] == "unavailable"
    assert sites["spp_fallback_reason"] == "spp_curves_unavailable"
    assert sites["selected_candidate_id"] == "perovskite_orbit_assignment_1"
    assert req["constraints"][1]["params"]["mode"] == "prototype_orbit_variable_spp_qlip"
    assert meta["active_symmetry_mode"] == "prototype_orbit_variable_spp_qlip"


def test_qlip_builder_v2_keeps_generic_grid_without_symmetry() -> None:
    spec = task_spec_from_query("Generate TiO2")

    req, meta = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        RetrievalBundle(retrieval_id="r-nosym", mode="metadata", fusion_notes=[], items=[]),
        None,
        guidance_mode="none",
    )

    assert req["problem"]["design_space"]["sites"]["mode"] == "uniform_grid"
    assert req["constraints"] == []
    assert req["problem"]["symmetry"]["source"] == "none"
    assert meta["active_symmetry_mode"] == "none"
