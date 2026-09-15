from __future__ import annotations

import json
from pathlib import Path

import pytest

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def _settings_for_workspace(workspace: Path) -> Settings:
    settings = Settings.from_sources(None)
    settings.workspace_root = workspace
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    return settings


def _partial_spp_fallback(workspace: Path) -> dict[str, object]:
    regularisation_dir = workspace / "regularisation_spp"
    regularisation_dir.mkdir(parents=True, exist_ok=True)
    return {
        "allow_qlip_without_spp": True,
        "allow_partial_spp_guidance": True,
        "spp_regularisation_dir": str(regularisation_dir),
        "spp_regularisation_weight": 1.0,
        "spp_missing_pair_policy": "soft_repulsive",
    }


def test_pipeline_structured_task_spec_produces_deterministic_request(workdir: Path) -> None:
    task_spec_payload = {
        "query_text": "TiO2 structured objective case",
        "composition_target": "TiO2",
        "solve_mode": "feasibility",
        "symmetry_request": {"space_group": None, "hardness": "none"},
        "qlip_objective": "qlip.objective.energy_proxy",
    }

    left_workspace = workdir / "left"
    right_workspace = workdir / "right"
    left_workspace.mkdir(parents=True, exist_ok=True)
    right_workspace.mkdir(parents=True, exist_ok=True)

    left = run_csp_pipeline(
        query=None,
        with_spp=True,
        mode="stub",
        workspace=left_workspace,
        settings=_settings_for_workspace(left_workspace),
        execution_overrides=_partial_spp_fallback(left_workspace),
        task_spec_payload=task_spec_payload,
    )
    right = run_csp_pipeline(
        query=None,
        with_spp=True,
        mode="stub",
        workspace=right_workspace,
        settings=_settings_for_workspace(right_workspace),
        execution_overrides=_partial_spp_fallback(right_workspace),
        task_spec_payload=task_spec_payload,
    )

    assert left.status == "SUCCEEDED"
    assert right.status == "SUCCEEDED"

    left_task_spec = json.loads((left.run_dir / "artifacts" / "task_spec.json").read_text(encoding="utf-8"))
    right_task_spec = json.loads((right.run_dir / "artifacts" / "task_spec.json").read_text(encoding="utf-8"))
    assert left_task_spec["qlip_objective"] == {"type": "spp_energy"}
    assert right_task_spec["qlip_objective"] == {"type": "spp_energy"}

    left_request = json.loads((left.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    right_request = json.loads((right.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    assert left_request["problem"]["objective"] == {"type": "spp_energy"}
    assert right_request["problem"]["objective"] == {"type": "spp_energy"}
    assert left_request["guidance"][0]["params"]["regularisation_spp_dir"] != right_request["guidance"][0]["params"]["regularisation_spp_dir"]

    left_semantic_request = json.loads(
        (left.run_dir / "artifacts" / "qlip_request.semantic.json").read_text(encoding="utf-8")
    )
    right_semantic_request = json.loads(
        (right.run_dir / "artifacts" / "qlip_request.semantic.json").read_text(encoding="utf-8")
    )
    assert left_semantic_request == right_semantic_request
    assert left_semantic_request["problem"]["objective"] == {"type": "spp_energy"}

    left_meta = json.loads((left.run_dir / "artifacts" / "qlip_builder_meta.json").read_text(encoding="utf-8"))
    assert left_meta["builder_input_trace"]["builder_inputs"]["qlip_objective_family"] == "spp_energy"


def test_pipeline_structured_symmetry_writes_trace_and_request(workdir: Path) -> None:
    task_spec_payload = {
        "query_text": "Generate BaTiO3 perovskite",
        "composition_target": "BaTiO3",
        "target_space_group": "Pm-3m",
        "target_space_group_number": 221,
        "target_crystal_system": "cubic",
        "target_structure_family": "perovskite",
        "prototype": "perovskite",
    }
    workspace = workdir / "symmetry"
    workspace.mkdir(parents=True, exist_ok=True)

    result = run_csp_pipeline(
        query=None,
        with_spp=True,
        mode="stub",
        workspace=workspace,
        settings=_settings_for_workspace(workspace),
        execution_overrides=_partial_spp_fallback(workspace),
        task_spec_payload=task_spec_payload,
    )

    assert result.status == "SUCCEEDED"
    request = json.loads((result.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    trace = json.loads((result.run_dir / "artifacts" / "symmetry_trace.json").read_text(encoding="utf-8"))
    assert request["problem"]["symmetry"]["requested_space_group"] == "Pm-3m"
    assert request["problem"]["design_space"]["sites"]["mode"] == "prototype_scaffold"
    assert request["problem"]["design_space"]["sites"]["site_mode"] == "prototype_scaffold"
    assert trace["requested_space_group"] == "Pm-3m"
    assert trace["active_symmetry_mode"] == "prototype_scaffold"
    assert trace["candidate_site_source"] == "prototype_scaffold"
    assert trace["scaffold_used_for_final_cif"] is True
    assert trace["final_cif_source"] == "prototype_scaffold"
    assert trace["scaffold_family"] == "perovskite"
    assert trace["scaffold_space_group"] == "Pm-3m"
    assert trace["scaffold_space_group_number"] == 221
    assert trace["scaffold_crystal_system"] == "cubic"
    assert trace["scaffold_site_count"] == 5
    assert trace["scaffold_formula"] == "BaTiO3"
    assert trace["scaffold_lattice_parameters"]
    assert trace["scaffold_fractional_coordinates"]
    assert trace["scaffold_source_note"]
    assert trace["post_solve_validation"]["ok"] is True
    assert trace["post_solve_validation"]["analyzed_crystal_system"] == "cubic"


def test_pipeline_structured_symmetry_writes_prototype_orbit_qlip_trace(workdir: Path) -> None:
    task_spec_payload = {
        "query_text": "Generate BaTiO3 perovskite",
        "composition_target": "BaTiO3",
        "target_space_group": "Pm-3m",
        "target_space_group_number": 221,
        "target_crystal_system": "cubic",
        "target_structure_family": "perovskite",
        "prototype": "perovskite",
    }
    workspace = workdir / "prototype_orbit"
    workspace.mkdir(parents=True, exist_ok=True)
    overrides = _partial_spp_fallback(workspace)
    overrides["active_symmetry_mode"] = "prototype_orbit_qlip"

    result = run_csp_pipeline(
        query=None,
        with_spp=True,
        mode="stub",
        workspace=workspace,
        settings=_settings_for_workspace(workspace),
        execution_overrides=overrides,
        task_spec_payload=task_spec_payload,
    )

    assert result.status == "SUCCEEDED"
    request = json.loads((result.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    trace = json.loads((result.run_dir / "artifacts" / "symmetry_trace.json").read_text(encoding="utf-8"))
    orbit_solution = json.loads((result.run_dir / "artifacts" / "orbit_solution.json").read_text(encoding="utf-8"))
    sites = request["problem"]["design_space"]["sites"]
    assert sites["mode"] == "prototype_orbit_qlip"
    assert sites["site_mode"] == "prototype_orbit"
    assert sites["orbit_count"] == 3
    assert sites["site_count"] == 5
    assert trace["active_symmetry_mode"] == "prototype_orbit_qlip"
    assert trace["orbit_level_selection"] is True
    assert trace["final_cif_source"] == "prototype_orbit_qlip"
    assert trace["symmetry_closed"] is True
    assert trace["selected_orbits"] == ["ba_1a", "ti_1b", "o_3c"]
    assert len(trace["selected_sites"]) == 5
    assert orbit_solution["orbit_level_selection"] is True
    assert orbit_solution["symmetry_closed"] is True
    assert trace["post_solve_validation"]["space_group_exact_match"] is True


def test_pipeline_structured_symmetry_writes_variable_prototype_orbit_qlip_artifacts(workdir: Path) -> None:
    task_spec_payload = {
        "query_text": "Generate SrTiO3 perovskite with variable orbit selection",
        "composition_target": "SrTiO3",
        "target_space_group": "Pm-3m",
        "target_space_group_number": 221,
        "target_crystal_system": "cubic",
        "target_structure_family": "perovskite",
        "prototype": "perovskite",
    }
    workspace = workdir / "prototype_orbit_variable"
    workspace.mkdir(parents=True, exist_ok=True)
    overrides = _partial_spp_fallback(workspace)
    overrides["active_symmetry_mode"] = "prototype_orbit_variable_qlip"

    result = run_csp_pipeline(
        query=None,
        with_spp=True,
        mode="stub",
        workspace=workspace,
        settings=_settings_for_workspace(workspace),
        execution_overrides=overrides,
        task_spec_payload=task_spec_payload,
    )

    assert result.status == "SUCCEEDED"
    request = json.loads((result.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    trace = json.loads((result.run_dir / "artifacts" / "symmetry_trace.json").read_text(encoding="utf-8"))
    orbit_solution = json.loads((result.run_dir / "artifacts" / "orbit_solution.json").read_text(encoding="utf-8"))
    orbit_candidates = json.loads((result.run_dir / "artifacts" / "orbit_candidates.json").read_text(encoding="utf-8"))
    sites = request["problem"]["design_space"]["sites"]
    assert sites["site_mode"] == "prototype_orbit_variable"
    assert sites["orbit_variable_selection"] is True
    assert sites["formula_constraints"]["target_counts"] == {"Sr": 1, "Ti": 1, "O": 3}
    assert sites["selected_species_by_orbit"] == {"ba_1a": "Sr", "ti_1b": "Ti", "o_3c": "O"}
    assert trace["active_symmetry_mode"] == "prototype_orbit_variable_qlip"
    assert trace["orbit_level_selection"] is True
    assert trace["variable_orbit_selection"] is True
    assert trace["final_cif_source"] == "prototype_orbit_variable_qlip"
    assert trace["symmetry_closed"] is True
    assert trace["selected_species_by_orbit"]["ba_1a"] == "Sr"
    assert trace["spp_scoring_status"] == "unavailable"
    assert trace["orbit_assignment_solver"] == "enumeration_backed_qlip_style_selector"
    assert orbit_solution["variable_orbit_selection"] is True
    assert orbit_solution["selected_species_by_orbit"]["ba_1a"] == "Sr"
    assert orbit_solution["orbit_assignment_solver"] == "enumeration_backed_qlip_style_selector"
    assert orbit_candidates["mode"] == "prototype_orbit_variable_qlip"
    assert orbit_candidates["orbit_assignment_solver"] == "enumeration_backed_qlip_style_selector"
    assert len([candidate for candidate in orbit_candidates["candidates"] if candidate["formula_satisfied"]]) == 1
    assert trace["post_solve_validation"]["space_group_exact_match"] is True
    assert trace["post_solve_validation"]["crystal_system_match"] is True


def test_pipeline_structured_symmetry_writes_variable_spp_prototype_orbit_qlip_artifacts(workdir: Path) -> None:
    task_spec_payload = {
        "query_text": "Generate BaTiO3 perovskite with SPP-scored variable orbit selection",
        "composition_target": "BaTiO3",
        "target_space_group": "Pm-3m",
        "target_space_group_number": 221,
        "target_crystal_system": "cubic",
        "target_structure_family": "perovskite",
        "prototype": "perovskite",
    }
    workspace = workdir / "prototype_orbit_variable_spp"
    workspace.mkdir(parents=True, exist_ok=True)
    overrides = _partial_spp_fallback(workspace)
    overrides["active_symmetry_mode"] = "prototype_orbit_variable_spp_qlip"

    result = run_csp_pipeline(
        query=None,
        with_spp=True,
        mode="stub",
        workspace=workspace,
        settings=_settings_for_workspace(workspace),
        execution_overrides=overrides,
        task_spec_payload=task_spec_payload,
    )

    assert result.status == "SUCCEEDED"
    request = json.loads((result.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    trace = json.loads((result.run_dir / "artifacts" / "symmetry_trace.json").read_text(encoding="utf-8"))
    orbit_solution = json.loads((result.run_dir / "artifacts" / "orbit_solution.json").read_text(encoding="utf-8"))
    orbit_candidates = json.loads((result.run_dir / "artifacts" / "orbit_candidates.json").read_text(encoding="utf-8"))
    sites = request["problem"]["design_space"]["sites"]
    assert sites["mode"] == "prototype_orbit_variable_spp_qlip"
    assert sites["site_mode"] == "prototype_orbit_variable"
    assert sites["spp_objective_enabled"] is False
    assert sites["spp_scoring_status"] == "unavailable"
    assert trace["active_symmetry_mode"] == "prototype_orbit_variable_spp_qlip"
    assert trace["variable_orbit_selection"] is True
    assert trace["selected_candidate_id"] == "perovskite_orbit_assignment_1"
    assert trace["spp_scoring_status"] == "unavailable"
    assert trace["spp_fallback_reason"] == "spp_curves_unavailable"
    assert trace["symmetry_closed"] is True
    assert orbit_solution["selected_candidate_id"] == "perovskite_orbit_assignment_1"
    assert orbit_solution["spp_scoring_status"] == "unavailable"
    assert orbit_solution["objective_value"] is None
    assert orbit_candidates["spp_scoring_status"] == "unavailable"
    assert trace["post_solve_validation"]["space_group_exact_match"] is True
    assert trace["post_solve_validation"]["crystal_system_match"] is True


@pytest.mark.parametrize(
    ("formula", "family", "space_group", "space_group_number", "crystal_system", "site_count", "orbit_count"),
    [
        ("BaTiO3", "perovskite", "Pm-3m", 221, "cubic", 5, 3),
        ("CsPbBr3", "halide perovskite", "Pm-3m", 221, "cubic", 5, 3),
        ("ZnFe2O4", "spinel", "Fd-3m", 227, "cubic", 56, 3),
        ("NiO", "rocksalt", "Fm-3m", 225, "cubic", 8, 2),
        ("CeO2", "fluorite", "Fm-3m", 225, "cubic", 12, 2),
        ("FeS2", "pyrite", "Pa-3", 205, "cubic", 12, 2),
        ("LiCoO2", "layered oxide", "R-3m", 166, "trigonal", 12, 3),
        ("LiFePO4", "olivine phosphate", "Pnma", 62, "orthorhombic", 28, 6),
        ("Li6PS5Cl", "argyrodite", "F-43m", 216, "cubic", 52, 5),
        ("TiN", "nitride", "Fm-3m", 225, "cubic", 8, 2),
    ],
)
def test_pipeline_structured_orbit_mode_writes_all_10_orbit_solutions(
    workdir: Path,
    formula: str,
    family: str,
    space_group: str,
    space_group_number: int,
    crystal_system: str,
    site_count: int,
    orbit_count: int,
) -> None:
    task_spec_payload = {
        "query_text": f"Generate {formula} {family}",
        "composition_target": formula,
        "target_space_group": space_group,
        "target_space_group_number": space_group_number,
        "target_crystal_system": crystal_system,
        "target_structure_family": family,
        "prototype": family,
    }
    workspace = workdir / f"orbit_{formula.lower()}"
    workspace.mkdir(parents=True, exist_ok=True)
    overrides = _partial_spp_fallback(workspace)
    overrides["active_symmetry_mode"] = "prototype_orbit_qlip"

    result = run_csp_pipeline(
        query=None,
        with_spp=True,
        mode="stub",
        workspace=workspace,
        settings=_settings_for_workspace(workspace),
        execution_overrides=overrides,
        task_spec_payload=task_spec_payload,
    )

    assert result.status == "SUCCEEDED"
    request = json.loads((result.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    trace = json.loads((result.run_dir / "artifacts" / "symmetry_trace.json").read_text(encoding="utf-8"))
    orbit_solution = json.loads((result.run_dir / "artifacts" / "orbit_solution.json").read_text(encoding="utf-8"))
    sites = request["problem"]["design_space"]["sites"]
    assert sites["site_mode"] == "prototype_orbit"
    assert sites["orbit_count"] == orbit_count
    assert sites["site_count"] == site_count
    assert len(sites["orbit_selectors"]) == orbit_count
    assert all(selector["selection_scope"] == "orbit" for selector in sites["orbit_selectors"])
    assert trace["active_symmetry_mode"] == "prototype_orbit_qlip"
    assert trace["orbit_level_selection"] is True
    assert trace["final_cif_source"] == "prototype_orbit_qlip"
    assert trace["symmetry_closed"] is True
    assert trace["scaffold_space_group"] == space_group
    assert trace["scaffold_space_group_number"] == space_group_number
    assert trace["scaffold_crystal_system"] == crystal_system
    assert len(trace["selected_orbits"]) == orbit_count
    assert len(trace["selected_sites"]) == site_count
    assert orbit_solution["formula"] == formula
    assert orbit_solution["symmetry_closed"] is True
    assert len(orbit_solution["orbits"]) == orbit_count
    assert len(orbit_solution["sites"]) == site_count
    assert trace["post_solve_validation"]["space_group_exact_match"] is True
    assert trace["post_solve_validation"]["crystal_system_match"] is True


@pytest.mark.parametrize(
    ("formula", "family", "space_group", "space_group_number", "crystal_system", "site_count"),
    [
        ("CsPbBr3", "halide perovskite", "Pm-3m", 221, "cubic", 5),
        ("ZnFe2O4", "spinel", "Fd-3m", 227, "cubic", 56),
        ("NiO", "rocksalt", "Fm-3m", 225, "cubic", 8),
        ("CeO2", "fluorite", "Fm-3m", 225, "cubic", 12),
        ("FeS2", "pyrite", "Pa-3", 205, "cubic", 12),
        ("LiCoO2", "layered oxide", "R-3m", 166, "trigonal", 12),
        ("LiFePO4", "olivine phosphate", "Pnma", 62, "orthorhombic", 28),
        ("Li6PS5Cl", "argyrodite", "F-43m", 216, "cubic", 52),
        ("TiN", "nitride", "Fm-3m", 225, "cubic", 8),
    ],
)
def test_pipeline_structured_symmetry_uses_supported_final_scaffold(
    workdir: Path,
    formula: str,
    family: str,
    space_group: str,
    space_group_number: int,
    crystal_system: str,
    site_count: int,
) -> None:
    task_spec_payload = {
        "query_text": f"Generate {formula} {family}",
        "composition_target": formula,
        "target_space_group": space_group,
        "target_space_group_number": space_group_number,
        "target_crystal_system": crystal_system,
        "target_structure_family": family,
        "prototype": family,
    }
    workspace = workdir / formula.lower()
    workspace.mkdir(parents=True, exist_ok=True)

    result = run_csp_pipeline(
        query=None,
        with_spp=True,
        mode="stub",
        workspace=workspace,
        settings=_settings_for_workspace(workspace),
        execution_overrides=_partial_spp_fallback(workspace),
        task_spec_payload=task_spec_payload,
    )

    assert result.status == "SUCCEEDED"
    request = json.loads((result.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    trace = json.loads((result.run_dir / "artifacts" / "symmetry_trace.json").read_text(encoding="utf-8"))
    assert request["problem"]["design_space"]["sites"]["site_mode"] == "prototype_scaffold"
    assert trace["scaffold_used_for_final_cif"] is True
    assert trace["final_cif_source"] == "prototype_scaffold"
    assert trace["scaffold_family"] == family
    assert trace["scaffold_space_group"] == space_group
    assert trace["scaffold_space_group_number"] == space_group_number
    assert trace["scaffold_crystal_system"] == crystal_system
    assert trace["scaffold_site_count"] == site_count
    assert trace["scaffold_formula"] == formula
    assert trace["scaffold_lattice_parameters"]
    assert trace["scaffold_fractional_coordinates"]
    assert trace["scaffold_source_note"]
    assert trace["post_solve_validation"]["analyzed_crystal_system"] == crystal_system


def test_pipeline_structured_symmetry_falls_back_for_unsupported_scaffold(workdir: Path) -> None:
    task_spec_payload = {
        "query_text": "Generate TiO2 rutile",
        "composition_target": "TiO2",
        "target_space_group": "P42/mnm",
        "target_space_group_number": 136,
        "target_crystal_system": "tetragonal",
        "target_structure_family": "rutile",
        "prototype": "rutile",
    }
    workspace = workdir / "unsupported"
    workspace.mkdir(parents=True, exist_ok=True)

    result = run_csp_pipeline(
        query=None,
        with_spp=True,
        mode="stub",
        workspace=workspace,
        settings=_settings_for_workspace(workspace),
        execution_overrides=_partial_spp_fallback(workspace),
        task_spec_payload=task_spec_payload,
    )

    assert result.status == "SUCCEEDED"
    trace = json.loads((result.run_dir / "artifacts" / "symmetry_trace.json").read_text(encoding="utf-8"))
    assert trace["scaffold_used_for_final_cif"] is False
    assert trace["final_cif_source"] == "generic_fallback"
    assert trace["fallback_reason"] == "unsupported_family"


def test_pipeline_no_symmetry_keeps_generic_site_mode(workdir: Path) -> None:
    task_spec_payload = {
        "query_text": "Generate Si",
        "composition_target": "Si",
        "symmetry_request": {"space_group": None, "hardness": "none"},
    }
    workspace = workdir / "generic"
    workspace.mkdir(parents=True, exist_ok=True)

    result = run_csp_pipeline(
        query=None,
        with_spp=True,
        mode="stub",
        workspace=workspace,
        settings=_settings_for_workspace(workspace),
        execution_overrides=_partial_spp_fallback(workspace),
        task_spec_payload=task_spec_payload,
    )

    assert result.status == "SUCCEEDED"
    request = json.loads((result.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    trace = json.loads((result.run_dir / "artifacts" / "symmetry_trace.json").read_text(encoding="utf-8"))
    assert request["problem"]["design_space"]["sites"]["mode"] == "uniform_grid"
    assert "site_mode" not in request["problem"]["design_space"]["sites"]
    assert trace["scaffold_used_for_final_cif"] is False
    assert trace["final_cif_source"] == "generic_fallback"
