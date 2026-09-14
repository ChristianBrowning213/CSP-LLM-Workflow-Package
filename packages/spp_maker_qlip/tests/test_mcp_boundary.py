"""Tests for MCP boundary parsing/validation/dispatch hardening."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spp_maker.boundary import (
    BoundaryParseError,
    dispatch_mcp_tool_call,
    filter_unknown_keys,
    normalize_warnings,
    parse_tool_invocation,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lmstudio_payloads"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _sum_runner(tool_name: str, arguments: dict, **_: object) -> int:
    if tool_name != "sum_values":
        raise ValueError(f"unknown tool: {tool_name}")
    return int(arguments["a"]) + int(arguments["b"])


def _schema_registry() -> dict[str, dict]:
    return {
        "sum_values": {
            "type": "object",
            "properties": {
                "a": {"type": "integer", "minimum": 0},
                "b": {"type": "integer", "minimum": 0},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        }
    }


def test_parse_direct_shape_arguments_json_string() -> None:
    payload = _load_fixture("direct_arguments_string.json")
    call, warnings = parse_tool_invocation(payload)

    assert call["tool_name"] == "sum_values"
    assert call["arguments"] == {"a": 2, "b": 3}
    assert isinstance(call["call_id"], str)
    assert call["call_id"].startswith("call_")
    codes = [item["code"] for item in warnings]
    assert "arguments_json_decoded" in codes
    assert "unknown_keys_filtered" in codes


def test_parse_wrapper_shape_with_unknown_keys() -> None:
    payload = _load_fixture("wrapper_with_noise.json")
    call, warnings = parse_tool_invocation(payload)

    assert call["tool_name"] == "sum_values"
    assert call["arguments"] == {"a": 5, "b": 6}
    dropped = [item for item in warnings if item["code"] == "unknown_keys_filtered"]
    assert dropped
    assert any(item.get("path") == "$" for item in dropped)
    assert any(item.get("path") == "$.tool" for item in dropped)


def test_parse_anthropic_nested_tool_use_shape() -> None:
    payload = _load_fixture("anthropic_nested_tool_use.json")
    call, warnings = parse_tool_invocation(payload)

    assert call["tool_name"] == "sum_values"
    assert call["arguments"] == {"a": 8, "b": 13}
    assert call["call_id"] == "call_nested_001"
    assert warnings == [
        {
            "code": "unknown_keys_filtered",
            "message": "unknown keys were filtered from envelope object",
            "path": "$.input[1]",
            "dropped_keys": ["cache_control"],
        }
    ]


def test_parse_rejects_arguments_that_decode_to_non_object() -> None:
    payload = _load_fixture("arguments_non_object.json")
    with pytest.raises(BoundaryParseError) as exc_info:
        parse_tool_invocation(payload)

    error = exc_info.value.error
    assert error["type"] == "parse_error"
    assert error["code"] == "arguments_not_object"


def test_parse_wrong_wrapper_shape_returns_structured_error() -> None:
    payload = _load_fixture("wrong_wrapper_shape.json")
    with pytest.raises(BoundaryParseError) as exc_info:
        parse_tool_invocation(payload)

    error = exc_info.value.error
    assert error["type"] == "parse_error"
    assert error["code"] in {"missing_tool_name", "no_tool_invocation_found"}


def test_filter_unknown_keys_is_copy_and_stable() -> None:
    source = {"z": 0, "a": 1, "m": 2}
    filtered, dropped = filter_unknown_keys(source, {"a", "m"})

    assert filtered == {"a": 1, "m": 2}
    assert dropped == ["z"]
    assert source == {"z": 0, "a": 1, "m": 2}


def test_warning_normalization_dedupes_and_sorts() -> None:
    warnings = [
        {"code": "b", "message": "second", "path": "$.z"},
        {"code": "a", "message": "first", "path": "$.a"},
        {"code": "a", "message": "first", "path": "$.a"},
        {"message": "missing code"},
    ]
    normalized = normalize_warnings(warnings)
    assert normalized == [
        {"code": "a", "message": "first", "path": "$.a"},
        {"code": "b", "message": "second", "path": "$.z"},
        {"code": "warning_unknown", "message": "missing code"},
    ]


def test_dispatch_success_includes_trace_id_and_warnings() -> None:
    payload = _load_fixture("direct_arguments_string.json")
    response = dispatch_mcp_tool_call(
        payload,
        runner=_sum_runner,
        tool_schemas=_schema_registry(),
    )

    assert response["ok"] is True
    assert isinstance(response["trace_id"], str) and response["trace_id"].startswith("trace_")
    assert response["tool_name"] == "sum_values"
    assert response["result"] == 5
    assert response["error"] is None
    assert isinstance(response["warnings"], list)


def test_dispatch_validation_error_is_structured_and_deterministic() -> None:
    payload = {"name": "sum_values", "arguments": {"a": "1", "c": 4}}
    response = dispatch_mcp_tool_call(
        payload,
        runner=_sum_runner,
        tool_schemas=_schema_registry(),
        trace_id="trace_test_validation",
    )

    assert response["ok"] is False
    assert response["trace_id"] == "trace_test_validation"
    assert response["tool_name"] == "sum_values"
    error = response["error"]
    assert error["type"] == "validation_error"
    assert error["tool_name"] == "sum_values"
    assert error["trace_id"] == "trace_test_validation"
    assert [item["path"] for item in error["details"]] == ["$.a", "$.b", "$.c"]
    assert error["hints"] == sorted(error["hints"])


def test_dispatch_parse_error_always_has_trace_id() -> None:
    payload = {"input": "just text without tool invocation"}
    response = dispatch_mcp_tool_call(
        payload,
        runner=_sum_runner,
        tool_schemas=_schema_registry(),
    )

    assert response["ok"] is False
    assert isinstance(response["trace_id"], str) and response["trace_id"].startswith("trace_")
    assert response["tool_name"] is None
    assert response["error"]["type"] == "parse_error"
    assert response["error"]["trace_id"] == response["trace_id"]
    assert isinstance(response["warnings"], list)


def test_dispatch_override_payload_routes_through_boundary() -> None:
    payload = {"input": "no tool here"}
    override_payload = {"name": "sum_values", "arguments": {"a": 10, "b": 20}}
    response = dispatch_mcp_tool_call(
        payload,
        override_payload=override_payload,
        runner=_sum_runner,
        tool_schemas=_schema_registry(),
        trace_id="trace_override",
    )

    assert response["ok"] is True
    assert response["trace_id"] == "trace_override"
    assert response["result"] == 30
    assert any(item["code"] == "override_payload_used" for item in response["warnings"])
