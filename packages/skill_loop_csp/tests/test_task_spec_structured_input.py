from __future__ import annotations

import json

from sok_llm_orchestrator.orchestrator.task_spec import load_task_spec_file, task_spec_from_payload


def test_task_spec_from_payload_binds_canonical_objective_id() -> None:
    spec = task_spec_from_payload(
        {
            "composition_target": "TiO2",
            "solve_mode": "feasibility",
            "symmetry_request": {"space_group": None, "hardness": "none"},
            "qlip_objective": "qlip.objective.energy_proxy",
        }
    )
    assert spec.query_text == "TiO2"
    assert spec.composition_target == "TiO2"
    assert spec.solve_mode == "feasibility"
    assert spec.qlip_objective == {"type": "spp_energy"}
    assert "query_text:derived_from_task_spec" in spec.defaults_used


def test_task_spec_from_payload_preserves_symmetry_and_prototype_targets() -> None:
    spec = task_spec_from_payload(
        {
            "query_text": "Generate BaTiO3",
            "composition_target": "BaTiO3",
            "target_space_group": "Pm-3m",
            "target_space_group_number": 221,
            "target_crystal_system": "cubic",
            "target_structure_family": "perovskite",
            "prototype": "perovskite",
        }
    )

    assert spec.symmetry_request.space_group == "Pm-3m"
    assert spec.symmetry_request.hardness == "hard"
    assert spec.target_space_group == "Pm-3m"
    assert spec.target_space_group_number == "221"
    assert spec.target_crystal_system == "cubic"
    assert spec.target_structure_family == "perovskite"
    assert spec.prototype == "perovskite"


def test_load_task_spec_file_accepts_yaml_and_json(workdir) -> None:
    yaml_path = workdir / "task_spec.yaml"
    json_path = workdir / "task_spec.json"
    payload = {
        "composition_target": "TiO2",
        "query_text": "TiO2 structured run",
        "solve_mode": "feasibility",
        "symmetry_request": {"space_group": None, "hardness": "none"},
        "qlip_objective": {"type": "spp_energy"},
    }
    yaml_path.write_text(
        "composition_target: TiO2\n"
        "query_text: TiO2 structured run\n"
        "solve_mode: feasibility\n"
        "symmetry_request:\n"
        "  space_group: null\n"
        "  hardness: none\n"
        "qlip_objective:\n"
        "  type: spp_energy\n",
        encoding="utf-8",
    )
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    yaml_spec = load_task_spec_file(yaml_path)
    json_spec = load_task_spec_file(json_path)

    assert yaml_spec.to_dict() == json_spec.to_dict()
