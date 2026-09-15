from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

SESSION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "session_id",
        "status",
        "task_spec",
        "clarification_state",
        "optimization_plan",
        "budget_state",
        "iteration_history",
        "best_so_far",
        "blocked_state",
        "termination_reason",
        "conversation_history",
        "policy_state",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "optimization.session.v1"},
        "session_id": {"type": "string", "minLength": 1},
        "status": {
            "type": "string",
            "enum": [
                "PENDING_CLARIFICATION",
                "READY",
                "RUNNING",
                "WAITING_CLARIFICATION",
                "STOPPED",
                "COMPLETED",
                "FAILED",
            ],
        },
        "task_spec": {"type": "object"},
        "clarification_state": {"type": "object"},
        "optimization_plan": {"type": ["object", "null"]},
        "budget_state": {"type": "object"},
        "iteration_history": {"type": "array", "items": {"type": "object"}},
        "best_so_far": {"type": ["object", "null"]},
        "blocked_state": {"type": ["object", "null"]},
        "termination_reason": {"type": ["string", "null"]},
        "conversation_history": {"type": "array", "items": {"type": "object"}},
        "policy_state": {"type": "object"},
        "hypothesis_state": {"type": "object"},
    },
}


def stable_session_id(
    task_spec: dict[str, Any],
    mode: str,
    budget_signature: dict[str, Any],
    seed_hint: str = "default",
) -> str:
    payload = {
        "budget_signature": budget_signature,
        "mode": mode,
        "seed_hint": seed_hint,
        "task_spec": task_spec,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


@dataclass(slots=True)
class OptimizationSession:
    session_id: str
    status: str
    task_spec: dict[str, Any]
    clarification_state: dict[str, Any]
    optimization_plan: dict[str, Any] | None
    budget_state: dict[str, Any]
    iteration_history: list[dict[str, Any]] = field(default_factory=list)
    best_so_far: dict[str, Any] | None = None
    blocked_state: dict[str, Any] | None = None
    termination_reason: str | None = None
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    policy_state: dict[str, Any] = field(default_factory=dict)
    hypothesis_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "optimization.session.v1",
            "session_id": self.session_id,
            "status": self.status,
            "task_spec": self.task_spec,
            "clarification_state": self.clarification_state,
            "optimization_plan": self.optimization_plan,
            "budget_state": self.budget_state,
            "iteration_history": list(self.iteration_history),
            "best_so_far": self.best_so_far,
            "blocked_state": self.blocked_state,
            "termination_reason": self.termination_reason,
            "conversation_history": list(self.conversation_history),
            "policy_state": dict(self.policy_state),
            "hypothesis_state": dict(self.hypothesis_state),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OptimizationSession":
        validate_optimization_session(payload)
        return cls(
            session_id=payload["session_id"],
            status=payload["status"],
            task_spec=payload["task_spec"],
            clarification_state=payload["clarification_state"],
            optimization_plan=payload.get("optimization_plan"),
            budget_state=payload["budget_state"],
            iteration_history=list(payload.get("iteration_history", [])),
            best_so_far=payload.get("best_so_far"),
            blocked_state=payload.get("blocked_state"),
            termination_reason=payload.get("termination_reason"),
            conversation_history=list(payload.get("conversation_history", [])),
            policy_state=dict(payload.get("policy_state", {})),
            hypothesis_state=dict(payload.get("hypothesis_state", {})),
        )


def validate_optimization_session(payload: dict[str, Any]) -> None:
    validator = Draft202012Validator(SESSION_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        pointer = "/" + "/".join(str(x) for x in err.absolute_path)
        raise ValueError(f"{pointer}: {err.message}")
