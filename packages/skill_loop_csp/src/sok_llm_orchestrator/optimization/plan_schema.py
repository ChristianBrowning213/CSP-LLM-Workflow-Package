from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

OPTIMIZATION_PLAN_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "objective_target",
        "initial_hypotheses",
        "action_family_priorities",
        "exploration_strategy",
        "stopping_criteria",
        "fallback_strategy",
        "escalation_conditions",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "optimization.plan.v1"},
        "objective_target": {"type": "string", "minLength": 1},
        "initial_hypotheses": {"type": "array", "items": {"type": "string"}},
        "action_family_priorities": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "exploration_strategy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["policy", "exploration_rate"],
            "properties": {
                "policy": {"type": "string", "enum": ["epsilon_greedy"]},
                "exploration_rate": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        },
        "stopping_criteria": {"type": "object", "additionalProperties": True},
        "fallback_strategy": {"type": "array", "items": {"type": "string"}},
        "escalation_conditions": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass(slots=True)
class OptimizationPlan:
    objective_target: str
    initial_hypotheses: list[str] = field(default_factory=list)
    action_family_priorities: list[str] = field(default_factory=list)
    exploration_strategy: dict[str, Any] = field(default_factory=dict)
    stopping_criteria: dict[str, Any] = field(default_factory=dict)
    fallback_strategy: list[str] = field(default_factory=list)
    escalation_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "optimization.plan.v1",
            "objective_target": self.objective_target,
            "initial_hypotheses": list(self.initial_hypotheses),
            "action_family_priorities": list(self.action_family_priorities),
            "exploration_strategy": dict(self.exploration_strategy),
            "stopping_criteria": dict(self.stopping_criteria),
            "fallback_strategy": list(self.fallback_strategy),
            "escalation_conditions": list(self.escalation_conditions),
        }


def validate_optimization_plan(payload: dict[str, Any]) -> None:
    validator = Draft202012Validator(OPTIMIZATION_PLAN_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        pointer = "/" + "/".join(str(x) for x in err.absolute_path)
        raise ValueError(f"{pointer}: {err.message}")

