"""Versioned immutable state and safe run-root boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from uuid import UUID, uuid4

from .approvals import ApprovalRequest
from .budgets import AgentBudgets
from .models import (
    AgentPlan,
    ApprovalStatus,
    ArtifactReference,
    DecisionRecord,
    EvaluationRecord,
    ParsedIntent,
    PlanStepStatus,
    ToolCall,
    ToolCallStatus,
    WorkflowRunReference,
    _non_empty,
    _strict_payload,
)
from .termination import AgentRunStatus, is_terminal
from .schemas import AGENT_STATE_SCHEMA_VERSION, AGENT_STATE_SCHEMA_VERSION_NUMBER


def utc_now_iso(clock: Callable[[], datetime] | None = None) -> str:
    value = (clock or (lambda: datetime.now(timezone.utc)))()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def new_identifier(prefix: str, uuid_factory: Callable[[], UUID] = uuid4) -> str:
    _non_empty(prefix, "prefix")
    if not prefix.replace("_", "").isalnum():
        raise ValueError("identifier prefix must contain only letters, numbers, and underscores")
    return f"{prefix}_{uuid_factory().hex}"


def new_agent_run_id(uuid_factory: Callable[[], UUID] = uuid4) -> str:
    return new_identifier("agent_run", uuid_factory)


def new_plan_id(uuid_factory: Callable[[], UUID] = uuid4) -> str:
    return new_identifier("plan", uuid_factory)


def new_step_id(uuid_factory: Callable[[], UUID] = uuid4) -> str:
    return new_identifier("step", uuid_factory)


def new_decision_id(uuid_factory: Callable[[], UUID] = uuid4) -> str:
    return new_identifier("decision", uuid_factory)


def new_tool_call_id(uuid_factory: Callable[[], UUID] = uuid4) -> str:
    return new_identifier("tool_call", uuid_factory)


def new_approval_id(uuid_factory: Callable[[], UUID] = uuid4) -> str:
    return new_identifier("approval", uuid_factory)


def new_artifact_id(uuid_factory: Callable[[], UUID] = uuid4) -> str:
    return new_identifier("artifact", uuid_factory)


@dataclass(frozen=True, slots=True)
class WriteScope:
    run_root: str

    def __post_init__(self) -> None:
        _non_empty(self.run_root, "run_root")
        object.__setattr__(self, "run_root", str(Path(self.run_root).resolve()))

    def resolve(self, relative_path: str) -> Path:
        _non_empty(relative_path, "relative_path")
        posix, windows = PurePosixPath(relative_path), PureWindowsPath(relative_path)
        if posix.is_absolute() or windows.is_absolute() or windows.drive:
            raise ValueError("path must be relative to the configured run root")
        if ".." in posix.parts or ".." in windows.parts:
            raise ValueError("path traversal outside the configured run root is forbidden")
        root = Path(self.run_root)
        candidate = (root / Path(*posix.parts)).resolve()
        try:
            inside = os.path.commonpath((str(root), str(candidate))) == str(root)
        except ValueError:
            inside = False
        if not inside:
            raise ValueError("resolved path is outside the configured run root")
        return candidate

    def resolve_artifact(self, reference: ArtifactReference) -> Path:
        return self.resolve(reference.path)


@dataclass(frozen=True, slots=True)
class AgentRunState:
    agent_run_id: str
    user_goal: str
    parsed_intent: ParsedIntent
    plan: AgentPlan
    workflow_runs: tuple[WorkflowRunReference, ...] = ()
    decisions: tuple[DecisionRecord, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    current_candidate: ArtifactReference | None = None
    evaluation: EvaluationRecord | None = None
    budgets: AgentBudgets = AgentBudgets()
    approvals: tuple[ApprovalRequest, ...] = ()
    status: AgentRunStatus = AgentRunStatus.PENDING
    pending_user_action: str | None = None
    schema_version: str = AGENT_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _non_empty(self.agent_run_id, "agent_run_id")
        _non_empty(self.user_goal, "user_goal")
        if self.schema_version != AGENT_STATE_SCHEMA_VERSION:
            raise ValueError(f"unsupported agent state schema version: {self.schema_version}")
        object.__setattr__(self, "workflow_runs", tuple(self.workflow_runs))
        object.__setattr__(self, "decisions", tuple(self.decisions))
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(self, "approvals", tuple(self.approvals))
        object.__setattr__(self, "status", AgentRunStatus(self.status))
        if self.pending_user_action is not None:
            _non_empty(self.pending_user_action, "pending_user_action")
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        groups = {
            "workflow run": [item.run_id for item in self.workflow_runs],
            "decision": [item.decision_id for item in self.decisions],
            "tool call": [item.tool_call_id for item in self.tool_calls],
            "approval": [item.approval_id for item in self.approvals],
        }
        for label, identifiers in groups.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{label} IDs must be unique")

        artifacts = [
            artifact
            for run in self.workflow_runs
            for artifact in (run.result_ref, run.candidate_ref)
            if artifact is not None
        ]
        artifact_ids = [artifact.artifact_id for artifact in artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("artifact IDs must be unique")
        artifacts_by_id = {artifact.artifact_id: artifact for artifact in artifacts}
        if self.current_candidate is not None and artifacts_by_id.get(self.current_candidate.artifact_id) != self.current_candidate:
            raise ValueError("current_candidate must reference an artifact produced by a known workflow run")
        run_ids = set(groups["workflow run"])
        if self.evaluation is not None:
            if artifacts_by_id.get(self.evaluation.candidate_ref.artifact_id) != self.evaluation.candidate_ref:
                raise ValueError("evaluation candidate must reference a produced artifact")
            if self.evaluation.workflow_run_ref not in run_ids:
                raise ValueError("evaluation must reference a known workflow run")
        if len(self.workflow_runs) > self.budgets.usage.workflow_runs_used:
            raise ValueError("workflow-run references cannot exceed recorded workflow-run budget usage")

        tool_ids = set(groups["tool call"])
        for decision in self.decisions:
            if decision.result_ref is not None and decision.result_ref not in tool_ids:
                raise ValueError("decision result_ref must point to a known tool call")
        for call in self.tool_calls:
            if call.result_ref is not None and call.result_ref not in artifacts_by_id and call.result_ref not in run_ids:
                raise ValueError("tool-call result_ref must point to a known result artifact or workflow run")

        request_refs = set(self.plan_step_ids) | tool_ids | set(groups["decision"])
        for approval in self.approvals:
            if approval.status is ApprovalStatus.APPROVED and approval.request_ref not in request_refs:
                raise ValueError("approved approval must reference an existing plan step, tool call, or decision")
        if self.status is AgentRunStatus.SUCCESS:
            required = set(self.plan.required_approvals)
            approved_categories = {item.category for item in self.approvals if item.status is ApprovalStatus.APPROVED}
            approved_refs = {item.request_ref for item in self.approvals if item.status is ApprovalStatus.APPROVED}
            required_step_refs = {step.step_id for step in self.plan.steps if step.approval_category is not None}
            if not required <= approved_categories or not required_step_refs <= approved_refs:
                raise ValueError("SUCCESS requires every required approval to be approved")
        if is_terminal(self.status):
            active_steps = {PlanStepStatus.READY, PlanStepStatus.AWAITING_APPROVAL, PlanStepStatus.RUNNING}
            active_calls = {ToolCallStatus.PROPOSED, ToolCallStatus.APPROVAL_REQUIRED, ToolCallStatus.APPROVED, ToolCallStatus.RUNNING}
            if any(step.status in active_steps for step in self.plan.steps) or any(call.status in active_calls for call in self.tool_calls):
                raise ValueError("terminal state cannot contain pending planned execution")

    @property
    def plan_step_ids(self) -> tuple[str, ...]:
        return tuple(step.step_id for step in self.plan.steps)

    def transition_status(self, status: AgentRunStatus) -> "AgentRunState":
        target = AgentRunStatus(status)
        if is_terminal(self.status):
            raise ValueError("terminal agent state cannot transition; start a new run")
        if self.status is AgentRunStatus.PENDING and target not in {AgentRunStatus.RUNNING, AgentRunStatus.BLOCKED,
                                                                  AgentRunStatus.USER_INPUT_REQUIRED, AgentRunStatus.SYSTEM_ERROR}:
            raise ValueError(f"illegal run transition: PENDING -> {target.value}")
        if target is AgentRunStatus.PENDING or target is self.status:
            raise ValueError(f"illegal run transition: {self.status.value} -> {target.value}")
        return replace(self, status=target)

    def append_decision(self, decision: DecisionRecord) -> "AgentRunState":
        if is_terminal(self.status):
            raise ValueError("terminal agent state cannot accept a new decision")
        return replace(self, decisions=(*self.decisions, decision))

    def append_tool_call(self, tool_call: ToolCall) -> "AgentRunState":
        if is_terminal(self.status):
            raise ValueError("terminal agent state cannot accept a tool call")
        return replace(self, tool_calls=(*self.tool_calls, tool_call))

    def replace_tool_call(self, tool_call: ToolCall) -> "AgentRunState":
        if is_terminal(self.status):
            raise ValueError("terminal agent state cannot update a tool call")
        matches = [index for index, item in enumerate(self.tool_calls) if item.tool_call_id == tool_call.tool_call_id]
        if len(matches) != 1:
            raise ValueError("tool call must already exist exactly once in state")
        calls = list(self.tool_calls)
        existing = calls[matches[0]]
        if (
            existing.tool_name is not tool_call.tool_name
            or existing.arguments != tool_call.arguments
            or existing.requested_by is not tool_call.requested_by
        ):
            raise ValueError("tool-call replacement cannot change immutable request identity")
        from .termination import transition_tool_call

        if existing.status is ToolCallStatus.RUNNING:
            transition_tool_call(existing, tool_call.status, result_ref=tool_call.result_ref)
        elif tool_call.status in {ToolCallStatus.SUCCEEDED, ToolCallStatus.FAILED}:
            running = transition_tool_call(existing, ToolCallStatus.RUNNING)
            transition_tool_call(running, tool_call.status, result_ref=tool_call.result_ref)
        else:
            transition_tool_call(existing, tool_call.status, result_ref=tool_call.result_ref)
        calls[matches[0]] = tool_call
        return replace(self, tool_calls=tuple(calls))

    def append_workflow_run(self, workflow_run: WorkflowRunReference) -> "AgentRunState":
        if is_terminal(self.status):
            raise ValueError("terminal agent state cannot accept a workflow run")
        from .budgets import BudgetResource

        budgets = self.budgets.consume(BudgetResource.WORKFLOW_RUNS)
        return replace(self, workflow_runs=(*self.workflow_runs, workflow_run), budgets=budgets)

    def append_approval(self, approval: ApprovalRequest) -> "AgentRunState":
        return replace(self, approvals=(*self.approvals, approval))

    def set_current_candidate(self, candidate: ArtifactReference) -> "AgentRunState":
        if is_terminal(self.status):
            raise ValueError("terminal agent state cannot change its candidate")
        return replace(self, current_candidate=candidate)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "agent_run_id": self.agent_run_id,
            "user_goal": self.user_goal,
            "parsed_intent": self.parsed_intent.to_dict(),
            "plan": self.plan.to_dict(),
            "workflow_runs": [item.to_dict() for item in self.workflow_runs],
            "decisions": [item.to_dict() for item in self.decisions],
            "tool_calls": [item.to_dict() for item in self.tool_calls],
            "current_candidate": self.current_candidate.to_dict() if self.current_candidate else None,
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "budgets": self.budgets.to_dict(),
            "approvals": [item.to_dict() for item in self.approvals],
            "status": self.status.value,
            "pending_user_action": self.pending_user_action,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":") if indent is None else None, indent=indent)

    @classmethod
    def from_dict(cls, value: Any) -> "AgentRunState":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"agent_run_id", "user_goal", "parsed_intent", "plan"})
        p["parsed_intent"] = ParsedIntent.from_dict(p["parsed_intent"])
        p["plan"] = AgentPlan.from_dict(p["plan"])
        p["workflow_runs"] = tuple(WorkflowRunReference.from_dict(x) for x in p.get("workflow_runs", ()))
        p["decisions"] = tuple(DecisionRecord.from_dict(x) for x in p.get("decisions", ()))
        p["tool_calls"] = tuple(ToolCall.from_dict(x) for x in p.get("tool_calls", ()))
        if p.get("current_candidate") is not None:
            p["current_candidate"] = ArtifactReference.from_dict(p["current_candidate"])
        if p.get("evaluation") is not None:
            p["evaluation"] = EvaluationRecord.from_dict(p["evaluation"])
        p["budgets"] = AgentBudgets.from_dict(p.get("budgets", {}))
        p["approvals"] = tuple(ApprovalRequest.from_dict(x) for x in p.get("approvals", ()))
        return cls(**p)

    @classmethod
    def from_json(cls, value: str) -> "AgentRunState":
        return cls.from_dict(json.loads(value))


__all__ = [
    "AGENT_STATE_SCHEMA_VERSION", "AGENT_STATE_SCHEMA_VERSION_NUMBER", "AgentRunState", "WriteScope",
    "new_agent_run_id", "new_approval_id", "new_artifact_id", "new_decision_id", "new_identifier",
    "new_plan_id", "new_step_id", "new_tool_call_id", "utc_now_iso",
]
