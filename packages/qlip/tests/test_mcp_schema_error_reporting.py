import importlib.util

import pytest


def test_tool_validation_error_includes_pointer_and_missing_field():
    spec = importlib.util.find_spec("mcp.server.fastmcp")
    if spec is None:
        pytest.skip("mcp SDK not installed")
    from qlip.mcp import server

    result = server.validate_request_tool({})
    assert result["valid"] is False
    assert result["errors"]
    paths = [err["path"] for err in result["errors"]]
    assert any(path.startswith("/problem") or path == "" for path in paths)
    assert any("required" in err["message"] for err in result["errors"])
