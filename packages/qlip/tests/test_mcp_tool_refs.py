import json

from qlip.mcp import server


def _walk(obj, predicate):
    if predicate(obj):
        return True
    if isinstance(obj, dict):
        return any(_walk(v, predicate) for v in obj.values())
    if isinstance(obj, list):
        return any(_walk(v, predicate) for v in obj)
    return False


def test_tools_list_has_no_qlip_refs():
    tools = server._build_tool_listing()
    payload = [tool.model_dump() for tool in tools]
    assert not _walk(payload, lambda v: isinstance(v, str) and "qlip://" in v)


def test_tools_list_input_schema_lmstudio_shape():
    tools = server._build_tool_listing()
    for tool in tools:
        schema = tool.inputSchema
        assert schema.get("type") == "object"
        assert schema.get("additionalProperties") is False
        assert "$ref" not in json.dumps(schema)
        assert "$defs" not in json.dumps(schema)
