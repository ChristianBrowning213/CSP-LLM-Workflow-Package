from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
from pymatgen.core import Composition

from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
    _qlip_ordered_orbits_adapter,
    _qlip_target_formula,
    _validate_qlip_species_contract,
)


def _schema() -> dict:
    import qlip

    root = Path(qlip.__file__).resolve()
    for parent in root.parents:
        candidate = parent / "docs" / "mcp" / "MCP_SCHEMA.json"
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))["solve_request"]
    raise RuntimeError(f"unable to locate installed QLIP solve schema from {root}")


def _request(structure, scaffold_id: str, ordered_orbits: list[dict], *, formula: str | None = None) -> dict:
    cell = structure.lattice
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": formula or structure.composition.formula.replace(" ", "")},
            "design_space": {
                "template": {
                    "name": scaffold_id,
                    "lattice": {
                        "a": cell.a, "b": cell.b, "c": cell.c,
                        "alpha": cell.alpha, "beta": cell.beta, "gamma": cell.gamma,
                        "units": "angstrom",
                    },
                },
                "sites": {
                    "mode": "explicit_fractional_sites",
                    "explicit_fractional_sites": structure.frac_coords.tolist(),
                    "ordered_orbits": ordered_orbits,
                },
            },
            "objective": {"type": "none"},
        },
        "constraints": [],
        "guidance": [],
        "guidance_mode": "weighted_sum",
        "solver": {"name": "gurobi"},
        "artifacts": {"return_cif": True},
        "runtime": {"max_sites": 64, "max_binary_vars": 500, "max_constraints": 1000},
        "context": {"run_id": "serialization-contract", "pot_root": str(Path.cwd())},
    }


def test_nasicon_ordered_orbits_serialize_to_strict_qlip_contract() -> None:
    stages = ProductionWorkflowStages()
    task = stages.normalise("Na3Zr2Si2PO12")
    scaffold_id, structure, internal = stages._scaffold(task, WorkflowConfig(output_root=Path(".")))
    wire = _qlip_ordered_orbits_adapter(internal)

    assert len(wire) == len(internal)
    assert [row["orbit_id"] for row in wire] == [row["orbit_id"] for row in internal]
    assert [row["site_indices"] for row in wire] == [list(row["site_indices"]) for row in internal]
    assert [row["allowed_species"] for row in wire] == [list(row["allowed_species"]) for row in internal]
    assert all(row["required_occupancy"] is True for row in wire)
    assert all(isinstance(row["site_indices"], list) for row in wire)
    assert all(row.get("fixed_species") is not None for row in wire if "fixed_species" in row)
    assert not ({"source_species", "multiplicity", "coordination_role", "occupation_mode"} & {key for row in wire for key in row})

    round_trip = json.loads(json.dumps(wire))
    assert [row["site_indices"] for row in round_trip] == [list(row["site_indices"]) for row in internal]
    errors = list(Draft202012Validator(_schema()).iter_errors(_request(structure, scaffold_id, wire)))
    assert errors == []


def test_nasicon_success_reporting_does_not_call_abx3_assignment_counter(monkeypatch) -> None:
    stages = ProductionWorkflowStages()
    task = stages.normalise("Na3Zr2Si2PO12")
    monkeypatch.setattr(
        stages, "enumerate_feasible_assignments",
        lambda *args, **kwargs: pytest.fail("ABX3 counter called for NASICON"),
    )
    assert stages.reported_feasible_state_count(
        task, WorkflowConfig(output_root=Path(".")),
    ) is None


def test_abx3_ordered_orbit_wire_payload_is_unchanged() -> None:
    stages = ProductionWorkflowStages()
    task = stages.normalise("BaTiO3")
    for scaffold_mode in ("tight", "loose"):
        _, _, internal = stages._scaffold(task, WorkflowConfig(output_root=Path("."), scaffold_mode=scaffold_mode))
        assert _qlip_ordered_orbits_adapter(internal) == internal


@pytest.mark.parametrize(
    ("formula", "expected_species", "expected_wire_formula"),
    [
        ("LiZr2(PO4)3", {"Li", "Zr", "P", "O"}, "Li2Zr4P6O24"),
        ("Na3Zr2Si2PO12", {"Na", "Zr", "Si", "P", "O"}, "Na6Zr4Si4P2O24"),
        ("Na3Ti2(PO4)3", {"Na", "Ti", "P", "O"}, "Na6Ti4P6O24"),
    ],
)
def test_target_formula_species_survive_strict_qlip_serialization(
    formula: str, expected_species: set[str], expected_wire_formula: str,
) -> None:
    from qlip.core.validate import validate_request

    stages = ProductionWorkflowStages()
    task = stages.normalise(formula)
    scaffold_id, structure, internal = stages._scaffold(task, WorkflowConfig(output_root=Path(".")))
    wire = _qlip_ordered_orbits_adapter(internal)
    wire_formula = _qlip_target_formula(task, len(structure))
    required_pairs = stages.required_pairs(task, WorkflowConfig(output_root=Path(".")))
    guidance = [{
        "id": "objective.energy_spp", "weight": 1.0,
        "params": {"mode": "partial", "supported_pairs": required_pairs, "missing_pairs": []},
    }]

    assert set(Composition(task["formula"]).get_el_amt_dict()) == expected_species
    assert wire_formula == expected_wire_formula
    assert set(Composition(wire_formula).get_el_amt_dict()) == expected_species
    assert {row["fixed_species"] for row in wire if row.get("fixed_species")} <= expected_species
    assert {species for pair in required_pairs for species in pair.split("-")} <= expected_species
    _validate_qlip_species_contract(
        formula=wire_formula, ordered_orbits=wire, required_pairs=required_pairs, guidance=guidance,
    )
    request = _request(structure, scaffold_id, wire, formula=wire_formula)
    assert list(Draft202012Validator(_schema()).iter_errors(request)) == []
    report = validate_request(request, strict=True)
    assert not [error for error in report.errors if error.code.startswith("ordered_orbit")]


def test_species_contract_fails_before_qlip_for_source_formula_mismatch() -> None:
    stages = ProductionWorkflowStages()
    task = stages.normalise("LiZr2(PO4)3")
    _, structure, internal = stages._scaffold(task, WorkflowConfig(output_root=Path(".")))
    wire = _qlip_ordered_orbits_adapter(internal)
    required_pairs = stages.required_pairs(task, WorkflowConfig(output_root=Path(".")))
    with pytest.raises(WorkflowStageError) as captured:
        _validate_qlip_species_contract(
            formula=structure.composition.formula.replace(" ", ""),
            ordered_orbits=wire,
            required_pairs=required_pairs,
            guidance=[{"params": {"supported_pairs": required_pairs, "missing_pairs": []}}],
        )
    assert captured.value.stage == "qlip_request_adapter"
    assert captured.value.code == "QLIP_SPECIES_CONTRACT_MISMATCH"
    assert "Li" in captured.value.details["missing_by_source"]["fixed_species"]
