from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .archive import write_agentic_llm_trace
from .plan_compile import compile_run_plan_to_tool_proposals
from .schemas import RUN_PLAN_SCHEMA_VERSION, assert_json_serializable, to_json_dict
from .tools import AgenticToolRegistry

RUN_PLAN_REQUIRED_FIELDS = [
    "schema_version",
    "overall_goal",
    "run_goal",
    "stage",
    "detailed_description",
    "hoping_to_find",
    "plan_as_text",
    "what_we_tried_previously_that_is_related",
    "success_criteria",
    "stop_conditions_for_this_run",
]
PLANNER_COMPILE_RUN_SCHEMA_VERSION = "agentic_csp.planner_compile_run.v1"


def _validated_run_plan(run_plan: Mapping[str, Any]) -> dict[str, Any]:
    plain_run_plan = to_json_dict(run_plan)
    if plain_run_plan.get("schema_version") != RUN_PLAN_SCHEMA_VERSION:
        msg = (
            f"Planner output schema_version must be {RUN_PLAN_SCHEMA_VERSION}, "
            f"got {plain_run_plan.get('schema_version')}"
        )
        raise ValueError(msg)
    missing_fields = [
        field_name for field_name in RUN_PLAN_REQUIRED_FIELDS if field_name not in plain_run_plan
    ]
    if missing_fields:
        msg = "Planner output missing required fields: " + ", ".join(missing_fields)
        raise ValueError(msg)
    assert_json_serializable(plain_run_plan)
    return plain_run_plan


def _validation_error_text(trace: Mapping[str, Any]) -> str:
    errors = trace.get("validation_errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(item) for item in errors)
    return "unknown planner validation failure"


def _proposal_requirement_error(run_plan: Mapping[str, Any]) -> str:
    run_goal = str(run_plan.get("run_goal", "")).strip()
    stage = str(run_plan.get("stage", "")).strip()
    return (
        "Planner compile produced no valid proposals for a proposal-required run. "
        f"run_goal={run_goal!r}, stage={stage!r}. "
        "For retrieval or wide_exploration runs, plan_as_text must contain the exact standalone line "
        "'tool_hint: crystal.csp_pack'."
    )


def _planner_feedback_payload(
    original_input_payload: Mapping[str, Any],
    run_plan: Mapping[str, Any],
) -> dict[str, Any]:
    feedback_payload = dict(to_json_dict(original_input_payload))
    existing_feedback = feedback_payload.get("planner_feedback")
    planner_feedback: dict[str, Any] = (
        dict(existing_feedback) if isinstance(existing_feedback, Mapping) else {}
    )
    planner_feedback.update(
        {
            "previous_compile_failure": True,
            "compile_failure_reason": _proposal_requirement_error(run_plan),
            "required_exact_tool_hint_line": "tool_hint: crystal.csp_pack",
            "required_plan_as_text_item": "tool_hint: crystal.csp_pack",
            "instruction": (
                "Your next RunPlan MUST include a plan_as_text item that is exactly or "
                "contains the standalone line: tool_hint: crystal.csp_pack"
            ),
            "invalid_examples": [
                "Use the crystal.csp_pack tool",
                "call crystal.csp_pack",
                "tool hint: crystal csp pack",
            ],
            "valid_example": {
                "plan_as_text": (
                    "1. Retrieve candidate structures for the current run.\n"
                    "tool_hint: crystal.csp_pack\n"
                    "Expected result: ranked candidate set with exportability metadata."
                )
            },
        }
    )
    feedback_payload["planner_feedback"] = planner_feedback
    return feedback_payload


def _run_planner_trace(
    llm_runtime: Any,
    input_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    trace = to_json_dict(llm_runtime.run_agent("planner", input_payload, "run_plan"))
    parsed_output = trace.get("parsed_output")
    if not isinstance(parsed_output, Mapping):
        msg = "Planner LLM runtime did not return a valid parsed_output: " + _validation_error_text(
            trace
        )
        raise ValueError(msg)
    return trace, _validated_run_plan(parsed_output)


def run_live_planner(
    llm_runtime: Any,
    input_payload: Mapping[str, Any],
    out_dir=None,
    archive_trace: bool = False,
) -> dict[str, Any]:
    if not isinstance(input_payload, Mapping):
        msg = "input_payload must be a mapping"
        raise TypeError(msg)
    if archive_trace and out_dir is None:
        msg = "out_dir is required when archive_trace=True"
        raise ValueError(msg)

    trace, run_plan = _run_planner_trace(llm_runtime, input_payload)
    if archive_trace:
        _ = write_agentic_llm_trace(trace, out_dir, "planner")
    return run_plan


def run_live_planner_and_compile(
    llm_runtime: Any,
    input_payload: Mapping[str, Any],
    out_dir=None,
    archive_trace: bool = False,
    registry: AgenticToolRegistry | None = None,
    require_proposals: bool = False,
    max_compile_retries: int = 2,
) -> dict[str, Any]:
    if not isinstance(input_payload, Mapping):
        msg = "input_payload must be a mapping"
        raise TypeError(msg)
    if archive_trace and out_dir is None:
        msg = "out_dir is required when archive_trace=True"
        raise ValueError(msg)
    if max_compile_retries < 0:
        msg = "max_compile_retries must be >= 0"
        raise ValueError(msg)

    original_input_payload = to_json_dict(input_payload)
    working_input_payload = deepcopy(original_input_payload)
    last_trace: dict[str, Any] | None = None
    last_run_plan: dict[str, Any] | None = None

    for attempt_index in range(max_compile_retries + 1):
        trace, run_plan = _run_planner_trace(llm_runtime, working_input_payload)
        last_trace = trace
        last_run_plan = run_plan

        compile_result = compile_run_plan_to_tool_proposals(run_plan, registry=registry)
        validation_results = compile_result.get("validation_results")
        if not isinstance(validation_results, list):
            validation_results = []

        valid_proposal_count = 0
        invalid_proposal_count = 0
        for result in validation_results:
            if isinstance(result, Mapping) and result.get("valid") is True:
                valid_proposal_count += 1
            else:
                invalid_proposal_count += 1

        proposals = compile_result.get("proposals")
        warnings = compile_result.get("warnings")
        output = {
            "schema_version": PLANNER_COMPILE_RUN_SCHEMA_VERSION,
            "run_plan": run_plan,
            "compile_result": compile_result,
            "proposal_count": len(proposals) if isinstance(proposals, list) else 0,
            "valid_proposal_count": valid_proposal_count,
            "invalid_proposal_count": invalid_proposal_count,
            "warnings": list(warnings) if isinstance(warnings, list) else [],
        }

        if not require_proposals or valid_proposal_count >= 1:
            if archive_trace and last_trace is not None:
                output["trace_write"] = write_agentic_llm_trace(last_trace, out_dir, "planner")
            assert_json_serializable(output)
            return output

        if attempt_index < max_compile_retries:
            working_input_payload = _planner_feedback_payload(original_input_payload, run_plan)
            continue

        if archive_trace and last_trace is not None:
            _ = write_agentic_llm_trace(last_trace, out_dir, "planner")
        raise ValueError(_proposal_requirement_error(run_plan))

    if archive_trace and last_trace is not None:
        _ = write_agentic_llm_trace(last_trace, out_dir, "planner")
    raise ValueError(_proposal_requirement_error(last_run_plan or {}))


__all__ = [
    "PLANNER_COMPILE_RUN_SCHEMA_VERSION",
    "RUN_PLAN_REQUIRED_FIELDS",
    "run_live_planner",
    "run_live_planner_and_compile",
]
