from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy
from pathlib import Path

from sok_llm_orchestrator.agentic.plan_compile import PLAN_COMPILE_SCHEMA_VERSION
from sok_llm_orchestrator.agentic.planner_runtime import (
    PLANNER_COMPILE_RUN_SCHEMA_VERSION,
    run_live_planner,
    run_live_planner_and_compile,
)
from sok_llm_orchestrator.agentic.schemas import RUN_PLAN_SCHEMA_VERSION
import sok_llm_orchestrator.agentic.planner_runtime as planner_runtime_module


class _FakePlannerRuntime:
    def __init__(self, result: dict[str, object] | list[dict[str, object]]) -> None:
        self.results = [result] if isinstance(result, dict) else list(result)
        self.calls: list[tuple[str, dict[str, object], str]] = []

    def run_agent(
        self,
        agent_name: str,
        input_payload,
        expected_schema_name: str,
    ):  # type: ignore[no-untyped-def]
        self.calls.append((agent_name, dict(input_payload), expected_schema_name))
        if not self.results:
            raise AssertionError("No more fake planner outputs configured")
        return self.results.pop(0)


def _valid_planner_trace() -> dict[str, object]:
    return {
        "parsed_output": {
            "schema_version": RUN_PLAN_SCHEMA_VERSION,
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "detailed_description": "Plan a retrieval-focused run.",
            "hoping_to_find": "Promising TiO2 candidate structures.",
            "plan_as_text": "tool_hint: crystal.csp_pack",
            "what_we_tried_previously_that_is_related": "No prior failed strategies.",
            "success_criteria": ["Return a plan."],
            "stop_conditions_for_this_run": ["Missing inputs."],
        },
        "raw_output": "{\"schema_version\":\"agentic_csp.run_plan.v1\"}",
        "attempts": [
            {
                "attempt_number": 1,
                "raw_output": "{\"schema_version\":\"agentic_csp.run_plan.v1\"}",
                "validation_errors": [],
            }
        ],
        "validation_errors": [],
    }


def _planner_trace_with_plan_text(plan_as_text: str) -> dict[str, object]:
    trace = _valid_planner_trace()
    parsed_output = trace["parsed_output"]
    if isinstance(parsed_output, dict):
        parsed_output["plan_as_text"] = plan_as_text
    return trace


