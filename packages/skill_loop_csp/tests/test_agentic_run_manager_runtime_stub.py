from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy
from pathlib import Path

from sok_llm_orchestrator.agentic.run_manager_runtime import run_live_run_manager
from sok_llm_orchestrator.agentic.schemas import RUN_MANAGER_LOG_SCHEMA_VERSION
import sok_llm_orchestrator.agentic.run_manager_runtime as run_manager_runtime_module


class _FakeRunManagerRuntime:
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


def _valid_run_manager_trace() -> dict[str, object]:
    return {
        "parsed_output": {
            "schema_version": RUN_MANAGER_LOG_SCHEMA_VERSION,
            "run_id": "run_001",
            "tool_calls_attempted": [
                {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "step": "Review the proposed crystal.csp_pack request.",
                    "tool_name": "crystal.csp_pack",
                    "arguments": {"query": "retrieve candidates"},
                    "expected_result": "A reviewed future proposal only.",
                    "why": "The planner requested candidate retrieval.",
                    "condition": "Do not execute in this ticket.",
                }
            ],
            "failures_handled": [],
            "manager_notes": "Reviewed proposal readiness only; no execution occurred.",
            "artifacts_created": [],
        },
        "raw_output": "{\"schema_version\":\"agentic_csp.run_manager_log.v1\"}",
        "attempts": [
            {
                "attempt_number": 1,
                "raw_output": "{\"schema_version\":\"agentic_csp.run_manager_log.v1\"}",
                "validation_errors": [],
            }
        ],
        "validation_errors": [],
    }


def _run_manager_input() -> dict[str, object]:
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
        "proposal_count": 1,
        "valid_proposal_count": 1,
        "invalid_proposal_count": 0,
        "warnings": [],
    }


def test_run_live_run_manager_returns_valid_run_manager_log_dict() -> None:
    runtime = _FakeRunManagerRuntime(_valid_run_manager_trace())
    payload = _run_manager_input()

    result = run_live_run_manager(runtime, payload)

    assert result["schema_version"] == RUN_MANAGER_LOG_SCHEMA_VERSION
    assert result["run_id"] == "run_001"
    assert result["manager_notes"]
    assert runtime.calls == [("run_manager", payload, "run_manager_log")]


def test_run_live_run_manager_archive_trace_writes_trace_json(workdir) -> None:  # type: ignore[no-untyped-def]
    runtime = _FakeRunManagerRuntime(_valid_run_manager_trace())
    result = run_live_run_manager(runtime, _run_manager_input(), out_dir=workdir, archive_trace=True)

    trace_path = Path(workdir) / "agentic_llm_trace_run_manager.json"
    trace_json = json.loads(trace_path.read_text(encoding="utf-8"))

    assert result["schema_version"] == RUN_MANAGER_LOG_SCHEMA_VERSION
    assert trace_path.exists()
    assert trace_json["parsed_output"]["schema_version"] == RUN_MANAGER_LOG_SCHEMA_VERSION
    assert "raw_output" in trace_json


def test_run_live_run_manager_fails_truthfully_for_missing_or_wrong_schema() -> None:
    runtime = _FakeRunManagerRuntime(
        {
            "parsed_output": {
                "schema_version": "agentic_csp.run_plan.v1",
                "run_id": "run_001",
            },
            "raw_output": "{}",
            "attempts": [],
            "validation_errors": ["wrong schema"],
        }
    )

    try:
        _ = run_live_run_manager(runtime, _run_manager_input())
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid run manager schema")


def test_run_live_run_manager_does_not_mutate_input_and_is_json_serializable() -> None:
    runtime = _FakeRunManagerRuntime(_valid_run_manager_trace())
    payload = _run_manager_input()
    payload["nested"] = {"alpha": 1}
    before = deepcopy(payload)

    result = run_live_run_manager(runtime, payload)

    assert payload == before
    assert json.loads(json.dumps(result))["schema_version"] == RUN_MANAGER_LOG_SCHEMA_VERSION


def test_run_manager_runtime_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(run_manager_runtime_module)
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


def test_run_manager_runtime_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    runtime = _FakeRunManagerRuntime(_valid_run_manager_trace())
    _ = run_live_run_manager(runtime, _run_manager_input())
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
