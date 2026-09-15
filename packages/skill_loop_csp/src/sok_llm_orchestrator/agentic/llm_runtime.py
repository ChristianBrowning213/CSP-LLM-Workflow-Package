from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .prompting import render_agent_prompt
from .schemas import (
    ORCHESTRATOR_DECISION_SCHEMA_VERSION,
    RUN_EVALUATION_SCHEMA_VERSION,
    RUN_MANAGER_LOG_SCHEMA_VERSION,
    RUN_PLAN_SCHEMA_VERSION,
    assert_json_serializable,
    to_json_dict,
)

SCHEMA_VERSION_BY_NAME = {
    "run_plan": RUN_PLAN_SCHEMA_VERSION,
    "run_manager_log": RUN_MANAGER_LOG_SCHEMA_VERSION,
    "run_evaluation": RUN_EVALUATION_SCHEMA_VERSION,
    "orchestrator_decision": ORCHESTRATOR_DECISION_SCHEMA_VERSION,
}

SCHEMA_NAME_BY_AGENT = {
    "planner": "run_plan",
    "run_manager": "run_manager_log",
    "evaluator": "run_evaluation",
    "orchestrator": "orchestrator_decision",
}

REQUIRED_TOP_LEVEL_FIELDS_BY_SCHEMA = {
    RUN_PLAN_SCHEMA_VERSION: [
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
    ],
    RUN_MANAGER_LOG_SCHEMA_VERSION: [
        "schema_version",
        "run_id",
        "tool_calls_attempted",
        "failures_handled",
        "manager_notes",
        "artifacts_created",
    ],
    RUN_EVALUATION_SCHEMA_VERSION: [
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
    ],
    ORCHESTRATOR_DECISION_SCHEMA_VERSION: [
        "schema_version",
        "decision",
        "reason",
        "next_run_goal",
        "current_stage",
        "evidence_used",
        "user_message_if_stopping",
        "clarification_question_if_needed",
    ],
}

EXPECTED_TOP_LEVEL_TYPES_BY_SCHEMA: dict[str, dict[str, tuple[type, ...]]] = {
    RUN_EVALUATION_SCHEMA_VERSION: {
        "schema_version": (str,),
        "run_id": (str,),
        "run_goal": (str,),
        "run_goal_success": (bool,),
        "overall_goal_progress": (str,),
        "summary": (str,),
        "what_worked": (list,),
        "what_failed_or_was_weak": (list,),
        "scientific_findings": (list,),
        "best_artifacts": (list,),
        "scores": (dict,),
        "comparison_to_previous_best": (str,),
        "recommended_next_run": (str,),
        "should_stop": (bool,),
        "stop_reason": (str, type(None)),
        "needs_user_clarification": (bool,),
        "clarification_question": (str, type(None)),
    },
    ORCHESTRATOR_DECISION_SCHEMA_VERSION: {
        "schema_version": (str,),
        "decision": (str,),
        "reason": (str,),
        "next_run_goal": (str, type(None)),
        "current_stage": (str,),
        "evidence_used": (list,),
        "user_message_if_stopping": (str, type(None)),
        "clarification_question_if_needed": (str, type(None)),
    },
}


def _expected_schema_version(expected_schema_name: str) -> str:
    if expected_schema_name in SCHEMA_VERSION_BY_NAME:
        return SCHEMA_VERSION_BY_NAME[expected_schema_name]
    if expected_schema_name in SCHEMA_VERSION_BY_NAME.values():
        return expected_schema_name
    msg = f"Unknown expected schema name: {expected_schema_name}"
    raise KeyError(msg)


def _extract_message_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        return ""
    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_json_object(text: str) -> dict[str, Any]:
    candidates = [_strip_json_fence(text)]
    stripped = candidates[0]
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
        candidates.append(stripped[first_brace : last_brace + 1])

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(parsed, dict):
            msg = "LLM output must be a JSON object."
            raise ValueError(msg)
        return to_json_dict(parsed)

    msg = f"Malformed JSON object: {last_error}"
    raise ValueError(msg)


