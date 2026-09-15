from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic.execution_handoff import (
    DEFAULT_PREFLIGHT_REQUIREMENTS,
    EXECUTION_HANDOFF_SCHEMA_VERSION,
    build_execution_handoff,
)
import sok_llm_orchestrator.agentic.execution_handoff as execution_handoff_module


def _chain_result(
    *,
    execution_allowed: bool,
    execution_intent_status: str,
    selected_proposals: list[dict[str, object]],
    blocked_reasons: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.proposal_review_chain.v1",
        "run_id": "run_001",
        "execution_intent": {
            "schema_version": "agentic_csp.execution_intent.v1",
            "status": execution_intent_status,
            "selected_proposals": selected_proposals,
            "blocked_reasons": list(blocked_reasons or []),
            "warnings": list(warnings or []),
            "execution_allowed": execution_allowed,
        },
    }


def test_build_execution_handoff_ready_when_execution_is_allowed() -> None:
    chain_result = _chain_result(
        execution_allowed=True,
        execution_intent_status="ready_for_execution",
        selected_proposals=[
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {
                    "case_id": "run-plan-compile",
                    "objective_family": "TiO2",
                },
            }
        ],
    )

    result = build_execution_handoff(chain_result)

    assert result["schema_version"] == EXECUTION_HANDOFF_SCHEMA_VERSION
    assert result["status"] == "ready"
    assert result["execution_allowed"] is True
    assert result["execution_intent_status"] == "ready_for_execution"
    assert result["selected_tool_sequence"] == ["crystal.csp_pack"]
    assert result["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert result["preflight_requirements"] == DEFAULT_PREFLIGHT_REQUIREMENTS
    assert result["blocked_reasons"] == []
    assert result["source_chain_schema_version"] == "agentic_csp.proposal_review_chain.v1"
    assert result["source_run_id"] == "run_001"


def test_build_execution_handoff_blocked_when_execution_is_not_allowed() -> None:
    chain_result = _chain_result(
        execution_allowed=False,
        execution_intent_status="review_required",
        selected_proposals=[
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {
                    "case_id": "run-plan-compile",
                    "objective_family": "TiO2",
                },
            }
        ],
        blocked_reasons=["Proposal warnings require manual review before execution."],
        warnings=["Manual review recommended"],
    )

    result = build_execution_handoff(chain_result)

    assert result["status"] == "blocked"
    assert result["execution_allowed"] is False
    assert result["execution_intent_status"] == "review_required"
    assert result["selected_tool_sequence"] == []
    assert result["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert result["blocked_reasons"] == [
        "Proposal warnings require manual review before execution."
    ]
    assert result["warnings"] == ["Manual review recommended"]


def test_build_execution_handoff_does_not_mutate_input_and_is_json_serializable() -> None:
    chain_result = _chain_result(
        execution_allowed=True,
        execution_intent_status="ready_for_execution",
        selected_proposals=[
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {"case_id": "run-plan-compile"},
            }
        ],
    )
    before = deepcopy(chain_result)

    result = build_execution_handoff(chain_result)

    assert chain_result == before
    assert json.loads(json.dumps(result))["schema_version"] == EXECUTION_HANDOFF_SCHEMA_VERSION


def test_execution_handoff_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(execution_handoff_module)
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


def test_execution_handoff_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = build_execution_handoff(
        _chain_result(
            execution_allowed=False,
            execution_intent_status="blocked_no_proposals",
            selected_proposals=[],
            blocked_reasons=["No tool proposals are available for execution review."],
        )
    )
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
