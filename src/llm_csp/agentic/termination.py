"""Authoritative run and low-level transition semantics."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum

from .models import PlanStep, PlanStepStatus, ToolCall, ToolCallStatus


class AgentRunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"
    NO_VALID_CANDIDATE = "NO_VALID_CANDIDATE"
    SOLVER_INFEASIBLE = "SOLVER_INFEASIBLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    USER_INPUT_REQUIRED = "USER_INPUT_REQUIRED"
    SYSTEM_ERROR = "SYSTEM_ERROR"


TERMINAL_STATUSES = frozenset(AgentRunStatus) - {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}


def is_terminal(status: AgentRunStatus) -> bool:
    if not isinstance(status, AgentRunStatus):
        raise TypeError("status must be an AgentRunStatus")
    return status in TERMINAL_STATUSES


_STEP_TRANSITIONS = {
    PlanStepStatus.PENDING: {PlanStepStatus.READY, PlanStepStatus.AWAITING_APPROVAL, PlanStepStatus.SKIPPED, PlanStepStatus.BLOCKED},
    PlanStepStatus.READY: {PlanStepStatus.AWAITING_APPROVAL, PlanStepStatus.RUNNING, PlanStepStatus.SKIPPED, PlanStepStatus.BLOCKED},
    PlanStepStatus.AWAITING_APPROVAL: {PlanStepStatus.READY, PlanStepStatus.SKIPPED, PlanStepStatus.BLOCKED},
    PlanStepStatus.RUNNING: {PlanStepStatus.SUCCEEDED, PlanStepStatus.FAILED, PlanStepStatus.BLOCKED},
}
_TOOL_TRANSITIONS = {
    ToolCallStatus.PROPOSED: {ToolCallStatus.APPROVAL_REQUIRED, ToolCallStatus.APPROVED, ToolCallStatus.RUNNING, ToolCallStatus.REJECTED},
    ToolCallStatus.APPROVAL_REQUIRED: {ToolCallStatus.APPROVED, ToolCallStatus.REJECTED},
    ToolCallStatus.APPROVED: {ToolCallStatus.RUNNING, ToolCallStatus.REJECTED},
    ToolCallStatus.RUNNING: {ToolCallStatus.SUCCEEDED, ToolCallStatus.FAILED},
}


def transition_plan_step(step: PlanStep, status: PlanStepStatus) -> PlanStep:
    target = PlanStepStatus(status)
    if target not in _STEP_TRANSITIONS.get(step.status, set()):
        raise ValueError(f"illegal plan-step transition: {step.status.value} -> {target.value}")
    return replace(step, status=target)


def transition_tool_call(call: ToolCall, status: ToolCallStatus, *, result_ref: str | None = None) -> ToolCall:
    target = ToolCallStatus(status)
    if target not in _TOOL_TRANSITIONS.get(call.status, set()):
        raise ValueError(f"illegal tool-call transition: {call.status.value} -> {target.value}")
    return replace(call, status=target, result_ref=result_ref if result_ref is not None else call.result_ref)


__all__ = ["AgentRunStatus", "TERMINAL_STATUSES", "is_terminal", "transition_plan_step", "transition_tool_call"]
