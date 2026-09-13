"""Deterministic immutable execution-budget accounting."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from .models import _strict_payload


class BudgetExceededError(RuntimeError):
    pass


class BudgetResource(str, Enum):
    WORKFLOW_RUNS = "workflow_runs"
    REPAIR_ATTEMPTS = "repair_attempts"
    RETRIEVAL_RETRIES = "retrieval_retries"
    MODEL_FORMAT_RETRIES = "model_format_retries"
    WALL_CLOCK_SECONDS = "wall_clock_seconds"


_LIMIT_FIELD = {
    BudgetResource.WORKFLOW_RUNS: "max_workflow_runs",
    BudgetResource.REPAIR_ATTEMPTS: "max_repair_attempts",
    BudgetResource.RETRIEVAL_RETRIES: "max_retrieval_retries",
    BudgetResource.MODEL_FORMAT_RETRIES: "max_model_format_retries",
    BudgetResource.WALL_CLOCK_SECONDS: "max_wall_clock_seconds",
}
_USAGE_FIELD = {
    BudgetResource.WORKFLOW_RUNS: "workflow_runs_used",
    BudgetResource.REPAIR_ATTEMPTS: "repair_attempts_used",
    BudgetResource.RETRIEVAL_RETRIES: "retrieval_retries_used",
    BudgetResource.MODEL_FORMAT_RETRIES: "model_format_retries_used",
    BudgetResource.WALL_CLOCK_SECONDS: "elapsed_seconds",
}


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    max_workflow_runs: int = 2
    max_repair_attempts: int = 1
    max_retrieval_retries: int = 1
    max_model_format_retries: int = 2
    max_wall_clock_seconds: int = 3600

    def __post_init__(self) -> None:
        if any(type(getattr(self, f)) is not int or getattr(self, f) < 0 for f in self.__dataclass_fields__):
            raise ValueError("budget limits must be non-negative integers")

    def to_dict(self) -> dict[str, int]:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Any) -> "BudgetLimits":
        return cls(**_strict_payload(value, set(cls.__dataclass_fields__)))


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    workflow_runs_used: int = 0
    repair_attempts_used: int = 0
    retrieval_retries_used: int = 0
    model_format_retries_used: int = 0
    elapsed_seconds: int = 0

    def __post_init__(self) -> None:
        if any(type(getattr(self, f)) is not int or getattr(self, f) < 0 for f in self.__dataclass_fields__):
            raise ValueError("budget usage must be non-negative integers")

    def to_dict(self) -> dict[str, int]:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Any) -> "BudgetUsage":
        return cls(**_strict_payload(value, set(cls.__dataclass_fields__)))


@dataclass(frozen=True, slots=True)
class AgentBudgets:
    limits: BudgetLimits = BudgetLimits()
    usage: BudgetUsage = BudgetUsage()

    def __post_init__(self) -> None:
        for resource in BudgetResource:
            if self.remaining(resource) < 0:
                raise BudgetExceededError(f"usage exceeds {resource.value} limit")

    def remaining(self, resource: BudgetResource) -> int:
        resource = BudgetResource(resource)
        return getattr(self.limits, _LIMIT_FIELD[resource]) - getattr(self.usage, _USAGE_FIELD[resource])

    def exhausted(self, resource: BudgetResource | None = None) -> bool:
        if resource is not None:
            return self.remaining(resource) == 0
        return any(self.remaining(item) == 0 for item in BudgetResource)

    def can_consume(self, resource: BudgetResource, amount: int = 1) -> bool:
        if type(amount) is not int or amount < 0:
            raise ValueError("budget amount must be a non-negative integer")
        return amount <= self.remaining(BudgetResource(resource))

    def consume(self, resource: BudgetResource, amount: int = 1) -> "AgentBudgets":
        resource = BudgetResource(resource)
        if not self.can_consume(resource, amount):
            raise BudgetExceededError(f"consuming {amount} would exceed {resource.value} budget")
        field_name = _USAGE_FIELD[resource]
        usage = replace(self.usage, **{field_name: getattr(self.usage, field_name) + amount})
        return replace(self, usage=usage)

    def to_dict(self) -> dict[str, Any]:
        return {"limits": self.limits.to_dict(), "usage": self.usage.to_dict()}

    @classmethod
    def from_dict(cls, value: Any) -> "AgentBudgets":
        p = _strict_payload(value, {"limits", "usage"})
        return cls(BudgetLimits.from_dict(p.get("limits", {})), BudgetUsage.from_dict(p.get("usage", {})))


__all__ = ["AgentBudgets", "BudgetExceededError", "BudgetLimits", "BudgetResource", "BudgetUsage"]
