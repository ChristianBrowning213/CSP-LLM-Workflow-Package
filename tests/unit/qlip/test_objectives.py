from __future__ import annotations

import copy
import json
from importlib.resources import files

import pyomo.environ as pyo
from ase import Atoms
from jsonschema import Draft202012Validator

from qlip.allocation import Allocation
from qlip.core.models import SolveOutputs, SolveResult, SolveSummary
from qlip.core.objectives import apply_objective_contract, validate_objective_contract
from qlip.core.solve import _build_positions
from qlip.mcp import server
from tests.qlip_support.solve_test_support import DummySPP, assign_sequential_solution, base_request


def _schema_validator():
    schema = json.loads(files("qlip.resources").joinpath("schemas", "MCP_SCHEMA.json").read_text())
    return Draft202012Validator(schema["solve_request"])


def _request_with_objective(objective: dict):
    req = base_request("SrTiO3", density=2)
    req["problem"]["objective"] = copy.deepcopy(objective)
    return req


def _assert_schema_accepts(objective: dict) -> None:
    errors = sorted(_schema_validator().iter_errors(_request_with_objective(objective)), key=str)
    assert errors == []


def _compile_objective(objective: dict):
    req = _request_with_objective(objective)
    allocation = Allocation(Atoms(symbols=req["problem"]["chemistry"]["formula"]))
    allocation.positions = _build_positions(req["problem"]["design_space"])
    allocation.cost = DummySPP()
    allocation.encode()
    family = apply_objective_contract(allocation, objective)
    return allocation, family


def _linear_property(name: str = "property_x_estimate") -> dict:
    return {
        "name": name,
        "offset": 0.25,
        "terms": [
            {"species": "Sr", "site": 0, "coefficient": 2.0},
            {"species": "O", "coefficient": 0.5},
            {"site": 3, "coefficient": -1.0},
        ],
    }


def test_runtime_request_schema_accepts_objective_families():
    _assert_schema_accepts({"type": "spp_energy"})
    _assert_schema_accepts(
        {"type": "density_packing", "direction": "maximize", "proxy": "pair_distance_packing"}
    )
    _assert_schema_accepts(
        {"type": "linear_property", "direction": "minimize", "property": _linear_property()}
    )
    _assert_schema_accepts(
        {
            "type": "threshold_tradeoff",
            "base_objective": "spp_energy",
            "property": _linear_property("threshold_x"),
            "threshold": {"sense": ">=", "value": 1.0},
            "tradeoff_direction": "maximize",
            "tradeoff_weight": 0.2,
        }
    )


def test_runtime_objective_dispatch_compiles_density_packing():
    allocation, family = _compile_objective(
        {"type": "density_packing", "direction": "maximize", "proxy": "pair_distance_packing"}
    )

    assert family == "density_packing"
    assert allocation.m.obj.expr.polynomial_degree() == 2


def test_runtime_objective_dispatch_compiles_linear_property():
    allocation, family = _compile_objective(
        {"type": "linear_property", "direction": "maximize", "property": _linear_property()}
    )
    assign_sequential_solution(allocation)

    assert family == "linear_property"
    assert allocation.m.obj.expr.polynomial_degree() == 1
    assert hasattr(allocation.m, "qprop_property_x_estimate")
    assert pyo.value(allocation.m.obj.expr) < 0


def test_runtime_objective_dispatch_compiles_threshold_tradeoff():
    allocation, family = _compile_objective(
        {
            "type": "threshold_tradeoff",
            "base_objective": "spp_energy",
            "property": _linear_property("threshold_x"),
            "threshold": {"sense": ">=", "value": 1.0},
            "tradeoff_direction": "maximize",
            "tradeoff_weight": 0.2,
        }
    )

    assert family == "threshold_tradeoff"
    assert hasattr(allocation.m, "qprop_threshold_x")
    assert hasattr(allocation.m, "qlip_threshold_tradeoff_bound")
    assert allocation.m.obj.expr.polynomial_degree() >= 1


def test_invalid_mixed_objective_guidance_fails_clearly():
    issues = validate_objective_contract(
        {"type": "linear_property", "direction": "minimize", "property": _linear_property()},
        species=["Sr", "Ti", "O"],
        site_count=8,
        guidance=[{"id": "objective.energy_spp", "params": {}, "enabled": True}],
    )

    assert [issue.code for issue in issues] == ["invalid_objective_guidance_mix"]
    assert issues[0].path == "/guidance"


def test_invalid_linear_property_identifier_fails_clearly():
    issues = validate_objective_contract(
        {
            "type": "linear_property",
            "direction": "minimize",
            "property": {"terms": [{"species": "Ba", "site": 100, "coefficient": 1.0}]},
        },
        species=["Sr", "Ti", "O"],
        site_count=8,
        guidance=[],
    )
    codes = {issue.code for issue in issues}

    assert "unknown_objective_species" in codes
    assert "objective_site_out_of_range" in codes


def test_mcp_solve_path_preserves_new_objective_family_fields(monkeypatch):
    captured = {}

    def _fake_core_solve(payload):
        captured["objective"] = payload["problem"]["objective"]
        return SolveResult(
            status="OPTIMAL",
            summary=SolveSummary(solver="gurobi", timing_ms=1, termination="optimal"),
            outputs=SolveOutputs(cif="data_test"),
        )

    monkeypatch.setattr(server, "core_solve", _fake_core_solve)
    request = _request_with_objective(
        {"type": "linear_property", "direction": "minimize", "property": _linear_property()}
    )

    result = server._dispatch_tool_call("qlip.solve", request)

    assert result["ok"] is True
    assert result["result"]["result"]["status"] == "OPTIMAL"
    assert captured["objective"]["type"] == "linear_property"
    assert captured["objective"]["property"]["terms"][0]["species"] == "Sr"