def test_run_live_planner_returns_valid_run_plan_dict() -> None:
    runtime = _FakePlannerRuntime(_valid_planner_trace())
    payload = {
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
    }
    result = run_live_planner(runtime, payload)

    assert result["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert result["overall_goal"] == "TiO2"
    assert runtime.calls == [("planner", payload, "run_plan")]


def test_run_live_planner_and_compile_returns_valid_compiled_proposal() -> None:
    runtime = _FakePlannerRuntime(
        _planner_trace_with_plan_text(
            "\n".join(
                [
                    "1. Retrieve candidate structures for the current run.",
                    "tool_hint: crystal.csp_pack",
                    "Expected result: ranked candidate set with exportability metadata.",
                ]
            )
        )
    )

    result = run_live_planner_and_compile(
        runtime,
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
    )

    assert result["schema_version"] == PLANNER_COMPILE_RUN_SCHEMA_VERSION
    assert result["run_plan"]["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert result["compile_result"]["schema_version"] == PLAN_COMPILE_SCHEMA_VERSION
    assert result["proposal_count"] == 1
    assert result["valid_proposal_count"] == 1
    assert result["invalid_proposal_count"] == 0
    assert result["compile_result"]["proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert result["compile_result"]["validation_results"][0]["valid"] is True


def test_run_live_planner_and_compile_supports_multiple_valid_tool_hints_without_changing_retry_behavior() -> None:
    runtime = _FakePlannerRuntime(
        _planner_trace_with_plan_text(
            "\n".join(
                [
                    "1. Prepare a fuller future CSP workflow.",
                    "tool_hint: crystal.csp_pack",
                    "tool_hint: spp.run_pipeline",
                    "tool_hint: qlip.validate_request",
                ]
            )
        )
    )

    result = run_live_planner_and_compile(
        runtime,
        {
            "overall_goal": "TiO2",
            "run_goal": "future csp workflow proposal review",
            "stage": "wide_exploration",
        },
    )

    assert result["proposal_count"] == 3
    assert result["valid_proposal_count"] == 3
    assert result["invalid_proposal_count"] == 0
    assert [item["tool_name"] for item in result["compile_result"]["proposals"]] == [
        "crystal.csp_pack",
        "spp.run_pipeline",
        "qlip.validate_request",
    ]
    assert all(item["valid"] is True for item in result["compile_result"]["validation_results"])
    assert runtime.calls == [
        (
            "planner",
            {
                "overall_goal": "TiO2",
                "run_goal": "future csp workflow proposal review",
                "stage": "wide_exploration",
            },
            "run_plan",
        )
    ]


def test_run_live_planner_and_compile_truthfully_returns_zero_proposals_without_hint() -> None:
    runtime = _FakePlannerRuntime(
        _planner_trace_with_plan_text(
            "1. Review the current goal and outline a cautious next run without tool hints."
        )
    )

    result = run_live_planner_and_compile(
        runtime,
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
    )

    assert result["schema_version"] == PLANNER_COMPILE_RUN_SCHEMA_VERSION
    assert result["proposal_count"] == 0
    assert result["valid_proposal_count"] == 0
    assert result["invalid_proposal_count"] == 0
    assert result["compile_result"]["proposals"] == []
    assert result["compile_result"]["validation_results"] == []
    assert result["warnings"] == []


def test_run_live_planner_and_compile_fails_truthfully_when_require_proposals_is_true() -> None:
    runtime = _FakePlannerRuntime(
        _planner_trace_with_plan_text(
            "1. Use the crystal.csp_pack tool to retrieve candidates without a formal tool_hint line."
        )
    )

    try:
        _ = run_live_planner_and_compile(
            runtime,
            {
                "overall_goal": "TiO2",
                "run_goal": "retrieve candidates",
                "stage": "wide_exploration",
            },
            require_proposals=True,
            max_compile_retries=0,
        )
    except ValueError as exc:
        error_text = str(exc)
        assert "no valid proposals" in error_text.lower()
        assert "tool_hint: crystal.csp_pack" in error_text
    else:
        raise AssertionError("Expected ValueError when proposal-required planner output has no hint")


def test_run_live_planner_and_compile_retries_with_compile_feedback_and_succeeds() -> None:
    runtime = _FakePlannerRuntime(
        [
            _planner_trace_with_plan_text(
                "1. Use the crystal.csp_pack tool to retrieve candidates without a formal tool_hint line."
            ),
            _planner_trace_with_plan_text(
                "\n".join(
                    [
                        "1. Refine the proposal after compile feedback.",
                        "tool_hint: crystal.csp_pack",
                        "Expected result: ranked candidate set with exportability metadata.",
                    ]
                )
            ),
        ]
    )
    payload = {
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
    }
    before = deepcopy(payload)

    result = run_live_planner_and_compile(
        runtime,
        payload,
        require_proposals=True,
        max_compile_retries=2,
    )

    assert payload == before
    assert result["proposal_count"] == 1
    assert result["valid_proposal_count"] == 1
    assert len(runtime.calls) == 2
    second_payload = runtime.calls[1][1]
    assert "planner_feedback" in second_payload
    assert second_payload["planner_feedback"]["previous_compile_failure"] is True
    assert (
        second_payload["planner_feedback"]["required_exact_tool_hint_line"]
        == "tool_hint: crystal.csp_pack"
    )
    assert (
        second_payload["planner_feedback"]["required_plan_as_text_item"]
        == "tool_hint: crystal.csp_pack"
    )
    assert second_payload["planner_feedback"]["invalid_examples"] == [
        "Use the crystal.csp_pack tool",
        "call crystal.csp_pack",
        "tool hint: crystal csp pack",
    ]
    assert (
        second_payload["planner_feedback"]["valid_example"]["plan_as_text"]
        .splitlines()[1]
        == "tool_hint: crystal.csp_pack"
    )


def test_run_live_planner_and_compile_fails_after_bounded_compile_retries() -> None:
    runtime = _FakePlannerRuntime(
        [
            _planner_trace_with_plan_text(
                "1. Use the crystal.csp_pack tool to retrieve candidates without a formal tool_hint line."
            ),
            _planner_trace_with_plan_text(
                "1. Still describe the tool in prose without the required tool_hint line."
            ),
            _planner_trace_with_plan_text(
                "1. Continue to avoid the exact standalone tool_hint line."
            ),
        ]
    )

    try:
        _ = run_live_planner_and_compile(
            runtime,
            {
                "overall_goal": "TiO2",
                "run_goal": "retrieve candidates",
                "stage": "wide_exploration",
            },
            require_proposals=True,
            max_compile_retries=2,
        )
    except ValueError as exc:
        assert "tool_hint: crystal.csp_pack" in str(exc)
        assert len(runtime.calls) == 3
    else:
        raise AssertionError("Expected ValueError after bounded compile retries")


def test_run_live_planner_and_compile_preserves_unknown_hint_warning_and_invalid_validation() -> None:
    runtime = _FakePlannerRuntime(
        _planner_trace_with_plan_text(
            "\n".join(
                [
                    "1. Explore an unsupported bridge candidate.",
                    "tool_hint: unknown.tool",
                ]
            )
        )
    )

    result = run_live_planner_and_compile(
        runtime,
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
    )

    assert result["proposal_count"] == 0
    assert result["valid_proposal_count"] == 0
    assert result["invalid_proposal_count"] == 1
    assert result["warnings"] == ["Unknown tool_hint: unknown.tool"]
    assert result["compile_result"]["validation_results"][0]["valid"] is False
    assert result["compile_result"]["validation_results"][0]["tool_name"] == "unknown.tool"


def test_run_live_planner_archive_trace_writes_trace_json(workdir) -> None:  # type: ignore[no-untyped-def]
    runtime = _FakePlannerRuntime(_valid_planner_trace())
    result = run_live_planner(
        runtime,
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
        out_dir=workdir,
        archive_trace=True,
    )

    trace_path = Path(workdir) / "agentic_llm_trace_planner.json"
    trace_json = json.loads(trace_path.read_text(encoding="utf-8"))

    assert result["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert trace_path.exists()
    assert trace_json["parsed_output"]["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert "raw_output" in trace_json


def test_run_live_planner_and_compile_archive_trace_writes_trace_json(workdir) -> None:  # type: ignore[no-untyped-def]
    runtime = _FakePlannerRuntime(_valid_planner_trace())
    result = run_live_planner_and_compile(
        runtime,
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
        out_dir=workdir,
        archive_trace=True,
        require_proposals=True,
    )

    trace_path = Path(workdir) / "agentic_llm_trace_planner.json"
    trace_json = json.loads(trace_path.read_text(encoding="utf-8"))

    assert result["schema_version"] == PLANNER_COMPILE_RUN_SCHEMA_VERSION
    assert trace_path.exists()
    assert result["trace_write"]["agent_name"] == "planner"
    assert trace_json["parsed_output"]["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert "raw_output" in trace_json


def test_run_live_planner_fails_truthfully_for_missing_or_wrong_schema() -> None:
    runtime = _FakePlannerRuntime(
        {
            "parsed_output": {
                "schema_version": "agentic_csp.run_manager_log.v1",
                "overall_goal": "TiO2",
            },
            "raw_output": "{}",
            "attempts": [],
            "validation_errors": ["wrong schema"],
        }
    )

    try:
        _ = run_live_planner(
            runtime,
            {
                "overall_goal": "TiO2",
                "run_goal": "retrieve candidates",
                "stage": "wide_exploration",
            },
        )
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid planner schema")


def test_run_live_planner_does_not_mutate_input_and_is_json_serializable() -> None:
    runtime = _FakePlannerRuntime(_valid_planner_trace())
    payload = {
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
        "nested": {"alpha": 1},
    }
    before = deepcopy(payload)

    result = run_live_planner(runtime, payload)

    assert payload == before
    assert json.loads(json.dumps(result))["schema_version"] == RUN_PLAN_SCHEMA_VERSION


def test_run_live_planner_and_compile_does_not_mutate_input_and_is_json_serializable() -> None:
    runtime = _FakePlannerRuntime(_valid_planner_trace())
    payload = {
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
        "nested": {"alpha": 1},
    }
    before = deepcopy(payload)

    result = run_live_planner_and_compile(runtime, payload)

    assert payload == before
    assert json.loads(json.dumps(result))["schema_version"] == PLANNER_COMPILE_RUN_SCHEMA_VERSION


def test_planner_runtime_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(planner_runtime_module)
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


def test_planner_runtime_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    runtime = _FakePlannerRuntime(_valid_planner_trace())
    _ = run_live_planner(
        runtime,
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
    )
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
