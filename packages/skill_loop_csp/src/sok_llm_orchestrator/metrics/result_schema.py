from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

RESULT_ROW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "case_id",
        "run_family",
        "feasible",
        "time_to_first_feasible_s",
        "objective_value",
        "retry_count",
        "analogue_distance",
        "space_group_match",
        "evidence_completeness",
        "reproducible",
    ],
    "properties": {
        "case_id": {"type": "string", "minLength": 1},
        "run_family": {"type": "string", "minLength": 1},
        "feasible": {"type": "boolean"},
        "time_to_first_feasible_s": {"type": ["number", "null"], "minimum": 0},
        "objective_value": {"type": ["number", "null"]},
        "retry_count": {"type": "integer", "minimum": 0},
        "analogue_distance": {"type": ["number", "null"], "minimum": 0},
        "space_group_match": {"type": "boolean"},
        "evidence_completeness": {"type": "number", "minimum": 0, "maximum": 1},
        "reproducible": {"type": "boolean"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}

RESULT_PAYLOAD_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "generated_at", "rows"],
    "properties": {
        "schema_version": {"type": "string", "const": "metrics.result.v1"},
        "generated_at": {"type": "string"},
        "rows": {"type": "array", "items": RESULT_ROW_SCHEMA},
        "summary": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "total_cases": {"type": "integer", "minimum": 0},
                "feasibility_rate": {"type": "number", "minimum": 0, "maximum": 1},
                "guided_win_rate": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            },
        },
    },
}


def validate_result_payload(payload: dict[str, Any]) -> None:
    validator = Draft202012Validator(RESULT_PAYLOAD_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = "/" + "/".join(str(x) for x in first.absolute_path)
        raise ValueError(f"{path}: {first.message}")
