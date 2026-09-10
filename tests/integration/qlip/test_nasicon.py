from __future__ import annotations

import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator

from qlip.scaffolds import ScaffoldCorpusConfigurationError, get_scaffold
from qlip.scaffolds.nasicon import task_orbits
from qlip.scaffolds.occupation import preflight_ordered_occupation


def test_nasicon_adapter_builds_schema_valid_representable_orbits() -> None:
    try:
        scaffold = get_scaffold("nasicon_na3zr2si2po12_c2_ordered")
    except ScaffoldCorpusConfigurationError as exc:
        pytest.skip(f"external NASICON scaffold corpus is not configured: {exc}")

    formula = "Na6Zr4Si4P2O24"
    orbits = task_orbits({"target_formula": formula}, scaffold)
    ordered_orbits = [
        {
            "orbit_id": orbit["orbit_id"],
            "site_indices": orbit["site_indices"],
            "allowed_species": orbit["allowed_species"],
            "required_occupancy": True,
        }
        for orbit in orbits
    ]
    request = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": formula},
            "design_space": {
                "template": {
                    "name": scaffold.scaffold_id,
                    "lattice": {**scaffold.lattice, "units": "angstrom"},
                },
                "sites": {
                    "mode": "explicit_fractional_sites",
                    "explicit_fractional_sites": scaffold.fractional_candidate_sites,
                    "ordered_orbits": ordered_orbits,
                },
            },
            "objective": {"type": "spp_energy"},
        },
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi"},
        "artifacts": {"return_cif": True},
    }

    schema = json.loads(
        files("qlip.resources").joinpath("schemas", "MCP_SCHEMA.json").read_text(encoding="utf-8")
    )["solve_request"]
    assert list(Draft202012Validator(schema).iter_errors(request)) == []
    result = preflight_ordered_occupation(
        formula,
        len(scaffold.fractional_candidate_sites),
        ordered_orbits,
    )
    assert result.stoichiometry_representable
    assert result.vacancy_count == 0
