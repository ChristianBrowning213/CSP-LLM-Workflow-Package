import json
from pathlib import Path

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


def _warning_codes(response):
    return [item.get("code") for item in response.get("warnings", []) if isinstance(item, dict)]


def _error_codes(response):
    return [item.get("code") for item in response.get("errors", []) if isinstance(item, dict)]


def _assert_envelope(response, expected_tool):
    assert isinstance(response, dict)
    assert set(response.keys()).issuperset({"ok", "tool", "trace_id", "result", "errors", "warnings", "meta"})
    assert response["tool"] == expected_tool
    assert isinstance(response["trace_id"], str) and response["trace_id"]
    assert isinstance(response["errors"], list)
    assert isinstance(response["warnings"], list)
    assert isinstance(response["meta"], dict)
    assert response["meta"].get("trace_id") == response["trace_id"]
    assert isinstance(response["meta"].get("payload_sha256"), str)
    assert isinstance(response["meta"].get("duration_ms"), int)
    assert isinstance(response["meta"].get("warnings_count_by_code"), dict)


def _expand_template(value):
    if isinstance(value, dict):
        if set(value.keys()) == {"$repeat", "count"}:
            return str(value["$repeat"]) * int(value["count"])
        return {k: _expand_template(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_template(item) for item in value]
    return value


def test_trace_id_propagation_and_generation():
    propagated = server._dispatch_tool_call(
        "qlip.shapes",
        {"request_id": 123, "arguments": {"include_examples": True}},
    )
    _assert_envelope(propagated, "qlip.shapes")
    assert propagated["trace_id"] == "123"
    assert propagated["meta"]["trace_id"] == "123"

    generated = server._dispatch_tool_call("qlip.shapes", {"arguments": {"include_examples": True}})
    _assert_envelope(generated, "qlip.shapes")
    assert generated["trace_id"]
    assert generated["trace_id"] != "123"


def test_payload_sha256_stable():
    payload_a = {"arguments": {"include_examples": True, "tool": "qlip.shapes"}}
    payload_b = {"arguments": {"tool": "qlip.shapes", "include_examples": True}}
    result_a = server._dispatch_tool_call("qlip.shapes", payload_a)
    result_b = server._dispatch_tool_call("qlip.shapes", payload_b)
    _assert_envelope(result_a, "qlip.shapes")
    _assert_envelope(result_b, "qlip.shapes")
    assert result_a["meta"]["payload_sha256"] == result_b["meta"]["payload_sha256"]


def test_uniform_response_envelope_success():
    result = server._dispatch_tool_call("qlip.shapes", {"arguments": {"include_examples": True}})
    _assert_envelope(result, "qlip.shapes")
    assert result["ok"] is True
    assert result["result"] is not None
    assert "tools" in result["result"]


def test_uniform_response_envelope_error():
    result = server._dispatch_tool_call("qlip.shapes", {"arguments": "{include_examples: true}"})
    _assert_envelope(result, "qlip.shapes")
    assert result["ok"] is False
    assert result["result"] is None
    assert result["errors"]
    assert result.get("primary_error") == result["errors"][0]


def test_warning_object_contract():
    result = server._dispatch_tool_call(
        "qlip.list_constraints",
        {"arguments": {"ids": {}, "junk": 123}},
    )
    _assert_envelope(result, "qlip.list_constraints")
    assert result["ok"] is True
    assert result["warnings"]
    for warning in result["warnings"]:
        assert set(warning.keys()).issuperset({"code", "message", "severity"})
        assert warning["severity"] in {"INFO", "WARN"}
    counts = result["meta"]["warnings_count_by_code"]
    assert isinstance(counts, dict) and counts


def test_string_len_limit_exceeded():
    result = server._dispatch_tool_call(
        "qlip.shapes",
        {"arguments": {"tool": "x" * 70000}},
    )
    _assert_envelope(result, "qlip.shapes")
    assert result["ok"] is False
    assert result["errors"][0]["code"] == "PAYLOAD_LIMIT_EXCEEDED"
    assert result["errors"][0].get("meta", {}).get("which_limit") == "STRING_LEN"


def test_total_string_bytes_limit_exceeded():
    result = server._dispatch_tool_call(
        "qlip.shapes",
        {
            "arguments": {
                "a": "x" * 60000,
                "b": "x" * 60000,
                "c": "x" * 60000,
                "d": "x" * 60000,
                "e": "x" * 60000,
            }
        },
    )
    _assert_envelope(result, "qlip.shapes")
    assert result["ok"] is False
    assert result["errors"][0]["code"] == "PAYLOAD_LIMIT_EXCEEDED"
    assert result["errors"][0].get("meta", {}).get("which_limit") == "STRING_TOTAL_BYTES"


def test_metadata_tools_drop_unknown_args_warn():
    shapes_result = server._dispatch_tool_call(
        "qlip.shapes",
        {"arguments": {"include_examples": True, "junk": 1}},
    )
    _assert_envelope(shapes_result, "qlip.shapes")
    assert shapes_result["ok"] is True
    assert "UNKNOWN_ARG_DROPPED" in _warning_codes(shapes_result)

    list_result = server._dispatch_tool_call(
        "qlip.list_constraints",
        {"arguments": {"ids": [], "junk": 123}},
    )
    _assert_envelope(list_result, "qlip.list_constraints")
    assert list_result["ok"] is True
    assert "UNKNOWN_ARG_DROPPED" in _warning_codes(list_result)


def test_validate_solve_keep_unknown_args_strict():
    invalid_validate = _base_request()
    invalid_validate["junk"] = 1
    validate_result = server._dispatch_tool_call("qlip.validate_request", invalid_validate)
    _assert_envelope(validate_result, "qlip.validate_request")
    assert validate_result["ok"] is False
    assert any(error.get("pointer") == "/junk" for error in validate_result["errors"])

    invalid_solve = _base_request()
    invalid_solve["junk"] = 1
    solve_result = server._dispatch_tool_call("qlip.solve", invalid_solve)
    _assert_envelope(solve_result, "qlip.solve")
    assert solve_result["ok"] is False
    assert any(error.get("pointer") == "/junk" for error in solve_result["errors"])


def test_openai_tool_calls_extraction_ok():
    payload = {
        "tool_calls": [
            {
                "function": {
                    "name": "qlip.shapes",
                    "arguments": {"include_examples": True},
                }
            }
        ]
    }
    result = server._dispatch_tool_call("qlip.shapes", payload)
    _assert_envelope(result, "qlip.shapes")
    assert result["ok"] is True
    assert "tools" in result["result"]


def test_function_arguments_json_string_ok():
    payload = {
        "function": {
            "name": "qlip.shapes",
            "arguments": "{\"include_examples\": true}",
        }
    }
    result = server._dispatch_tool_call("qlip.shapes", payload)
    _assert_envelope(result, "qlip.shapes")
    assert result["ok"] is True
    assert "COERCED_JSON_STRING_ARGS" in _warning_codes(result)


def test_unknown_tool_name_suggests():
    payload = {
        "function": {
            "name": "qlip.shapess",
            "arguments": {},
        }
    }
    result = server._dispatch_tool_call("qlip.shapes", payload)
    _assert_envelope(result, "qlip.shapess")
    assert result["ok"] is False
    assert result["errors"][0]["code"] == "UNKNOWN_TOOL_NAME"
    assert "qlip.shapes" in result["errors"][0].get("meta", {}).get("suggestions", [])


def test_multiple_tool_calls_warns():
    payload = {
        "tool_calls": [
            {"function": {"name": "qlip.shapes", "arguments": {"include_examples": True}}},
            {"function": {"name": "qlip.list_constraints", "arguments": {}}},
        ]
    }
    result = server._dispatch_tool_call("qlip.shapes", payload)
    _assert_envelope(result, "qlip.shapes")
    assert result["ok"] is True
    assert "MULTIPLE_TOOL_CALLS" in _warning_codes(result)


def test_errors_sorted_and_primary_error_present():
    result = server._dispatch_tool_call("qlip.validate_request", {})
    _assert_envelope(result, "qlip.validate_request")
    assert result["ok"] is False
    errors = result["errors"]
    assert errors
    assert result.get("primary_error") == errors[0]
    assert errors == sorted(
        errors,
        key=lambda issue: (
            issue.get("pointer", ""),
            issue.get("code", ""),
            issue.get("message", ""),
        ),
    )


def test_unknown_plugin_id_enriched_metadata():
    payload = _base_request()
    payload["constraints"] = [{"id": "proximity.atomic_radiai", "params": {}}]
    result = server._dispatch_tool_call("qlip.validate_request", payload)
    _assert_envelope(result, "qlip.validate_request")
    assert result["ok"] is False
    plugin_errors = [item for item in result["errors"] if item.get("code") == "UNKNOWN_PLUGIN_ID"]
    assert plugin_errors
    meta = plugin_errors[0].get("meta", {})
    assert meta.get("registry") == "constraints"
    assert isinstance(meta.get("registry_version"), str)
    assert isinstance(meta.get("allowed_count"), int)
    assert isinstance(meta.get("sample_allowed"), list)
    assert len(meta.get("sample_allowed")) <= 25


def test_category_retryable_fields_for_representative_errors():
    format_result = server._dispatch_tool_call("qlip.shapes", {"function": {"name": "qlip.shapess", "arguments": {}}})
    _assert_envelope(format_result, "qlip.shapess")
    assert format_result["meta"]["category"] == "FORMAT"
    assert format_result["meta"]["retryable"] is True

    limit_result = server._dispatch_tool_call("qlip.shapes", {"arguments": {"tool": "x" * 70000}})
    _assert_envelope(limit_result, "qlip.shapes")
    assert limit_result["meta"]["category"] == "LIMIT"
    assert limit_result["meta"]["retryable"] is True

    schema_result = server._dispatch_tool_call("qlip.validate_request", {})
    _assert_envelope(schema_result, "qlip.validate_request")
    assert schema_result["meta"]["category"] == "SCHEMA"
    assert schema_result["meta"]["retryable"] is True

    plugin_payload = _base_request()
    plugin_payload["constraints"] = [{"id": "proximity.atomic_radiai", "params": {}}]
    plugin_result = server._dispatch_tool_call("qlip.validate_request", plugin_payload)
    _assert_envelope(plugin_result, "qlip.validate_request")
    assert plugin_result["meta"]["category"] == "PLUGIN"
    assert plugin_result["meta"]["retryable"] is True


def test_shapes_hints_presence_and_policy():
    result = server._dispatch_tool_call("qlip.shapes", {"arguments": {"include_examples": False}})
    _assert_envelope(result, "qlip.shapes")
    assert result["ok"] is True
    tools = result["result"]["tools"]
    assert tools
    by_name = {entry["name"]: entry for entry in tools}
    for entry in tools:
        assert isinstance(entry.get("strict_schema"), bool)
        assert isinstance(entry.get("boundary_accepts_envelopes"), list)
        assert entry.get("boundary_unknown_arg_policy") in {"drop_with_warning", "error"}
        assert isinstance(entry.get("canonical_args_example"), dict)
    assert by_name["qlip.shapes"]["boundary_unknown_arg_policy"] == "drop_with_warning"
    assert by_name["qlip.list_constraints"]["boundary_unknown_arg_policy"] == "drop_with_warning"
    assert by_name["qlip.validate_request"]["boundary_unknown_arg_policy"] == "error"
    assert by_name["qlip.solve"]["boundary_unknown_arg_policy"] == "error"


def test_debug_boundary_parse_extraction_and_hash_stability():
    payload_a = {
        "arguments": {
            "payload": {"function": {"name": "qlip.shapes", "arguments": "{\"include_examples\": true}"}}
        }
    }
    payload_b = {
        "arguments": {
            "payload": {"function": {"arguments": "{\"include_examples\": true}", "name": "qlip.shapes"}}
        }
    }
    result_a = server._dispatch_tool_call("qlip.debug_boundary_parse", payload_a)
    result_b = server._dispatch_tool_call("qlip.debug_boundary_parse", payload_b)
    _assert_envelope(result_a, "qlip.debug_boundary_parse")
    _assert_envelope(result_b, "qlip.debug_boundary_parse")
    assert result_a["ok"] is True
    assert result_b["ok"] is True
    assert result_a["result"]["extracted_tool_name"] == "qlip.shapes"
    assert result_a["result"]["parsed_args"] == {"include_examples": True}
    assert "COERCED_JSON_STRING_ARGS" in [w["code"] for w in result_a["result"]["warnings"]]
    assert result_a["result"]["payload_sha256"] == result_b["result"]["payload_sha256"]


def test_no_error_dump_by_default(tmp_path, monkeypatch):
    dump_path = tmp_path / "qlip_dump.jsonl"
    monkeypatch.delenv("QLIP_MCP_DUMP_ERRORS", raising=False)
    monkeypatch.setenv("QLIP_MCP_DUMP_ERRORS_PATH", str(dump_path))

    result = server._dispatch_tool_call("qlip.shapes", {"arguments": "{include_examples: true}"})
    _assert_envelope(result, "qlip.shapes")
    assert result["ok"] is False
    assert not dump_path.exists()


def test_doc_example_fixture_linked():
    doc_path = Path(__file__).resolve().parents[1] / "docs" / "MCP_CLIENT_CONTRACT.md"
    doc_text = doc_path.read_text(encoding="utf-8")
    assert "tests/fixtures/lmstudio_payloads/08_tool_calls_openai_style.json" in doc_text

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "lmstudio_payloads" / "08_tool_calls_openai_style.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    response = server._dispatch_tool_call(fixture["tool"], fixture["payload"])
    _assert_envelope(response, "qlip.shapes")
    assert response["ok"] is True


def test_skillpack_good_fixture_round_trip():
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "qlip_mcp_boundary_v5"
        / "fixtures"
        / "good.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    request = fixture["request"]
    expected = fixture["expected"]
    dispatch_tool = expected["dispatch_tool"]

    response = server._dispatch_tool_call(dispatch_tool, request)
    _assert_envelope(response, expected["tool"])
    assert response["ok"] is bool(expected["ok"])
    assert (isinstance(response.get("trace_id"), str) and bool(response["trace_id"])) is bool(
        expected["has_trace_id"]
    )
    assert set(expected.get("expected_warning_codes", [])).issubset(set(_warning_codes(response)))


def test_lmstudio_fixture_corpus():
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "lmstudio_payloads"
    fixture_paths = sorted(fixture_dir.glob("*.json"))
    assert fixture_paths

    for fixture_path in fixture_paths:
        case = json.loads(fixture_path.read_text(encoding="utf-8"))
        payload = _expand_template(case.get("payload"))
        response = server._dispatch_tool_call(case["tool"], payload)
        _assert_envelope(response, response["tool"])

        expected_mode = case["expect"]
        if expected_mode == "success":
            assert response["ok"] is True
            assert response["errors"] == []
            assert response["result"] is not None
        else:
            assert response["ok"] is False
            assert response["errors"]
            assert response["result"] is None
            if "expected_first_code" in case:
                assert response["errors"][0]["code"] == case["expected_first_code"]
            if "expected_first_pointer" in case:
                assert response["errors"][0]["pointer"] == case["expected_first_pointer"]
            if "expected_first_hint" in case:
                assert case["expected_first_hint"] in response["errors"][0].get("hint", "")
            if "expected_which_limit" in case:
                assert response["errors"][0].get("meta", {}).get("which_limit") == case["expected_which_limit"]
            if "expected_contains_suggestion" in case:
                suggestions = response["errors"][0].get("meta", {}).get("suggestions", [])
                assert case["expected_contains_suggestion"] in suggestions

        expected_warning_codes = set(case.get("expected_warning_codes", []))
        if expected_warning_codes:
            assert expected_warning_codes.issubset(set(_warning_codes(response)))
