import importlib.util

import pytest


def test_tool_schema_ref_resolution_handles_defs_refs():
    spec = importlib.util.find_spec("mcp.server.fastmcp")
    if spec is None:
        pytest.skip("mcp SDK not installed")
    from qlip.mcp import server

    result = server.validate_request_tool({})
    assert result["valid"] is False
    assert result["errors"]
    assert all("Unresolvable JSON pointer" not in err["message"] for err in result["errors"])
