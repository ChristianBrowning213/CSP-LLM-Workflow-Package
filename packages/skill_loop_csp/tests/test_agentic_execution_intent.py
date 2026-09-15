from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic.execution_intent import (
    EXECUTION_INTENT_SCHEMA_VERSION,
    build_execution_intent,
)
import sok_llm_orchestrator.agentic.execution_intent as execution_intent_module


def _run_manager_log() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.run_manager_log.v1",
        "run_id": "run_001",
        "tool_calls_attempted": [],
        "failures_handled": [],
        "manager_notes": "Reviewed proposal readiness only; no execution occurred.",
        "artifacts_created": [],
    }


def _planner_compile_result(
    proposals: list[dict[str, object]],
    validation_results: list[dict[str, object]],
    warnings: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.planner_compile_run.v1",
        "run_plan": {
            "schema_version": "agentic_csp.run_plan.v1",
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "detailed_description": "Plan retrieval.",
            "hoping_to_find": "Candidates.",
            "plan_as_text": "tool_hint: crystal.csp_pack",
            "what_we_tried_previously_that_is_related": "Nothing yet.",
            "success_criteria": ["Valid proposal"],
            "stop_conditions_for_this_run": ["Missing input"],
        },
        "compile_result": {
            "schema_version": "agentic_csp.plan_compile.v1",
            "proposals": proposals,
            "validation_results": validation_results,
            "warnings": list(warnings or []),
        },
        "proposal_count": len(proposals),
        "valid_proposal_count": sum(
            1 for item in validation_results if item.get("valid") is True
        ),
        "invalid_proposal_count": sum(
            1 for item in validation_results if item.get("valid") is not True
        ),
        "warnings": list(warnings or []),
    }


def test_build_execution_intent_ready_for_execution_when_all_proposals_are_valid() -> None:
    planner_compile_result = _planner_compile_result(
        proposals=[
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {"query": "retrieve candidates"},
            }
        ],
        validation_results=[
            {
                "schema_version": "agentic_csp.tool_validation.v1",
                "tool_name": "crystal.csp_pack",
                "valid": True,
                "errors": [],
                "warnings": [],
            }
        ],
    )

    result = build_execution_intent(planner_compile_result, _run_manager_log())

    assert result["schema_version"] == EXECUTION_INTENT_SCHEMA_VERSION
    assert result["status"] == "ready_for_execution"
    assert result["execution_allowed"] is True
    assert result["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert result["blocked_reasons"] == []
    assert result["warnings"] == []


def test_build_execution_intent_blocks_when_no_proposals_exist() -> None:
    planner_compile_result = _planner_compile_result(proposals=[], validation_results=[])

    result = build_execution_intent(planner_compile_result, _run_manager_log())

    assert result["status"] == "blocked_no_proposals"
    assert result["execution_allowed"] is False
    assert result["selected_proposals"] == []
    assert any("No tool proposals" in item for item in result["blocked_reasons"])


def test_build_execution_intent_blocks_when_invalid_proposals_exist() -> None:
    planner_compile_result = _planner_compile_result(
        proposals=[],
        validation_results=[
            {
                "schema_version": "agentic_csp.tool_validation.v1",
                "tool_name": "unknown.tool",
                "valid": False,
                "errors": ["Unknown tool name: unknown.tool"],
                "warnings": [],
            }
        ],
    )

    result = build_execution_intent(planner_compile_result, _run_manager_log())

    assert result["status"] == "blocked_invalid_proposals"
    assert result["execution_allowed"] is False
    assert result["selected_proposals"] == []
    assert any("unknown.tool" in item for item in result["blocked_reasons"])


def test_build_execution_intent_requires_review_when_warnings_exist() -> None:
    planner_compile_result = _planner_compile_result(
        proposals=[
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {"query": "retrieve candidates"},
            }
        ],
        validation_results=[
            {
                "schema_version": "agentic_csp.tool_validation.v1",
                "tool_name": "crystal.csp_pack",
                "valid": True,
                "errors": [],
                "warnings": ["Manual review recommended"],
            }
        ],
        warnings=["Planner requested manual review."],
    )

    result = build_execution_intent(planner_compile_result, _run_manager_log())

    assert result["status"] == "review_required"
    assert result["execution_allowed"] is False
    assert result["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert "Manual review recommended" in result["warnings"]
    assert "Planner requested manual review." in result["warnings"]


def test_build_execution_intent_does_not_mutate_inputs_and_is_json_serializable() -> None:
    planner_compile_result = _planner_compile_result(
        proposals=[
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {"query": "retrieve candidates"},
            }
        ],
        validation_results=[
            {
                "schema_version": "agentic_csp.tool_validation.v1",
                "tool_name": "crystal.csp_pack",
                "valid": True,
                "errors": [],
                "warnings": [],
            }
        ],
    )
    run_manager_log = _run_manager_log()
    before_planner = deepcopy(planner_compile_result)
    before_manager = deepcopy(run_manager_log)

    result = build_execution_intent(planner_compile_result, run_manager_log)

    assert planner_compile_result == before_planner
    assert run_manager_log == before_manager
    assert json.loads(json.dumps(result))["schema_version"] == EXECUTION_INTENT_SCHEMA_VERSION


def test_execution_intent_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(execution_intent_module)
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


def test_execution_intent_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = build_execution_intent(
        _planner_compile_result(
            proposals=[],
            validation_results=[],
        ),
        _run_manager_log(),
    )
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
