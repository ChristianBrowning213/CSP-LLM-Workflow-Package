from __future__ import annotations

from typing import Any, Mapping

from .archive import write_agentic_llm_trace
from .schemas import ORCHESTRATOR_DECISION_SCHEMA_VERSION, assert_json_serializable, to_json_dict

ORCHESTRATOR_DECISION_REQUIRED_FIELDS = [
    "schema_version",
    "decision",
    "reason",
    "next_run_goal",
    "current_stage",
    "evidence_used",
    "user_message_if_stopping",
    "clarification_question_if_needed",
]


def _validated_orchestrator_decision(
    orchestrator_decision: Mapping[str, Any],
) -> dict[str, Any]:
    plain_orchestrator_decision = to_json_dict(orchestrator_decision)
    if plain_orchestrator_decision.get("schema_version") != ORCHESTRATOR_DECISION_SCHEMA_VERSION:
        msg = (
            f"Orchestrator output schema_version must be {ORCHESTRATOR_DECISION_SCHEMA_VERSION}, "
            f"got {plain_orchestrator_decision.get('schema_version')}"
        )
        raise ValueError(msg)
    missing_fields = [
        field_name
        for field_name in ORCHESTRATOR_DECISION_REQUIRED_FIELDS
        if field_name not in plain_orchestrator_decision
    ]
    if missing_fields:
        msg = "Orchestrator output missing required fields: " + ", ".join(missing_fields)
        raise ValueError(msg)
    assert_json_serializable(plain_orchestrator_decision)
    return plain_orchestrator_decision


def _validation_error_text(trace: Mapping[str, Any]) -> str:
    errors = trace.get("validation_errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(item) for item in errors)
    return "unknown orchestrator validation failure"


def run_live_orchestrator(
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

    trace = to_json_dict(llm_runtime.run_agent("orchestrator", input_payload, "orchestrator_decision"))
    parsed_output = trace.get("parsed_output")
    if not isinstance(parsed_output, Mapping):
        msg = "Orchestrator LLM runtime did not return a valid parsed_output: " + _validation_error_text(
            trace
        )
        raise ValueError(msg)

    orchestrator_decision = _validated_orchestrator_decision(parsed_output)
    if archive_trace:
        _ = write_agentic_llm_trace(trace, out_dir, "orchestrator")
    return orchestrator_decision


__all__ = [
    "ORCHESTRATOR_DECISION_REQUIRED_FIELDS",
    "run_live_orchestrator",
]
