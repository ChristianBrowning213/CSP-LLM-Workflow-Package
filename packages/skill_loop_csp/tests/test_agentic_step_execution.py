from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic.step_execution import (
    NOOP_STEP_EXECUTION_SCHEMA_VERSION,
    STEP_EXECUTION_PLAN_SCHEMA_VERSION,
    build_step_execution_plan,
    run_noop_step_execution,
)
import sok_llm_orchestrator.agentic.step_execution as step_execution_module


def _ready_handoff() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.execution_handoff.v1",
        "status": "ready",
        "execution_intent_status": "ready_for_execution",
        "execution_allowed": True,
        "selected_tool_sequence": ["crystal.csp_pack"],
        "selected_proposals": [
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {
                    "case_id": "run_001",
                    "objective_family": "retrieval",
                },
                "expected_result": "Ranked candidate set with exportability metadata.",
            }
        ],
        "preflight_requirements": [
            "executor_available",
            "tool_registry_compatible",
            "operator_allows_execution",
            "workspace_writeable",
        ],
        "blocked_reasons": [],
        "warnings": [],
        "source_chain_schema_version": "agentic_csp.proposal_review_chain.v1",
        "source_run_id": "run_001",
    }


def _blocked_handoff() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.execution_handoff.v1",
        "status": "blocked",
        "execution_intent_status": "blocked_no_proposals",
        "execution_allowed": False,
        "selected_tool_sequence": [],
        "selected_proposals": [],
        "preflight_requirements": [
            "executor_available",
            "tool_registry_compatible",
            "operator_allows_execution",
            "workspace_writeable",
        ],
        "blocked_reasons": ["No tool proposals are available for execution review."],
        "warnings": [],
        "source_chain_schema_version": "agentic_csp.proposal_review_chain.v1",
        "source_run_id": "run_001",
    }


def test_build_step_execution_plan_ready_handoff_creates_pending_step() -> None:
    handoff = _ready_handoff()
    before = deepcopy(handoff)

    result = build_step_execution_plan(handoff)

    assert handoff == before
    assert result["schema_version"] == STEP_EXECUTION_PLAN_SCHEMA_VERSION
    assert result["status"] == "ready"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["step_index"] == 0
    assert result["steps"][0]["tool_name"] == "crystal.csp_pack"
    assert result["steps"][0]["expected_mode"] == "noop_dry_run"
    assert result["steps"][0]["status"] == "pending"
    assert json.loads(json.dumps(result))["steps"][0]["tool_name"] == "crystal.csp_pack"


def test_build_step_execution_plan_blocked_handoff_has_no_steps() -> None:
    result = build_step_execution_plan(_blocked_handoff())

    assert result["status"] == "blocked"
    assert result["steps"] == []
    assert result["blocked_reasons"] == [
        "No tool proposals are available for execution review."
    ]


def test_run_noop_step_execution_converts_pending_step_to_would_execute() -> None:
    plan = build_step_execution_plan(_ready_handoff())
    before = deepcopy(plan)

    result = run_noop_step_execution(plan)

    assert plan == before
    assert result["schema_version"] == NOOP_STEP_EXECUTION_SCHEMA_VERSION
    assert result["execution_performed"] is False
    assert result["status"] == "completed"
    assert result["step_results"][0]["tool_name"] == "crystal.csp_pack"
    assert result["step_results"][0]["status"] == "would_execute"
    assert result["step_results"][0]["result_summary"] == "noop dry run only"


def test_run_noop_step_execution_blocked_plan_stays_blocked() -> None:
    plan = build_step_execution_plan(_blocked_handoff())

    result = run_noop_step_execution(plan)

    assert result["execution_performed"] is False
    assert result["status"] == "blocked"
    assert result["step_results"] == []


def test_step_execution_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(step_execution_module)
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


def test_step_execution_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    assert "sok_llm_orchestrator.pipeline" not in sys.modules
