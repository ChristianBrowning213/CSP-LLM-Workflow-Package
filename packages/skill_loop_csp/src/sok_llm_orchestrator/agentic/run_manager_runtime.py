from __future__ import annotations

from typing import Any, Mapping

from .archive import run_agent_and_archive_trace
from .schemas import RUN_MANAGER_LOG_SCHEMA_VERSION, assert_json_serializable, to_json_dict

RUN_MANAGER_LOG_REQUIRED_FIELDS = [
    "schema_version",
    "run_id",
    "tool_calls_attempted",
    "failures_handled",
    "manager_notes",
    "artifacts_created",
]


def _validated_run_manager_log(run_manager_log: Mapping[str, Any]) -> dict[str, Any]:
    plain_run_manager_log = to_json_dict(run_manager_log)
    if plain_run_manager_log.get("schema_version") != RUN_MANAGER_LOG_SCHEMA_VERSION:
        msg = (
            f"Run manager output schema_version must be {RUN_MANAGER_LOG_SCHEMA_VERSION}, "
            f"got {plain_run_manager_log.get('schema_version')}"
        )
        raise ValueError(msg)
    missing_fields = [
        field_name
        for field_name in RUN_MANAGER_LOG_REQUIRED_FIELDS
        if field_name not in plain_run_manager_log
    ]
    if missing_fields:
        msg = "Run manager output missing required fields: " + ", ".join(missing_fields)
        raise ValueError(msg)
    assert_json_serializable(plain_run_manager_log)
    return plain_run_manager_log


def _validation_error_text(trace: Mapping[str, Any]) -> str:
    errors = trace.get("validation_errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(item) for item in errors)
    return "unknown run manager validation failure"


def run_live_run_manager(
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
            "run_manager",
            input_payload,
            "run_manager_log",
            out_dir,
        )
        parsed_output = trace_result.get("parsed_output")
        if not isinstance(parsed_output, Mapping):
            msg = (
                "Run manager LLM runtime did not return a valid parsed_output: "
                + "; ".join(str(item) for item in trace_result.get("validation_errors", []))
                if isinstance(trace_result.get("validation_errors"), list)
                else "Run manager LLM runtime did not return a valid parsed_output."
            )
            raise ValueError(msg)
        return _validated_run_manager_log(parsed_output)

    trace = llm_runtime.run_agent(
        "run_manager",
        input_payload,
        "run_manager_log",
    )
    parsed_output = trace.get("parsed_output")
    if not isinstance(parsed_output, Mapping):
        msg = (
            "Run manager LLM runtime did not return a valid parsed_output: "
            + _validation_error_text(trace)
        )
        raise ValueError(msg)
    return _validated_run_manager_log(parsed_output)


__all__ = [
    "RUN_MANAGER_LOG_REQUIRED_FIELDS",
    "run_live_run_manager",
]
