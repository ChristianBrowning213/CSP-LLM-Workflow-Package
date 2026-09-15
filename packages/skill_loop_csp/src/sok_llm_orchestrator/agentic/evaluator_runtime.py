from __future__ import annotations

from typing import Any, Mapping

from .archive import run_agent_and_archive_trace
from .schemas import RUN_EVALUATION_SCHEMA_VERSION, assert_json_serializable, to_json_dict

RUN_EVALUATION_REQUIRED_FIELDS = [
    "schema_version",
    "run_id",
    "run_goal",
    "run_goal_success",
    "overall_goal_progress",
    "summary",
    "what_worked",
    "what_failed_or_was_weak",
    "scientific_findings",
    "best_artifacts",
    "scores",
    "comparison_to_previous_best",
    "recommended_next_run",
    "should_stop",
    "stop_reason",
    "needs_user_clarification",
    "clarification_question",
]


def _validated_run_evaluation(run_evaluation: Mapping[str, Any]) -> dict[str, Any]:
    plain_run_evaluation = to_json_dict(run_evaluation)
    if plain_run_evaluation.get("schema_version") != RUN_EVALUATION_SCHEMA_VERSION:
        msg = (
            f"Evaluator output schema_version must be {RUN_EVALUATION_SCHEMA_VERSION}, "
            f"got {plain_run_evaluation.get('schema_version')}"
        )
        raise ValueError(msg)
    missing_fields = [
        field_name
        for field_name in RUN_EVALUATION_REQUIRED_FIELDS
        if field_name not in plain_run_evaluation
    ]
    if missing_fields:
        msg = "Evaluator output missing required fields: " + ", ".join(missing_fields)
        raise ValueError(msg)
    assert_json_serializable(plain_run_evaluation)
    return plain_run_evaluation


def _validation_error_text(trace: Mapping[str, Any]) -> str:
    errors = trace.get("validation_errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(item) for item in errors)
    return "unknown evaluator validation failure"


def run_live_evaluator(
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

    if archive_trace:
        trace_result = run_agent_and_archive_trace(
            llm_runtime,
            "evaluator",
            input_payload,
            "run_evaluation",
            out_dir,
        )
        parsed_output = trace_result.get("parsed_output")
        if not isinstance(parsed_output, Mapping):
            msg = (
                "Evaluator LLM runtime did not return a valid parsed_output: "
                + "; ".join(str(item) for item in trace_result.get("validation_errors", []))
                if isinstance(trace_result.get("validation_errors"), list)
                else "Evaluator LLM runtime did not return a valid parsed_output."
            )
            raise ValueError(msg)
        return _validated_run_evaluation(parsed_output)

    trace = llm_runtime.run_agent(
        "evaluator",
        input_payload,
        "run_evaluation",
    )
    parsed_output = trace.get("parsed_output")
    if not isinstance(parsed_output, Mapping):
        msg = "Evaluator LLM runtime did not return a valid parsed_output: " + _validation_error_text(
            trace
        )
        raise ValueError(msg)
    return _validated_run_evaluation(parsed_output)


__all__ = [
    "RUN_EVALUATION_REQUIRED_FIELDS",
    "run_live_evaluator",
]
