import pytest

from qlip.mcp import server


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
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi"},
    }


@pytest.mark.parametrize(
    "payload, expect_warn",
    [
        ({}, False),
        ({"ids": None}, True),
        ({"tags_any": ""}, True),
        ({"ids": {}}, True),
        ({"tags_any": {}}, True),
        ({"ids": {"ids": []}}, True),
        ({"tags_any": {"tags_any": ["feasibility"]}}, True),
        ({"ids": "proximity.atomic_radii"}, True),
        ({"include_params_schema": "false"}, True),
    ],
)
def test_list_constraints_normalization(payload, expect_warn, capsys):
    result = server._run_tool("qlip.list_constraints", payload, server._list_constraints_impl)
    assert "items" in result
    stderr = capsys.readouterr().err
    assert ("[mcp-normalize]" in stderr) is expect_warn


@pytest.mark.parametrize(
    "payload, expect_warn",
    [
        ({}, False),
        ({"ids": None}, True),
        ({"tags_any": ""}, True),
        ({"ids": {}}, True),
        ({"tags_any": {}}, True),
        ({"ids": {"ids": []}}, True),
        ({"tags_any": {"tags_any": ["objective"]}}, True),
        ({"tags_any": "objective"}, True),
        ({"include_params_schema": "true"}, True),
    ],
)
def test_list_guidance_normalization(payload, expect_warn, capsys):
    result = server._run_tool("qlip.list_guidance", payload, server._list_guidance_impl)
    assert "items" in result
    stderr = capsys.readouterr().err
    assert ("[mcp-normalize]" in stderr) is expect_warn


def test_validate_request_unwraps_request_wrapper():
    result = server.validate_request_tool({"request": _base_request()})
    warnings = result.get("warnings", [])
    assert any(warn.get("code") == "UNWRAPPED_WRAPPER" for warn in warnings)


def test_validate_request_unwraps_solve_request_wrapper():
    result = server.validate_request_tool({"SolveRequest": _base_request()})
    warnings = result.get("warnings", [])
    assert any(warn.get("code") == "UNWRAPPED_WRAPPER" for warn in warnings)


def test_validate_request_unwraps_payload_wrapper():
    result = server.validate_request_tool({"payload": _base_request()})
    warnings = result.get("warnings", [])
    assert any(warn.get("code") == "UNWRAPPED_WRAPPER" for warn in warnings)


def test_validate_request_does_not_unwrap_ambiguous_wrapper():
    result = server.validate_request_tool({"request": _base_request(), "extra": 1})
    warnings = result.get("warnings", [])
    assert all(warn.get("code") != "UNWRAPPED_WRAPPER" for warn in warnings)
    assert result["valid"] is False


def test_shapes_accepts_stringified_include_examples():
    result = server.shapes(include_examples="true")
    tools = result.get("tools", [])
    assert tools
    assert all("example_args" in tool for tool in tools)


def test_shapes_drops_empty_include_examples(capsys):
    result = server.shapes(include_examples={})
    tools = result.get("tools", [])
    assert tools
    assert all("example_args" not in tool for tool in tools)
    stderr = capsys.readouterr().err
    assert "[mcp-normalize]" in stderr


def test_shapes_accepts_numeric_string_include_examples():
    result = server.shapes(include_examples="1")
    tools = result.get("tools", [])
    assert tools
    assert all("example_args" in tool for tool in tools)


def test_validate_request_coerces_solver_time_limit(capsys):
    req = _base_request()
    req["solver"]["time_limit_s"] = "60"
    result = server.validate_request_tool(req)
    warnings = result.get("warnings", [])
    assert any(warn.get("path") == "/solver/time_limit_s" for warn in warnings)
    assert "[mcp-normalize]" in capsys.readouterr().err


def test_validate_request_coerces_lattice_a():
    req = _base_request()
    req["problem"]["design_space"]["template"]["lattice"]["a"] = "3.9"
    result = server.validate_request_tool(req)
    warnings = result.get("warnings", [])
    assert any(
        warn.get("path") == "/problem/design_space/template/lattice/a" for warn in warnings
    )


def test_validate_request_coerces_uniform_grid_density():
    req = _base_request()
    req["problem"]["design_space"]["sites"]["uniform_grid"]["density"] = "4"
    result = server.validate_request_tool(req)
    warnings = result.get("warnings", [])
    assert any(
        warn.get("path") == "/problem/design_space/sites/uniform_grid/density"
        for warn in warnings
    )


def test_validate_request_coerces_artifacts_return_cif():
    req = _base_request()
    req["artifacts"] = {"return_cif": "false"}
    result = server.validate_request_tool(req)
    warnings = result.get("warnings", [])
    assert any(warn.get("path") == "/artifacts/return_cif" for warn in warnings)


def test_plugin_params_not_coerced():
    req = _base_request()
    req["constraints"] = [{"id": "proximity.atomic_radii", "params": {"scale": "1.0"}}]
    result = server.validate_request_tool(req)
    warnings = result.get("warnings", [])
    assert all("/constraints/0/params/scale" != warn.get("path") for warn in warnings)
    codes = {err["code"] for err in result.get("errors", [])}
    assert "invalid_constraint_params" in codes


def test_list_unknown_keys_are_not_dropped():
    with pytest.raises(Exception):
        server._run_tool("qlip.list_constraints", {"unknown": 1}, server._list_constraints_impl)
