import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from qlip.mcp import server


def _tool_defs():
    path = Path(__file__).resolve().parents[1] / "docs" / "mcp" / "MCP_TOOL_DEFS.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _base_request():
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "SrTiO3"},
            "design_space": {
                "template": {
                    "lattice": {
                        "a": 3.9,
                        "b": 3.9,
                        "c": 3.9,
                        "alpha": 90.0,
                        "beta": 90.0,
                        "gamma": 90.0,
                        "units": "angstrom",
                    }
                },
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}},
            },
        },
        "constraints": [{"id": "proximity.atomic_radii", "params": {"scale": 1.0}}],
        "guidance": [],
        "solver": {"name": "gurobi"},
    }


def test_tool_schemas_are_valid_draft202012():
    tool_defs = _tool_defs()
    for tool in tool_defs:
        Draft202012Validator.check_schema(tool["inputSchema"])
        Draft202012Validator.check_schema(tool["outputSchema"])


def test_tools_list_matches_tool_defs():
    defs = {tool["name"]: tool for tool in _tool_defs()}
    listed = server._build_tool_listing()
    for tool in listed:
        assert tool.name in defs
        assert tool.title == defs[tool.name].get("title")
        assert tool.description == defs[tool.name].get("description", "")
        assert tool.inputSchema.get("type") == "object"
        assert tool.inputSchema.get("additionalProperties") is False
        assert "qlip://" not in json.dumps(tool.inputSchema)
        assert "qlip://" not in json.dumps(tool.outputSchema or {})


def test_validate_request_accepts_wrapper_shape_with_warning():
    result = server.validate_request_tool({"request": _base_request()})
    warnings = result.get("warnings", [])
    assert any(issue.get("code") == "UNWRAPPED_WRAPPER" for issue in warnings)


def test_solve_accepts_wrapper_shape():
    result = server.solve_tool({"request": _base_request()})
    assert "run_id" in result
    assert "result" in result


def test_validate_request_rejects_extra_fields():
    payload = _base_request()
    payload["extra"] = 1
    result = server.validate_request_tool(payload)
    assert result["valid"] is False
    assert result["errors"]
