from __future__ import annotations

import ast
import inspect
import json
import sys

from sok_llm_orchestrator.agentic import default_agentic_tool_registry
from sok_llm_orchestrator.agentic.tools import TOOL_VALIDATION_SCHEMA_VERSION
import sok_llm_orchestrator.agentic.tools as tools_module


def test_default_registry_lists_expected_tool_names() -> None:
    registry = default_agentic_tool_registry()
    names = [tool["name"] for tool in registry.list_tools()]
    assert names == [
        "crystal.csp_pack",
        "crystal.novelty_check",
        "qlip.solve",
        "qlip.validate_request",
        "spp.package_for_qlip",
        "spp.run_pipeline",
    ]


def test_known_tool_lookup_succeeds() -> None:
    registry = default_agentic_tool_registry()
    tool = registry.get_tool("qlip.solve")
    assert tool.name == "qlip.solve"
    assert registry.has_tool("qlip.solve") is True


def test_unknown_tool_lookup_and_validation_fail_truthfully() -> None:
    registry = default_agentic_tool_registry()
    try:
        registry.get_tool("unknown.tool")
    except KeyError as exc:
        assert "Unknown tool" in str(exc)
    else:
        raise AssertionError("Expected KeyError for unknown tool lookup")

    result = registry.validate_tool_call_proposal(
        {
            "schema_version": "agentic_csp.tool_call_proposal.v1",
            "step": "test",
            "tool_name": "unknown.tool",
            "arguments": {},
            "expected_result": "none",
            "why": "test",
            "condition": None,
        }
    )
    assert result["schema_version"] == TOOL_VALIDATION_SCHEMA_VERSION
    assert result["valid"] is False
    assert result["tool_name"] == "unknown.tool"
    assert result["errors"]


def test_missing_required_arguments_fail() -> None:
    registry = default_agentic_tool_registry()
    result = registry.validate_tool_call_proposal(
        {
            "schema_version": "agentic_csp.tool_call_proposal.v1",
            "step": "test",
            "tool_name": "spp.run_pipeline",
            "arguments": {"case_id": "run_001"},
            "expected_result": "none",
            "why": "test",
            "condition": None,
        }
    )
    assert result["valid"] is False
    assert "corpus_ref" in " ".join(result["errors"])


def test_minimal_valid_proposals_for_all_six_tools_pass_and_are_json_serializable() -> None:
    registry = default_agentic_tool_registry()
    proposals = [
        ("crystal.csp_pack", {"case_id": "run_001", "objective_family": "TiO2"}),
        ("crystal.novelty_check", {"case_id": "run_001"}),
        ("spp.run_pipeline", {"case_id": "run_001", "corpus_ref": "pending_corpus_ref"}),
        ("spp.package_for_qlip", {"case_id": "run_001", "spp_package_ref": "pending_spp_package_ref"}),
        ("qlip.validate_request", {"case_id": "run_001", "request_ref": "pending_request_ref"}),
        ("qlip.solve", {"case_id": "run_001", "validated_request_ref": "pending_validated_request_ref"}),
    ]

    for tool_name, arguments in proposals:
        result = registry.validate_tool_call_proposal(
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "step": f"validate {tool_name}",
                "tool_name": tool_name,
                "arguments": arguments,
                "expected_result": "A proposal-time validation report.",
                "why": "Check request shape before any future execution layer exists.",
                "condition": None,
            }
        )
        assert result["schema_version"] == TOOL_VALIDATION_SCHEMA_VERSION
        assert result["valid"] is True
        assert result["errors"] == []
        assert json.loads(json.dumps(result))["tool_name"] == tool_name


def test_tool_registry_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(tools_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module.split(".")[0])

    assert "sqlite3" not in imported_modules
    assert "sqlalchemy" not in imported_modules
    assert "pipeline" not in imported_modules


def test_tool_registry_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    registry = default_agentic_tool_registry()
    _ = registry.list_tools()
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
