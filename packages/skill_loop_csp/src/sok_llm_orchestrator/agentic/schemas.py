from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import json
from typing import Any, ClassVar, Mapping, Self

AGENT_INPUT_SCHEMA_VERSION = "agentic_csp.agent_input.v1"
RUN_PLAN_SCHEMA_VERSION = "agentic_csp.run_plan.v1"
TOOL_CALL_PROPOSAL_SCHEMA_VERSION = "agentic_csp.tool_call_proposal.v1"
RUN_MANAGER_LOG_SCHEMA_VERSION = "agentic_csp.run_manager_log.v1"
RUN_EVALUATION_SCHEMA_VERSION = "agentic_csp.run_evaluation.v1"
ORCHESTRATOR_DECISION_SCHEMA_VERSION = "agentic_csp.orchestrator_decision.v1"
RUN_RECORD_SCHEMA_VERSION = "agentic_csp.run_record.v1"


def _to_plain_json_value(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {key: _to_plain_json_value(value) for key, value in asdict(obj).items()}
    if isinstance(obj, Mapping):
        return {key: _to_plain_json_value(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_to_plain_json_value(value) for value in obj]
    if isinstance(obj, tuple):
        return [_to_plain_json_value(value) for value in obj]
    return obj


def assert_json_serializable(obj: Any) -> None:
    json.dumps(_to_plain_json_value(obj), sort_keys=True)


def to_json_dict(obj: Any) -> dict[str, Any]:
    plain_obj = _to_plain_json_value(obj)
    if not isinstance(plain_obj, dict):
        msg = "Object must convert to a dictionary."
        raise TypeError(msg)
    assert_json_serializable(plain_obj)
    return plain_obj


def _assert_schema_version(actual: str, expected: str) -> None:
    if actual != expected:
        msg = f"schema_version must be {expected!r}, got {actual!r}"
        raise ValueError(msg)


class _SchemaModel:
    expected_schema_version: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        return to_json_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class AgentInputEnvelope(_SchemaModel):
    schema_version: str = AGENT_INPUT_SCHEMA_VERSION
    agent_name: str = ""
    payload: dict[str, Any] | None = None
    context_summary: dict[str, Any] | None = None
    artifact_refs: list[dict[str, Any]] | None = None

    expected_schema_version: ClassVar[str] = AGENT_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _assert_schema_version(self.schema_version, self.expected_schema_version)


@dataclass(frozen=True, slots=True)
class RunPlan(_SchemaModel):
    schema_version: str = RUN_PLAN_SCHEMA_VERSION
    overall_goal: str = ""
    run_goal: str = ""
    stage: str = ""
    detailed_description: str = ""
    hoping_to_find: str = ""
    plan_as_text: str = ""
    what_we_tried_previously_that_is_related: str = ""
    success_criteria: list[str] | None = None
    stop_conditions_for_this_run: list[str] | None = None

    expected_schema_version: ClassVar[str] = RUN_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _assert_schema_version(self.schema_version, self.expected_schema_version)


@dataclass(frozen=True, slots=True)
class ToolCallProposal(_SchemaModel):
    schema_version: str = TOOL_CALL_PROPOSAL_SCHEMA_VERSION
    step: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] | None = None
    expected_result: str = ""
    why: str = ""
    condition: str | None = None

    expected_schema_version: ClassVar[str] = TOOL_CALL_PROPOSAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _assert_schema_version(self.schema_version, self.expected_schema_version)


@dataclass(frozen=True, slots=True)
class RunManagerLog(_SchemaModel):
    schema_version: str = RUN_MANAGER_LOG_SCHEMA_VERSION
    run_id: str = ""
    tool_calls_attempted: list[ToolCallProposal] | None = None
    failures_handled: list[str] | None = None
    manager_notes: str = ""
    artifacts_created: list[dict[str, Any]] | None = None

    expected_schema_version: ClassVar[str] = RUN_MANAGER_LOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _assert_schema_version(self.schema_version, self.expected_schema_version)


@dataclass(frozen=True, slots=True)
class RunEvaluation(_SchemaModel):
    schema_version: str = RUN_EVALUATION_SCHEMA_VERSION
    run_id: str = ""
    run_goal: str = ""
    run_goal_success: bool = False
    overall_goal_progress: str = ""
    summary: str = ""
    what_worked: list[str] | None = None
    what_failed_or_was_weak: list[str] | None = None
    scientific_findings: list[str] | None = None
    best_artifacts: list[dict[str, Any]] | None = None
    scores: dict[str, Any] | None = None
    comparison_to_previous_best: str = ""
    recommended_next_run: str = ""
    should_stop: bool = False
    stop_reason: str | None = None
    needs_user_clarification: bool = False
    clarification_question: str | None = None

    expected_schema_version: ClassVar[str] = RUN_EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _assert_schema_version(self.schema_version, self.expected_schema_version)


@dataclass(frozen=True, slots=True)
class OrchestratorDecision(_SchemaModel):
    schema_version: str = ORCHESTRATOR_DECISION_SCHEMA_VERSION
    decision: str = ""
    reason: str = ""
    next_run_goal: str | None = None
    current_stage: str = ""
    evidence_used: list[str] | None = None
    user_message_if_stopping: str | None = None
    clarification_question_if_needed: str | None = None

    expected_schema_version: ClassVar[str] = ORCHESTRATOR_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _assert_schema_version(self.schema_version, self.expected_schema_version)


@dataclass(frozen=True, slots=True)
class AgenticRunRecord(_SchemaModel):
    schema_version: str = RUN_RECORD_SCHEMA_VERSION
    run_id: str = ""
    overall_goal: str = ""
    run_goal: str = ""
    stage: str = ""
    runtime_schema_version: str = ""
    agent_order: list[str] | None = None
    planner_output: dict[str, Any] | None = None
    run_manager_output: dict[str, Any] | None = None
    evaluator_output: dict[str, Any] | None = None
    orchestrator_output: dict[str, Any] | None = None
    tool_validation_results: list[dict[str, Any]] = field(default_factory=list)
    tool_validation_summary: dict[str, Any] = field(default_factory=dict)
    proposal_readiness: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] | None = None
    warnings: list[str] | None = None

    expected_schema_version: ClassVar[str] = RUN_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _assert_schema_version(self.schema_version, self.expected_schema_version)


__all__ = [
    "AGENT_INPUT_SCHEMA_VERSION",
    "RUN_PLAN_SCHEMA_VERSION",
    "TOOL_CALL_PROPOSAL_SCHEMA_VERSION",
    "RUN_MANAGER_LOG_SCHEMA_VERSION",
    "RUN_EVALUATION_SCHEMA_VERSION",
    "ORCHESTRATOR_DECISION_SCHEMA_VERSION",
    "RUN_RECORD_SCHEMA_VERSION",
    "AgentInputEnvelope",
    "RunPlan",
    "ToolCallProposal",
    "RunManagerLog",
    "RunEvaluation",
    "OrchestratorDecision",
    "AgenticRunRecord",
    "to_json_dict",
    "assert_json_serializable",
]
