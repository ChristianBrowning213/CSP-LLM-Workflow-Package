from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

DIAGNOSTIC_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "failure_type", "probable_cause", "evidence", "suggested_deltas"],
    "properties": {
        "schema_version": {"type": "string", "const": "diagnostic_report.v1"},
        "failure_type": {"type": "string"},
        "probable_cause": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "suggested_deltas": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass(slots=True)
class DiagnosticReport:
    failure_type: str
    probable_cause: str
    evidence: list[str]
    suggested_deltas: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "diagnostic_report.v1",
            "failure_type": self.failure_type,
            "probable_cause": self.probable_cause,
            "evidence": self.evidence,
            "suggested_deltas": self.suggested_deltas,
        }


def validate_diagnostic_report(payload: dict[str, Any]) -> None:
    validator = Draft202012Validator(DIAGNOSTIC_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        pointer = "/" + "/".join(str(x) for x in err.absolute_path)
        raise ValueError(f"{pointer}: {err.message}")
