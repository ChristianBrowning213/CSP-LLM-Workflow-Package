from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic.executor_preflight import (
    EXECUTOR_PREFLIGHT_SCHEMA_VERSION,
    build_executor_preflight,
)
import sok_llm_orchestrator.agentic.executor_preflight as executor_preflight_module


def _execution_handoff(
    *,
    status: str,
    execution_allowed: bool,
    selected_tool_sequence: list[str],
    selected_proposals: list[dict[str, object]],
    blocked_reasons: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.execution_handoff.v1",
        "status": status,
        "execution_intent_status": "ready_for_execution" if status == "ready" else "review_required",
        "execution_allowed": execution_allowed,
        "selected_tool_sequence": selected_tool_sequence,
        "selected_proposals": selected_proposals,
        "preflight_requirements": [
            "executor_available",
            "tool_registry_compatible",
            "operator_allows_execution",
            "workspace_writeable",
        ],
        "blocked_reasons": list(blocked_reasons or []),
        "warnings": list(warnings or []),
        "source_chain_schema_version": "agentic_csp.proposal_review_chain.v1",
        "source_run_id": "run_001",
    }


def test_ready_handoff_with_default_preflight_args_stays_blocked_dry_run() -> None:
    handoff = _execution_handoff(
        status="ready",
        execution_allowed=True,
        selected_tool_sequence=["crystal.csp_pack"],
        selected_proposals=[
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
            }
        ],
    )

    result = build_executor_preflight(handoff)

    assert result["schema_version"] == EXECUTOR_PREFLIGHT_SCHEMA_VERSION
    assert result["status"] == "blocked"
    assert result["execution_allowed"] is False
    assert result["dry_run_only"] is True
    assert "operator_allows_execution" in result["missing_requirements"]
    assert "workspace_writeable" in result["missing_requirements"]
    assert result["selected_tool_sequence"] == ["crystal.csp_pack"]
    assert result["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"


def test_ready_handoff_with_all_checks_true_and_tool_available_passes() -> None:
    handoff = _execution_handoff(
        status="ready",
        execution_allowed=True,
        selected_tool_sequence=["crystal.csp_pack"],
        selected_proposals=[
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
            }
        ],
    )

    result = build_executor_preflight(
        handoff,
        available_tools=["crystal.csp_pack"],
        operator_allows_execution=True,
        workspace_writeable=True,
    )

    assert result["status"] == "pass"
    assert result["execution_allowed"] is True
    assert result["dry_run_only"] is True
    assert result["missing_requirements"] == []
    assert result["selected_tool_sequence"] == ["crystal.csp_pack"]


def test_blocked_handoff_stays_blocked() -> None:
    handoff = _execution_handoff(
        status="blocked",
        execution_allowed=False,
        selected_tool_sequence=[],
        selected_proposals=[],
        blocked_reasons=["Proposal warnings require manual review before execution."],
    )

    result = build_executor_preflight(
        handoff,
        available_tools=["crystal.csp_pack"],
        operator_allows_execution=True,
        workspace_writeable=True,
    )

    assert result["status"] == "blocked"
    assert result["execution_allowed"] is False
    assert "execution_handoff_ready" in result["missing_requirements"]
    assert any("handoff is not ready" in item.lower() for item in result["blocked_reasons"])


def test_missing_tool_blocks_preflight() -> None:
    handoff = _execution_handoff(
        status="ready",
        execution_allowed=True,
        selected_tool_sequence=["crystal.csp_pack"],
        selected_proposals=[
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
            }
        ],
    )

    result = build_executor_preflight(
        handoff,
        available_tools=["spp.run_pipeline"],
        operator_allows_execution=True,
        workspace_writeable=True,
    )

    assert result["status"] == "blocked"
    assert result["execution_allowed"] is False
    assert "tool_registry_compatible" in result["missing_requirements"]


def test_executor_preflight_does_not_mutate_input_and_is_json_serializable() -> None:
    handoff = _execution_handoff(
        status="ready",
        execution_allowed=True,
        selected_tool_sequence=["crystal.csp_pack"],
        selected_proposals=[
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
            }
        ],
    )
    before = deepcopy(handoff)

    result = build_executor_preflight(
        handoff,
        available_tools=["crystal.csp_pack"],
        operator_allows_execution=True,
        workspace_writeable=True,
    )

    assert handoff == before
    assert json.loads(json.dumps(result))["schema_version"] == EXECUTOR_PREFLIGHT_SCHEMA_VERSION


def test_executor_preflight_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(executor_preflight_module)
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


def test_executor_preflight_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = build_executor_preflight(
        _execution_handoff(
            status="ready",
            execution_allowed=True,
            selected_tool_sequence=["crystal.csp_pack"],
            selected_proposals=[{"tool_name": "crystal.csp_pack"}],
        )
    )
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
