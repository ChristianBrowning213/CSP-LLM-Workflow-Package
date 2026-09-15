from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy
from pathlib import Path

from sok_llm_orchestrator.agentic.orchestrator_runtime import run_live_orchestrator
from sok_llm_orchestrator.agentic.schemas import ORCHESTRATOR_DECISION_SCHEMA_VERSION
import sok_llm_orchestrator.agentic.orchestrator_runtime as orchestrator_runtime_module


class _FakeOrchestratorRuntime:
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


def _valid_orchestrator_trace() -> dict[str, object]:
    return {
        "parsed_output": {
            "schema_version": ORCHESTRATOR_DECISION_SCHEMA_VERSION,
            "decision": "continue",
            "reason": "The evaluator reports a useful proposal-review run with no execution and recommends continuing.",
            "next_run_goal": "Escalate the reviewed proposal state into the next orchestrator-guided planning step.",
            "current_stage": "wide_exploration",
            "evidence_used": ["run_evaluation", "run_manager_log", "compile_result"],
            "user_message_if_stopping": "",
            "clarification_question_if_needed": "",
        },
        "raw_output": "{\"schema_version\":\"agentic_csp.orchestrator_decision.v1\"}",
        "attempts": [
            {
                "attempt_number": 1,
                "raw_output": "{\"schema_version\":\"agentic_csp.orchestrator_decision.v1\"}",
                "validation_errors": [],
            }
        ],
        "validation_errors": [],
    }


def _orchestrator_input() -> dict[str, object]:
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
        "run_evaluation": {
            "schema_version": "agentic_csp.run_evaluation.v1",
            "run_id": "run_001",
            "run_goal": "retrieve candidates",
            "run_goal_success": True,
            "overall_goal_progress": "Proposal review advanced the overall goal without execution.",
            "summary": "The run produced a validated future proposal.",
            "what_worked": ["The planner emitted a valid tool hint."],
            "what_failed_or_was_weak": ["No execution occurred in this ticket."],
            "scientific_findings": ["Proposal readiness improved."],
            "best_artifacts": [],
            "scores": {"proposal_readiness": "good"},
            "comparison_to_previous_best": "Comparable to prior review-only runs.",
            "recommended_next_run": "Ask the orchestrator whether to continue with deeper review.",
            "should_stop": False,
            "stop_reason": "",
            "needs_user_clarification": False,
            "clarification_question": "",
        },
        "proposal_count": 1,
        "valid_proposal_count": 1,
        "invalid_proposal_count": 0,
        "warnings": [],
    }


def test_run_live_orchestrator_returns_valid_orchestrator_decision_dict() -> None:
    runtime = _FakeOrchestratorRuntime(_valid_orchestrator_trace())
    payload = _orchestrator_input()

    result = run_live_orchestrator(runtime, payload)

    assert result["schema_version"] == ORCHESTRATOR_DECISION_SCHEMA_VERSION
    assert result["decision"] == "continue"
    assert result["reason"]
    assert runtime.calls == [("orchestrator", payload, "orchestrator_decision")]


def test_run_live_orchestrator_archive_trace_writes_trace_json(workdir) -> None:  # type: ignore[no-untyped-def]
    runtime = _FakeOrchestratorRuntime(_valid_orchestrator_trace())
    result = run_live_orchestrator(runtime, _orchestrator_input(), out_dir=workdir, archive_trace=True)

    trace_path = Path(workdir) / "agentic_llm_trace_orchestrator.json"
    trace_json = json.loads(trace_path.read_text(encoding="utf-8"))

    assert result["schema_version"] == ORCHESTRATOR_DECISION_SCHEMA_VERSION
    assert trace_path.exists()
    assert trace_json["parsed_output"]["schema_version"] == ORCHESTRATOR_DECISION_SCHEMA_VERSION
    assert "raw_output" in trace_json


def test_run_live_orchestrator_fails_truthfully_for_missing_or_wrong_schema() -> None:
    runtime = _FakeOrchestratorRuntime(
        {
            "parsed_output": {
                "schema_version": "agentic_csp.run_evaluation.v1",
                "decision": "continue",
            },
            "raw_output": "{}",
            "attempts": [],
            "validation_errors": ["wrong schema"],
        }
    )

    try:
        _ = run_live_orchestrator(runtime, _orchestrator_input())
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid orchestrator schema")


def test_run_live_orchestrator_does_not_mutate_input_and_is_json_serializable() -> None:
    runtime = _FakeOrchestratorRuntime(_valid_orchestrator_trace())
    payload = _orchestrator_input()
    payload["nested"] = {"alpha": 1}
    before = deepcopy(payload)

    result = run_live_orchestrator(runtime, payload)

    assert payload == before
    assert json.loads(json.dumps(result))["schema_version"] == ORCHESTRATOR_DECISION_SCHEMA_VERSION


def test_orchestrator_runtime_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(orchestrator_runtime_module)
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


def test_orchestrator_runtime_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    runtime = _FakeOrchestratorRuntime(_valid_orchestrator_trace())
    _ = run_live_orchestrator(runtime, _orchestrator_input())
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
