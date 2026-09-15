import json

from qlip.mcp import server


def test_shapes_includes_core_tools():
    result = server.shapes()
    names = {tool["name"] for tool in result["tools"]}
    assert "qlip.list_constraints" in names
    assert "qlip.list_guidance" in names
    assert "qlip.validate_request" in names
    assert "qlip.solve" in names


def test_shapes_entries_have_schema_and_notes():
    result = server.shapes()
    for tool in result["tools"]:
        assert isinstance(tool.get("args_schema"), dict)
        assert isinstance(tool.get("notes"), list)


def test_shapes_omit_examples_by_default():
    result = server.shapes()
    for tool in result["tools"]:
        assert "example_args" not in tool


def test_shapes_filter_single_tool():
    result = server.shapes(tool="qlip.validate_request")
    assert len(result["tools"]) == 1
    assert result["tools"][0]["name"] == "qlip.validate_request"


def test_shapes_validate_request_schema_is_top_level():
    result = server.shapes(tool="qlip.validate_request")
    schema = result["tools"][0]["args_schema"]
    required = schema.get("required", [])
    assert "request" not in required


def test_shapes_output_has_no_qlip_refs_or_unresolvable():
    result = server.shapes(include_examples=True)
    payload = json.dumps(result)
    assert "qlip://" not in payload
    assert "Unresolvable" not in payload
