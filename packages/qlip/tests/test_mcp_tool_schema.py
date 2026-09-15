import importlib.util

import pytest


def test_tool_schema_rejects_extra_fields():
    spec = importlib.util.find_spec("mcp.server.fastmcp")
    if spec is None:
        pytest.skip("mcp SDK not installed")
    from qlip.mcp import server

    with pytest.raises(Exception):
        server._validate_tool_input(
            "qlip.list_constraints",
            {"include_params_schema": True, "extra": 1},
        )
