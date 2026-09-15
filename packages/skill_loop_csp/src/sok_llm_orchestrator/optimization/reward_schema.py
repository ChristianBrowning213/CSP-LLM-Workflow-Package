from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

REWARD_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "action_id",
        "action_family",
        "primary_objective",
        "feasibility",
        "solver_stability",
        "novelty",
        "property_estimate",
        "analogue_quality",
        "valid_for_learning",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "optimization.reward.v1"},
        "action_id": {"type": "string"},
        "action_family": {"type": "string"},
        "primary_objective": {"type": ["number", "null"]},
        "feasibility": {"type": "boolean"},
        "solver_stability": {"type": ["number", "null"]},
        "novelty": {"type": ["number", "null"]},
        "property_estimate": {"type": ["number", "null"]},
        "analogue_quality": {"type": ["number", "null"]},
        "valid_for_learning": {"type": "boolean"},
        "run_reference": {"type": ["object", "null"]},
    },
}


@dataclass(slots=True)
class RewardRecord:
    action_id: str
    action_family: str
    primary_objective: float | None
    feasibility: bool
    solver_stability: float | None = None
    novelty: float | None = None
    property_estimate: float | None = None
    analogue_quality: float | None = None
    valid_for_learning: bool = True
    run_reference: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "optimization.reward.v1",
            "action_id": self.action_id,
            "action_family": self.action_family,
            "primary_objective": self.primary_objective,
            "feasibility": self.feasibility,
            "solver_stability": self.solver_stability,
            "novelty": self.novelty,
            "property_estimate": self.property_estimate,
            "analogue_quality": self.analogue_quality,
            "valid_for_learning": self.valid_for_learning,
            "run_reference": self.run_reference,
        }


def validate_reward_record(payload: dict[str, Any]) -> None:
    validator = Draft202012Validator(REWARD_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        pointer = "/" + "/".join(str(x) for x in err.absolute_path)
        raise ValueError(f"{pointer}: {err.message}")

