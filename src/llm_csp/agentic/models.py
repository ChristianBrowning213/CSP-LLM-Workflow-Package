"""Immutable, JSON-safe records shared by the agentic layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping, TypeVar


JSONMapping = Mapping[str, Any]
_T = TypeVar("_T")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_mapping(value: Any, name: str = "value") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _strict_payload(value: Any, allowed: set[str], required: set[str] = frozenset()) -> dict[str, Any]:
    payload = dict(_require_mapping(value))
    unknown = set(payload) - allowed
    missing = required - set(payload)
    if unknown:
        raise TypeError(f"unexpected field(s): {', '.join(sorted(unknown))}")
    if missing:
        raise TypeError(f"missing field(s): {', '.join(sorted(missing))}")
    return payload


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _non_empty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _utc_timestamp(value: str, name: str = "timestamp") -> None:
    _non_empty(value, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError(f"{name} must be timezone-aware UTC")


class ActorRole(str, Enum):
    PLANNER = "PLANNER"
    RUN_MANAGER = "RUN_MANAGER"
    EVALUATOR = "EVALUATOR"
    ORCHESTRATOR = "ORCHESTRATOR"
    SYSTEM = "SYSTEM"
    USER = "USER"


class SupportedToolName(str, Enum):
    SEARCH_CRYSTAL_DB = "search_crystal_db"
    RUN_CSP = "run_csp"
    VALIDATE_CANDIDATE = "validate_candidate"
    INSPECT_RUN = "inspect_run"


class PlanStepStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


class ToolCallStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ApprovalCategory(str, Enum):
    DROP_HARD_CONSTRAINT = "DROP_HARD_CONSTRAINT"
    CHANGE_COMPOSITION = "CHANGE_COMPOSITION"
    CHANGE_TOPOLOGY_FAMILY = "CHANGE_TOPOLOGY_FAMILY"
    EXPAND_SEARCH_SPACE = "EXPAND_SEARCH_SPACE"
    ACCEPT_NONOPTIMAL = "ACCEPT_NONOPTIMAL"
    BYPASS_VALIDATION = "BYPASS_VALIDATION"
    CHANGE_SCIENTIFIC_RESOURCE = "CHANGE_SCIENTIFIC_RESOURCE"
    INCREASE_BUDGET = "INCREASE_BUDGET"


class AutomaticAction(str, Enum):
    RETRY_MODEL_FORMAT = "RETRY_MODEL_FORMAT"
    READ_EXISTING_RUN = "READ_EXISTING_RUN"
    RETRY_RETRIEVAL = "RETRY_RETRIEVAL"
    EXECUTE_APPROVED_STEP = "EXECUTE_APPROVED_STEP"


class ConstraintKind(str, Enum):
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    SOFT_PREFERENCE = "SOFT_PREFERENCE"
    SUCCESS_CRITERION = "SUCCESS_CRITERION"


class EvaluationStatus(str, Enum):
    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    INCONCLUSIVE = "INCONCLUSIVE"


class RepairType(str, Enum):
    RETRY_RETRIEVAL = "RETRY_RETRIEVAL"
    CHANGE_SCAFFOLD = "CHANGE_SCAFFOLD"
    EXPAND_ALLOWED_DESIGN_SPACE = "EXPAND_ALLOWED_DESIGN_SPACE"
    SWITCH_SUPPORTED_SPP_MODE = "SWITCH_SUPPORTED_SPP_MODE"
    RELAX_OPTIONAL_CONSTRAINT = "RELAX_OPTIONAL_CONSTRAINT"
    REQUEST_USER_INPUT = "REQUEST_USER_INPUT"


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    artifact_id: str
    kind: str
    path: str
    producing_run_id: str
    sha256: str | None = None

    def __post_init__(self) -> None:
        from pathlib import PurePosixPath, PureWindowsPath

        for value, name in ((self.artifact_id, "artifact_id"), (self.kind, "kind"),
                            (self.path, "path"), (self.producing_run_id, "producing_run_id")):
            _non_empty(value, name)
        posix, windows = PurePosixPath(self.path), PureWindowsPath(self.path)
        if posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts or ".." in windows.parts:
            raise ValueError("artifact path must be a traversal-free relative path")
        if self.sha256 is not None and not _SHA256.fullmatch(self.sha256):
            raise ValueError("sha256 must contain 64 lowercase hexadecimal characters")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "ArtifactReference":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"artifact_id", "kind", "path", "producing_run_id"})
        return cls(**p)


@dataclass(frozen=True, slots=True)
class WorkflowRunReference:
    run_id: str
    result_status: str
    result_ref: ArtifactReference
    candidate_ref: ArtifactReference | None = None

    def __post_init__(self) -> None:
        _non_empty(self.run_id, "run_id")
        _non_empty(self.result_status, "result_status")
        if self.result_ref.producing_run_id != self.run_id:
            raise ValueError("result_ref must be produced by the referenced workflow run")
        if self.candidate_ref is not None and self.candidate_ref.producing_run_id != self.run_id:
            raise ValueError("candidate_ref must be produced by the referenced workflow run")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "WorkflowRunReference":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"run_id", "result_status", "result_ref"})
        p["result_ref"] = ArtifactReference.from_dict(p["result_ref"])
        if p.get("candidate_ref") is not None:
            p["candidate_ref"] = ArtifactReference.from_dict(p["candidate_ref"])
        return cls(**p)


@dataclass(frozen=True, slots=True)
class ConstraintRecord:
    kind: ConstraintKind
    description: str
    key: str | None = None
    value: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ConstraintKind(self.kind))
        _non_empty(self.description, "description")
        object.__setattr__(self, "value", _freeze(self.value))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "ConstraintRecord":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"kind", "description"})
        return cls(**p)


@dataclass(frozen=True, slots=True)
class ParsedIntent:
    goal_text: str
    target_formula: str | None = None
    requested_topology_family: str | None = None
    constraints: tuple[ConstraintRecord, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.goal_text, "goal_text")
        object.__setattr__(self, "constraints", tuple(self.constraints))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "ParsedIntent":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"goal_text"})
        p["constraints"] = tuple(ConstraintRecord.from_dict(x) for x in p.get("constraints", ()))
        return cls(**p)


@dataclass(frozen=True, slots=True)
class PlanStep:
    step_id: str
    tool_name: SupportedToolName
    purpose: str
    inputs: JSONMapping
    dependencies: tuple[str, ...] = ()
    approval_category: ApprovalCategory | None = None
    status: PlanStepStatus = PlanStepStatus.PENDING

    def __post_init__(self) -> None:
        _non_empty(self.step_id, "step_id")
        _non_empty(self.purpose, "purpose")
        object.__setattr__(self, "tool_name", SupportedToolName(self.tool_name))
        object.__setattr__(self, "inputs", _freeze(_require_mapping(self.inputs, "inputs")))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "status", PlanStepStatus(self.status))
        if self.approval_category is not None:
            object.__setattr__(self, "approval_category", ApprovalCategory(self.approval_category))
        if self.step_id in self.dependencies:
            raise ValueError("a plan step cannot depend on itself")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "PlanStep":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"step_id", "tool_name", "purpose", "inputs"})
        p["dependencies"] = tuple(p.get("dependencies", ()))
        return cls(**p)


@dataclass(frozen=True, slots=True)
class AgentPlan:
    plan_id: str
    goal: str
    steps: tuple[PlanStep, ...]
    assumptions: tuple[str, ...] = ()
    required_approvals: tuple[ApprovalCategory, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.plan_id, "plan_id")
        _non_empty(self.goal, "goal")
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "required_approvals", tuple(ApprovalCategory(x) for x in self.required_approvals))
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("plan step IDs must be unique")
        known = set(ids)
        for step in self.steps:
            if not set(step.dependencies) <= known:
                raise ValueError("plan step dependency must reference a known step")
        step_approval_categories = {step.approval_category for step in self.steps if step.approval_category is not None}
        if not step_approval_categories <= set(self.required_approvals):
            raise ValueError("every approval-gated step category must appear in required_approvals")
        dependencies = {step.step_id: set(step.dependencies) for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("plan step dependencies must be acyclic")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in ids:
            visit(step_id)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "AgentPlan":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"plan_id", "goal", "steps"})
        p["steps"] = tuple(PlanStep.from_dict(x) for x in p["steps"])
        p["assumptions"] = tuple(p.get("assumptions", ()))
        p["required_approvals"] = tuple(p.get("required_approvals", ()))
        return cls(**p)


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_id: str
    actor: ActorRole
    action: str
    rationale_summary: str
    input_refs: tuple[str, ...]
    created_at: str
    tool_name: SupportedToolName | None = None
    tool_arguments: JSONMapping = field(default_factory=dict)
    result_ref: str | None = None

    def __post_init__(self) -> None:
        for value, name in ((self.decision_id, "decision_id"), (self.action, "action"),
                            (self.rationale_summary, "rationale_summary")):
            _non_empty(value, name)
        if len(self.rationale_summary) > 500:
            raise ValueError("rationale_summary must be concise (500 characters or fewer)")
        object.__setattr__(self, "actor", ActorRole(self.actor))
        object.__setattr__(self, "input_refs", tuple(self.input_refs))
        object.__setattr__(self, "tool_arguments", _freeze(_require_mapping(self.tool_arguments, "tool_arguments")))
        if self.tool_name is not None:
            object.__setattr__(self, "tool_name", SupportedToolName(self.tool_name))
        _utc_timestamp(self.created_at, "created_at")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "DecisionRecord":
        p = _strict_payload(value, set(cls.__dataclass_fields__),
                            {"decision_id", "actor", "action", "rationale_summary", "input_refs", "created_at"})
        p["input_refs"] = tuple(p["input_refs"])
        return cls(**p)


@dataclass(frozen=True, slots=True)
class ToolError:
    code: str
    message: str
    details: JSONMapping = field(default_factory=dict)
    subsystem_status: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        _non_empty(self.code, "code")
        _non_empty(self.message, "message")
        object.__setattr__(self, "details", _freeze(_require_mapping(self.details, "details")))
        if self.subsystem_status is not None:
            _non_empty(self.subsystem_status, "subsystem_status")
        if not isinstance(self.retryable, bool):
            raise TypeError("retryable must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "ToolError":
        return cls(**_strict_payload(value, set(cls.__dataclass_fields__), {"code", "message"}))


@dataclass(frozen=True, slots=True)
class ToolCall:
    tool_call_id: str
    tool_name: SupportedToolName
    arguments: JSONMapping
    requested_by: ActorRole
    status: ToolCallStatus = ToolCallStatus.PROPOSED
    result_ref: str | None = None
    error: ToolError | None = None

    def __post_init__(self) -> None:
        _non_empty(self.tool_call_id, "tool_call_id")
        object.__setattr__(self, "tool_name", SupportedToolName(self.tool_name))
        object.__setattr__(self, "arguments", _freeze(_require_mapping(self.arguments, "arguments")))
        object.__setattr__(self, "requested_by", ActorRole(self.requested_by))
        object.__setattr__(self, "status", ToolCallStatus(self.status))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "ToolCall":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"tool_call_id", "tool_name", "arguments", "requested_by"})
        if p.get("error") is not None:
            p["error"] = ToolError.from_dict(p["error"])
        return cls(**p)


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_call_id: str
    tool_name: SupportedToolName
    status: str
    data: JSONMapping = field(default_factory=dict)
    artifact_refs: tuple[ArtifactReference, ...] = ()
    provenance: JSONMapping = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    error: ToolError | None = None
    schema_version: str = "llm_csp.agentic.tool_result.v1"

    def __post_init__(self) -> None:
        _non_empty(self.tool_call_id, "tool_call_id")
        _non_empty(self.status, "status")
        object.__setattr__(self, "tool_name", SupportedToolName(self.tool_name))
        object.__setattr__(self, "data", _freeze(_require_mapping(self.data, "data")))
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "provenance", _freeze(_require_mapping(self.provenance, "provenance")))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if self.schema_version != "llm_csp.agentic.tool_result.v1":
            raise ValueError("unsupported tool-result schema version")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "ToolResult":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"tool_call_id", "tool_name", "status"})
        p["artifact_refs"] = tuple(ArtifactReference.from_dict(x) for x in p.get("artifact_refs", ()))
        p["warnings"] = tuple(p.get("warnings", ()))
        if p.get("error") is not None:
            p["error"] = ToolError.from_dict(p["error"])
        return cls(**p)


@dataclass(frozen=True, slots=True)
class EvaluationCriterionResult:
    criterion: str
    satisfied: bool | None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.criterion, "criterion")
        if self.satisfied is not None and not isinstance(self.satisfied, bool):
            raise TypeError("satisfied must be true, false, or null")
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "EvaluationCriterionResult":
        return cls(**_strict_payload(value, set(cls.__dataclass_fields__), {"criterion", "satisfied"}))


@dataclass(frozen=True, slots=True)
class RepairRecommendation:
    repair_type: RepairType
    reason: str
    proposed_change: JSONMapping
    approval_required: bool
    source_result_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "repair_type", RepairType(self.repair_type))
        _non_empty(self.reason, "reason")
        _non_empty(self.source_result_ref, "source_result_ref")
        object.__setattr__(self, "proposed_change", _freeze(_require_mapping(self.proposed_change, "proposed_change")))
        if not isinstance(self.approval_required, bool):
            raise TypeError("approval_required must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "RepairRecommendation":
        return cls(**_strict_payload(value, set(cls.__dataclass_fields__), set(cls.__dataclass_fields__)))


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    candidate_ref: ArtifactReference
    workflow_run_ref: str
    criteria_results: tuple[EvaluationCriterionResult, ...]
    overall_status: EvaluationStatus
    repair_recommendation: RepairRecommendation | None = None

    def __post_init__(self) -> None:
        _non_empty(self.workflow_run_ref, "workflow_run_ref")
        object.__setattr__(self, "criteria_results", tuple(self.criteria_results))
        object.__setattr__(self, "overall_status", EvaluationStatus(self.overall_status))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "EvaluationRecord":
        p = _strict_payload(value, set(cls.__dataclass_fields__),
                            {"candidate_ref", "workflow_run_ref", "criteria_results", "overall_status"})
        p["candidate_ref"] = ArtifactReference.from_dict(p["candidate_ref"])
        p["criteria_results"] = tuple(EvaluationCriterionResult.from_dict(x) for x in p["criteria_results"])
        if p.get("repair_recommendation") is not None:
            p["repair_recommendation"] = RepairRecommendation.from_dict(p["repair_recommendation"])
        return cls(**p)


__all__ = [
    "ActorRole", "AgentPlan", "ApprovalCategory", "ApprovalStatus", "ArtifactReference",
    "AutomaticAction", "ConstraintKind", "ConstraintRecord", "DecisionRecord",
    "EvaluationCriterionResult", "EvaluationRecord", "EvaluationStatus", "ParsedIntent",
    "PlanStep", "PlanStepStatus", "RepairRecommendation", "RepairType", "SupportedToolName",
    "ToolCall", "ToolCallStatus", "ToolError", "ToolResult", "WorkflowRunReference",
]
