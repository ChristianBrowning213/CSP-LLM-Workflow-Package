from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy
from pathlib import Path

from sok_llm_orchestrator.agentic.evaluator_runtime import run_live_evaluator
from sok_llm_orchestrator.agentic.schemas import RUN_EVALUATION_SCHEMA_VERSION
import sok_llm_orchestrator.agentic.evaluator_runtime as evaluator_runtime_module


class _FakeEvaluatorRuntime:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, object], str]] = []

    def run_agent(
        self,
        agent_name: str,
        input_payload,
        expected_schema_name: str,
    ):  # type: ignore[no-untyped-def]
        self.calls.append((agent_name, dict(input_payload), expected_schema_name))
        return self.result


def _valid_evaluator_trace() -> dict[str, object]:
    return {
        "parsed_output": {
            "schema_version": RUN_EVALUATION_SCHEMA_VERSION,
            "run_id": "run_001",
            "run_goal": "retrieve candidates",
            "run_goal_success": True,
            "overall_goal_progress": "Proposal-review progress was meaningful but execution has not occurred.",
            "summary": "The proposal-review run produced a reviewable future crystal.csp_pack proposal without executing tools.",
            "what_worked": ["The planner emitted a usable tool hint.", "The run manager preserved the proposal review state."],
            "what_failed_or_was_weak": ["No tool execution or scientific solve occurred in this run."],
            "scientific_findings": ["This run improved proposal readiness only."],
            "best_artifacts": [],
            "scores": {"proposal_readiness": "good"},
            "comparison_to_previous_best": "Comparable to prior proposal-review baseline.",
            "recommended_next_run": "Escalate to orchestrator review of whether the validated proposal is ready for a future execution layer.",
            "should_stop": False,
            "stop_reason": "",
            "needs_user_clarification": False,
            "clarification_question": "",
        },
        "raw_output": "{\"schema_version\":\"agentic_csp.run_evaluation.v1\"}",
        "attempts": [
            {
                "attempt_number": 1,
                "raw_output": "{\"schema_version\":\"agentic_csp.run_evaluation.v1\"}",
                "validation_errors": [],
            }
        ],
        "validation_errors": [],
    }


def _evaluator_input() -> dict[str, object]:
    return {
        "run_id": "run_001",
        "run_plan": {
            "schema_version": "agentic_csp.run_plan.v1",
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "detailed_description": "Plan candidate retrieval.",
            "hoping_to_find": "Promising TiO2 structures.",
            "plan_as_text": "tool_hint: crystal.csp_pack",
            "what_we_tried_previously_that_is_related": "No prior failed strategies.",
            "success_criteria": ["Return candidate-oriented plan."],
            "stop_conditions_for_this_run": ["Missing inputs."],
        },
        "compile_result": {
            "schema_version": "agentic_csp.plan_compile.v1",
            "proposals": [
                {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "step": "Compile a future crystal.csp_pack request.",
                    "tool_name": "crystal.csp_pack",
                    "arguments": {"query": "retrieve candidates"},
                    "expected_result": "Prepared future request only.",
                    "why": "Planner requested candidate retrieval.",
                    "condition": "Review only.",
                }
            ],
            "validation_results": [
                {
                    "schema_version": "agentic_csp.tool_validation.v1",
                    "valid": True,
                    "tool_name": "crystal.csp_pack",
                    "errors": [],
                    "warnings": [],
                }
            ],
            "warnings": [],
        },
        "run_manager_log": {
            "schema_version": "agentic_csp.run_manager_log.v1",
            "run_id": "run_001",
            "tool_calls_attempted": [],
            "failures_handled": [],
            "manager_notes": "Reviewed proposal readiness only; no execution occurred.",
            "artifacts_created": [],
        },
        "proposal_count": 1,
        "valid_proposal_count": 1,
        "invalid_proposal_count": 0,
        "warnings": [],
    }


def test_run_live_evaluator_returns_valid_run_evaluation_dict() -> None:
    runtime = _FakeEvaluatorRuntime(_valid_evaluator_trace())
    payload = _evaluator_input()

    result = run_live_evaluator(runtime, payload)

    assert result["schema_version"] == RUN_EVALUATION_SCHEMA_VERSION
    assert result["run_id"] == "run_001"
    assert result["summary"]
    assert runtime.calls == [("evaluator", payload, "run_evaluation")]


def test_run_live_evaluator_archive_trace_writes_trace_json(workdir) -> None:  # type: ignore[no-untyped-def]
    runtime = _FakeEvaluatorRuntime(_valid_evaluator_trace())
    result = run_live_evaluator(runtime, _evaluator_input(), out_dir=workdir, archive_trace=True)

    trace_path = Path(workdir) / "agentic_llm_trace_evaluator.json"
    trace_json = json.loads(trace_path.read_text(encoding="utf-8"))

    assert result["schema_version"] == RUN_EVALUATION_SCHEMA_VERSION
    assert trace_path.exists()
    assert trace_json["parsed_output"]["schema_version"] == RUN_EVALUATION_SCHEMA_VERSION
    assert "raw_output" in trace_json


def test_run_live_evaluator_fails_truthfully_for_missing_or_wrong_schema() -> None:
    runtime = _FakeEvaluatorRuntime(
        {
            "parsed_output": {
                "schema_version": "agentic_csp.run_manager_log.v1",
                "run_id": "run_001",
            },
            "raw_output": "{}",
            "attempts": [],
            "validation_errors": ["wrong schema"],
        }
    )

    try:
        _ = run_live_evaluator(runtime, _evaluator_input())
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid evaluator schema")


def test_run_live_evaluator_fails_for_missing_required_top_level_fields() -> None:
    runtime = _FakeEvaluatorRuntime(
        {
            "parsed_output": {
                "schema_version": RUN_EVALUATION_SCHEMA_VERSION,
                "run_id": "run_001",
                "run_goal": "retrieve candidates",
                "summary": "Too sparse.",
            },
            "raw_output": "{}",
            "attempts": [],
            "validation_errors": ["missing fields"],
        }
    )

    try:
        _ = run_live_evaluator(runtime, _evaluator_input())
    except ValueError as exc:
        assert "missing required fields" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for missing evaluator fields")


def test_run_live_evaluator_does_not_mutate_input_and_is_json_serializable() -> None:
    runtime = _FakeEvaluatorRuntime(_valid_evaluator_trace())
    payload = _evaluator_input()
    payload["nested"] = {"alpha": 1}
    before = deepcopy(payload)

    result = run_live_evaluator(runtime, payload)

    assert payload == before
    assert json.loads(json.dumps(result))["schema_version"] == RUN_EVALUATION_SCHEMA_VERSION


def test_evaluator_runtime_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(evaluator_runtime_module)
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


def test_evaluator_runtime_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    runtime = _FakeEvaluatorRuntime(_valid_evaluator_trace())
    _ = run_live_evaluator(runtime, _evaluator_input())
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
