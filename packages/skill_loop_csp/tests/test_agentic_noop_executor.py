from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic.noop_executor import (
    NOOP_EXECUTION_REPORT_SCHEMA_VERSION,
    build_noop_execution_report,
)
import sok_llm_orchestrator.agentic.noop_executor as noop_executor_module


def _preflight_pass() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.executor_preflight.v1",
        "status": "pass",
        "execution_allowed": True,
        "dry_run_only": True,
        "checked_requirements": [
            "execution_handoff_ready",
            "operator_allows_execution",
            "workspace_writeable",
            "tool_registry_compatible",
        ],
        "missing_requirements": [],
        "blocked_reasons": [],
        "selected_tool_sequence": ["crystal.csp_pack"],
        "selected_proposals": [
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {"case_id": "run_001", "objective_family": "retrieval"},
                "expected_result": "Ranked candidate set with exportability metadata.",
            }
        ],
        "warnings": [],
    }


def _preflight_blocked() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.executor_preflight.v1",
        "status": "blocked",
        "execution_allowed": False,
        "dry_run_only": True,
        "checked_requirements": [
            "execution_handoff_ready",
            "operator_allows_execution",
            "workspace_writeable",
        ],
        "missing_requirements": ["operator_allows_execution"],
        "blocked_reasons": ["Operator approval for execution is not enabled."],
        "selected_tool_sequence": ["crystal.csp_pack"],
        "selected_proposals": [
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {"case_id": "run_001", "objective_family": "retrieval"},
                "expected_result": "Ranked candidate set with exportability metadata.",
            }
        ],
        "warnings": ["Review before execution."],
    }


def test_build_noop_execution_report_would_execute_when_preflight_passes() -> None:
    preflight = _preflight_pass()
    before = deepcopy(preflight)

    result = build_noop_execution_report(preflight)

    assert preflight == before
    assert result["schema_version"] == NOOP_EXECUTION_REPORT_SCHEMA_VERSION
    assert result["mode"] == "noop_dry_run"
    assert result["status"] == "would_execute"
    assert result["execution_performed"] is False
    assert result["dry_run_only"] is True
    assert result["selected_tool_sequence"] == ["crystal.csp_pack"]
    assert result["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert result["would_call_tools"] == ["crystal.csp_pack"]
    assert result["blocked_reasons"] == []
    assert json.loads(json.dumps(result))["status"] == "would_execute"


def test_build_noop_execution_report_blocks_when_preflight_is_blocked() -> None:
    preflight = _preflight_blocked()

    result = build_noop_execution_report(preflight)

    assert result["status"] == "blocked"
    assert result["execution_performed"] is False
    assert result["dry_run_only"] is True
    assert result["would_call_tools"] == []
    assert result["blocked_reasons"] == [
        "Operator approval for execution is not enabled."
    ]
    assert result["warnings"] == ["Review before execution."]
    assert result["selected_tool_sequence"] == ["crystal.csp_pack"]
    assert result["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"


def test_noop_executor_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(noop_executor_module)
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


def test_noop_executor_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    assert "sok_llm_orchestrator.pipeline" not in sys.modules