def _validate_schema_output(
    parsed_output: Mapping[str, Any],
    expected_schema_version: str,
) -> dict[str, Any]:
    schema_version = parsed_output.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version.strip():
        msg = "schema_version is required in parsed output."
        raise ValueError(msg)
    if schema_version != expected_schema_version:
        msg = (
            f"schema_version must be {expected_schema_version}, "
            f"got {schema_version}"
        )
        raise ValueError(msg)
    missing_fields = [
        field_name
        for field_name in REQUIRED_TOP_LEVEL_FIELDS_BY_SCHEMA.get(expected_schema_version, [])
        if field_name not in parsed_output
    ]
    if missing_fields:
        msg = (
            "Missing required top-level fields: "
            + ", ".join(missing_fields)
            + ". Do not nest them under metadata or another object."
        )
        raise ValueError(msg)
    type_errors: list[str] = []
    for field_name, expected_types in EXPECTED_TOP_LEVEL_TYPES_BY_SCHEMA.get(
        expected_schema_version, {}
    ).items():
        if field_name not in parsed_output:
            continue
        field_value = parsed_output[field_name]
        if not isinstance(field_value, expected_types):
            expected_type_names = ", ".join(expected_type.__name__ for expected_type in expected_types)
            actual_type_name = type(field_value).__name__
            type_errors.append(
                f"{field_name} must be one of [{expected_type_names}], got {actual_type_name}"
            )
    if type_errors:
        msg = "Invalid top-level field types: " + "; ".join(type_errors)
        raise ValueError(msg)
    plain_output = to_json_dict(parsed_output)
    assert_json_serializable(plain_output)
    return plain_output


@dataclass(slots=True)
class AgentLLMRuntime:
    client: Any
    max_attempts: int = 3
    validation_errors_limit: int = 12
    extra_chat_kwargs: dict[str, Any] = field(default_factory=dict)

    def run_agent(
        self,
        agent_name: str,
        input_payload: Mapping[str, Any],
        expected_schema_name: str,
    ) -> dict[str, Any]:
        if not isinstance(input_payload, Mapping):
            msg = "input_payload must be a mapping"
            raise TypeError(msg)

        expected_schema_version = _expected_schema_version(expected_schema_name)
        required_fields = REQUIRED_TOP_LEVEL_FIELDS_BY_SCHEMA.get(expected_schema_version, [])
        system_prompt = render_agent_prompt(
            agent_name,
            {
                "agent_name": agent_name,
                "expected_schema_name": expected_schema_name,
                "expected_schema_version": expected_schema_version,
                "required_top_level_fields": required_fields,
            },
        )
        user_payload = {
            "expected_schema_name": expected_schema_name,
            "expected_schema_version": expected_schema_version,
            "required_top_level_fields": required_fields,
            "output_rules": [
                "Return exactly one JSON object.",
                "Use the required top-level fields exactly as listed.",
                "Do not nest required fields under metadata.",
                "Do not include markdown fences or prose outside the JSON object.",
            ],
            "input_payload": dict(input_payload),
        }
        user_content = json.dumps(user_payload, indent=2, sort_keys=True)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        attempt_records: list[dict[str, Any]] = []
        validation_errors: list[str] = []
        raw_output = ""
        parsed_output: dict[str, Any] | None = None

        for attempt_number in range(1, self.max_attempts + 1):
            response = self.client.chat(messages=messages, **self.extra_chat_kwargs)
            raw_output = _extract_message_content(response)
            attempt_errors: list[str] = []

            try:
                parsed_candidate = _parse_json_object(raw_output)
                parsed_output = _validate_schema_output(
                    parsed_candidate,
                    expected_schema_version,
                )
            except (TypeError, ValueError) as exc:
                parsed_output = None
                attempt_errors.append(str(exc))
                validation_errors.append(str(exc))

            attempt_records.append(
                {
                    "attempt_number": attempt_number,
                    "raw_output": raw_output,
                    "validation_errors": list(attempt_errors),
                }
            )

            if parsed_output is not None:
                break

            if attempt_number < self.max_attempts:
                messages.extend(
                    [
                        {"role": "assistant", "content": raw_output},
                        {
                            "role": "user",
                            "content": (
                                "Return exactly one valid JSON object only. "
                                f"Required schema_version: {expected_schema_version}. "
                                "Required top-level fields: "
                                f"{required_fields}. "
                                "Do not nest required fields under metadata. "
                                f"Previous validation errors: {attempt_errors}"
                            ),
                        },
                    ]
                )

        result = {
            "agent_name": agent_name,
            "expected_schema_name": expected_schema_name,
            "expected_schema_version": expected_schema_version,
            "runtime_context": {
                "base_url": str(getattr(self.client, "base_url", "")),
                "model": str(getattr(self.client, "model", "")),
            },
            "system_prompt": system_prompt,
            "user_payload": user_payload,
            "parsed_output": parsed_output,
            "raw_output": raw_output,
            "attempts": attempt_records,
            "validation_errors": validation_errors[: self.validation_errors_limit],
        }
        assert_json_serializable(result)
        return result


__all__ = [
    "SCHEMA_NAME_BY_AGENT",
    "SCHEMA_VERSION_BY_NAME",
    "AgentLLMRuntime",
]
