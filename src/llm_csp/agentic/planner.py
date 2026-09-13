"""Constraint-preserving initial planner over the closed agent tool registry."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Callable, Mapping

from .budgets import AgentBudgets, BudgetResource
from .contracts import TOOL_CONTRACTS, ApprovalPolicy, validate_tool_input
from .model import AgentModel, AgentModelError, ModelErrorCode, ModelMetadata
from .models import (
    ActorRole,
    AgentPlan,
    ApprovalCategory,
    ConstraintKind,
    ConstraintRecord,
    DecisionRecord,
    ParsedIntent,
    PlanStep,
    PlanStepStatus,
    SupportedToolName,
    _jsonable,
    _non_empty,
    _strict_payload,
)
from .state import AgentRunState, new_identifier, utc_now_iso
from .termination import AgentRunStatus


PLANNER_INSTRUCTIONS = """Create one initial plan using only the declared deterministic tools.
Preserve every hard constraint, soft preference, and success criterion with its original kind.
Never claim scientific success, invent subsystem output, or modify scientific algorithms.
Mark protected deviations as approval-required; never create an approval.
For normal CSP generation, run_csp already performs retrieval and validation, so do not add
standalone search_crystal_db unless retrieval/evidence inspection is itself needed.
Return only an object conforming to the requested output schema."""

_SAFE_REF = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class PlannerStatus(str, Enum):
    PLANNED = "PLANNED"
    INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_ERROR = "MODEL_ERROR"
    USER_INPUT_REQUIRED = "USER_INPUT_REQUIRED"


@dataclass(frozen=True, slots=True)
class ClarificationRequest:
    question: str
    missing_field: str
    why_required: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.question, "question"), (self.missing_field, "missing_field"),
            (self.why_required, "why_required"),
        ):
            _non_empty(value, name)

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Any) -> "ClarificationRequest":
        return cls(**_strict_payload(
            value, set(cls.__dataclass_fields__), {"question", "missing_field", "why_required"}
        ))


@dataclass(frozen=True, slots=True)
class ProposedPlanStep:
    step_ref: str
    tool_name: str
    purpose: str
    inputs: Mapping[str, Any]
    dependencies: tuple[str, ...] = ()
    approval_category: str | None = None

    def __post_init__(self) -> None:
        if not _SAFE_REF.fullmatch(self.step_ref):
            raise ValueError("step_ref must be a safe short identifier")
        _non_empty(self.tool_name, "tool_name")
        _non_empty(self.purpose, "purpose")
        if not isinstance(self.inputs, Mapping):
            raise TypeError("inputs must be an object")
        object.__setattr__(self, "inputs", dict(self.inputs))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        if any(not isinstance(item, str) or not _SAFE_REF.fullmatch(item) for item in self.dependencies):
            raise ValueError("dependencies must contain safe step references")

    @classmethod
    def from_dict(cls, value: Any) -> "ProposedPlanStep":
        p = _strict_payload(
            value, set(cls.__dataclass_fields__), {"step_ref", "tool_name", "purpose", "inputs"}
        )
        p["dependencies"] = tuple(p.get("dependencies", ()))
        return cls(**p)


@dataclass(frozen=True, slots=True)
class PlannerModelOutput:
    """Strict schema expected at the model boundary; still untrusted after parsing."""

    status: str
    goal: str
    steps: tuple[ProposedPlanStep, ...]
    hard_constraints: tuple[ConstraintRecord, ...]
    soft_preferences: tuple[ConstraintRecord, ...]
    success_criteria: tuple[ConstraintRecord, ...]
    clarification: ClarificationRequest | None = None

    def __post_init__(self) -> None:
        if self.status not in {"PLAN", "USER_INPUT_REQUIRED"}:
            raise ValueError("status must be PLAN or USER_INPUT_REQUIRED")
        _non_empty(self.goal, "goal")
        if self.status == "PLAN" and (not self.steps or self.clarification is not None):
            raise ValueError("PLAN requires steps and cannot contain clarification")
        if self.status == "USER_INPUT_REQUIRED" and (self.steps or self.clarification is None):
            raise ValueError("USER_INPUT_REQUIRED requires clarification and no steps")
        expected = (
            (self.hard_constraints, ConstraintKind.HARD_CONSTRAINT),
            (self.soft_preferences, ConstraintKind.SOFT_PREFERENCE),
            (self.success_criteria, ConstraintKind.SUCCESS_CRITERION),
        )
        for records, kind in expected:
            if any(item.kind is not kind for item in records):
                raise ValueError(f"{kind.value} records must remain in their matching category")

    @classmethod
    def from_dict(cls, value: Any) -> "PlannerModelOutput":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {
            "status", "goal", "steps", "hard_constraints", "soft_preferences", "success_criteria",
        })
        p["steps"] = tuple(ProposedPlanStep.from_dict(item) for item in p["steps"])
        for name in ("hard_constraints", "soft_preferences", "success_criteria"):
            p[name] = tuple(ConstraintRecord.from_dict(item) for item in p[name])
        if p.get("clarification") is not None:
            p["clarification"] = ClarificationRequest.from_dict(p["clarification"])
        return cls(**p)


@dataclass(frozen=True, slots=True)
class PlannerInput:
    user_goal: str
    parsed_intent: ParsedIntent
    available_tools: tuple[Mapping[str, Any], ...]
    budget_limits: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        constraints = self.parsed_intent.constraints
        return {
            "user_goal": self.user_goal,
            "parsed_intent": self.parsed_intent.to_dict(),
            "hard_constraints": [x.to_dict() for x in constraints if x.kind is ConstraintKind.HARD_CONSTRAINT],
            "soft_preferences": [x.to_dict() for x in constraints if x.kind is ConstraintKind.SOFT_PREFERENCE],
            "success_criteria": [x.to_dict() for x in constraints if x.kind is ConstraintKind.SUCCESS_CRITERION],
            "available_tools": [_jsonable(x) for x in self.available_tools],
            "budget_limits": dict(self.budget_limits),
        }


@dataclass(frozen=True, slots=True)
class FormatAttempt:
    attempt: int
    metadata: ModelMetadata | None
    error_code: ModelErrorCode | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PlannerProvenance:
    invocation_id: str
    input_hash: str
    output_plan_id: str | None
    timestamp: str
    format_attempts: int
    model_metadata: tuple[ModelMetadata, ...]


@dataclass(frozen=True, slots=True)
class PlannerResult:
    status: PlannerStatus
    plan: AgentPlan | None
    model_metadata: ModelMetadata | None
    warnings: tuple[str, ...]
    error: AgentModelError | None
    format_attempts: tuple[FormatAttempt, ...]
    clarification: ClarificationRequest | None
    budgets: AgentBudgets
    provenance: PlannerProvenance
    preserved_constraints: tuple[ConstraintRecord, ...] = ()


def _schema_fields(model: type) -> dict[str, Any]:
    fields = getattr(model, "__dataclass_fields__", {})
    return {
        name: {
            "type": str(field.type),
            "required": field.default is MISSING and field.default_factory is MISSING,
        }
        for name, field in fields.items()
    }


def planner_tool_summaries() -> tuple[Mapping[str, Any], ...]:
    """Serialize the authoritative registry without exposing Python objects or package code."""
    return tuple({
        "name": contract.name.value,
        "description": contract.description,
        "input_fields": _schema_fields(contract.input_model),
        "side_effects": list(contract.side_effects),
        "approval_policy": contract.approval_policy.value,
        "read_only": contract.read_only,
    } for contract in TOOL_CONTRACTS.values())


def _constraints(intent: ParsedIntent, kind: ConstraintKind) -> tuple[ConstraintRecord, ...]:
    return tuple(item for item in intent.constraints if item.kind is kind)


def _same_records(left: tuple[ConstraintRecord, ...], right: tuple[ConstraintRecord, ...]) -> bool:
    key = lambda item: json.dumps(item.to_dict(), sort_keys=True, separators=(",", ":"))
    return sorted(map(key, left)) == sorted(map(key, right))


def _constraint_in_request(record: ConstraintRecord, request: Mapping[str, Any]) -> bool:
    if record.key is None:
        return True
    if record.key in request and request[record.key] == _jsonable(record.value):
        return True
    for item in request.get("constraints", ()):
        if isinstance(item, Mapping) and (
            item.get(record.key) == _jsonable(record.value)
            or (item.get("key") == record.key and item.get("value") == _jsonable(record.value))
        ):
            return True
    return False


class Planner:
    """Generate and deterministically validate one initial AgentPlan."""

    def __init__(
        self,
        *,
        id_factory: Callable[[str], str] = new_identifier,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._id_factory = id_factory
        self._clock = clock

    def input_for(self, state: AgentRunState) -> PlannerInput:
        return PlannerInput(
            state.user_goal,
            state.parsed_intent,
            planner_tool_summaries(),
            state.budgets.limits.to_dict(),
        )

    def _allocate(self, prefix: str) -> str:
        value = self._id_factory(prefix)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("ID factory returned an unsafe identifier")
        return value

    def plan(self, *, state: AgentRunState, model: AgentModel) -> PlannerResult:
        planner_input = self.input_for(state)
        base_payload = planner_input.to_dict()
        input_hash = hashlib.sha256(
            json.dumps(base_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        invocation_id = self._allocate("planner_invocation")
        timestamp = utc_now_iso(self._clock)
        budgets = state.budgets
        attempts: list[FormatAttempt] = []
        metadata: list[ModelMetadata] = []
        feedback: dict[str, Any] | None = None

        while True:
            payload = dict(base_payload)
            if feedback is not None:
                payload["format_correction"] = feedback
            try:
                response = model.generate_structured(
                    task=PLANNER_INSTRUCTIONS,
                    input_payload=payload,
                    output_schema=PlannerModelOutput,
                )
                metadata.append(response.metadata)
                try:
                    output = response.output if isinstance(response.output, PlannerModelOutput) else PlannerModelOutput.from_dict(response.output)
                    result = self._accept_output(output, state, budgets, invocation_id, input_hash, timestamp, attempts, metadata)
                    return result
                except (TypeError, ValueError, KeyError) as exc:
                    code = ModelErrorCode.MODEL_OUTPUT_SCHEMA_MISMATCH if isinstance(response.output, Mapping) else ModelErrorCode.MODEL_OUTPUT_INVALID
                    attempts.append(FormatAttempt(len(attempts) + 1, response.metadata, code, str(exc)))
                    if not budgets.can_consume(BudgetResource.MODEL_FORMAT_RETRIES):
                        return self._failure(
                            PlannerStatus.INVALID_MODEL_OUTPUT, state, budgets, invocation_id, input_hash,
                            timestamp, attempts, metadata,
                            AgentModelError(ModelErrorCode.MODEL_FORMAT_RETRY_EXHAUSTED, str(exc)),
                        )
                    budgets = budgets.consume(BudgetResource.MODEL_FORMAT_RETRIES)
                    feedback = {"error_code": code.value, "validation_error": str(exc), "required_action": "return schema-valid corrected output"}
            except AgentModelError as exc:
                attempts.append(FormatAttempt(len(attempts) + 1, None, exc.code, str(exc)))
                if exc.retryable_format and exc.code in {
                    ModelErrorCode.MODEL_OUTPUT_INVALID, ModelErrorCode.MODEL_OUTPUT_SCHEMA_MISMATCH,
                }:
                    if budgets.can_consume(BudgetResource.MODEL_FORMAT_RETRIES):
                        budgets = budgets.consume(BudgetResource.MODEL_FORMAT_RETRIES)
                        feedback = {"error_code": exc.code.value, "validation_error": str(exc), "required_action": "return schema-valid corrected output"}
                        continue
                    exc = AgentModelError(ModelErrorCode.MODEL_FORMAT_RETRY_EXHAUSTED, str(exc))
                    status = PlannerStatus.INVALID_MODEL_OUTPUT
                else:
                    status = PlannerStatus.MODEL_UNAVAILABLE if exc.code is ModelErrorCode.MODEL_UNAVAILABLE else PlannerStatus.MODEL_ERROR
                return self._failure(status, state, budgets, invocation_id, input_hash, timestamp, attempts, metadata, exc)
            except Exception as exc:
                error = AgentModelError(ModelErrorCode.MODEL_REQUEST_FAILED, f"{type(exc).__name__}: {exc}")
                attempts.append(FormatAttempt(len(attempts) + 1, None, error.code, str(error)))
                return self._failure(
                    PlannerStatus.MODEL_ERROR, state, budgets, invocation_id, input_hash,
                    timestamp, attempts, metadata, error,
                )

    def _accept_output(
        self, output: PlannerModelOutput, state: AgentRunState, budgets: AgentBudgets,
        invocation_id: str, input_hash: str, timestamp: str,
        attempts: list[FormatAttempt], metadata: list[ModelMetadata],
    ) -> PlannerResult:
        if output.status == "USER_INPUT_REQUIRED":
            attempts.append(FormatAttempt(len(attempts) + 1, metadata[-1]))
            return PlannerResult(
                PlannerStatus.USER_INPUT_REQUIRED, None, metadata[-1], (), None, tuple(attempts),
                output.clarification, budgets,
                PlannerProvenance(invocation_id, input_hash, None, timestamp, len(attempts), tuple(metadata)),
                state.parsed_intent.constraints,
            )
        if any(step.tool_name == SupportedToolName.RUN_CSP.value for step in output.steps) and state.parsed_intent.target_formula is None:
            attempts.append(FormatAttempt(len(attempts) + 1, metadata[-1]))
            clarification = ClarificationRequest(
                "What target composition should be used?",
                "target_formula",
                "The deterministic run_csp request requires a target formula.",
            )
            return PlannerResult(
                PlannerStatus.USER_INPUT_REQUIRED, None, metadata[-1], (), None, tuple(attempts),
                clarification, budgets,
                PlannerProvenance(invocation_id, input_hash, None, timestamp, len(attempts), tuple(metadata)),
                state.parsed_intent.constraints,
            )
        if output.goal != state.user_goal:
            raise ValueError("plan goal must exactly preserve the user goal")
        for records, kind in (
            (output.hard_constraints, ConstraintKind.HARD_CONSTRAINT),
            (output.soft_preferences, ConstraintKind.SOFT_PREFERENCE),
            (output.success_criteria, ConstraintKind.SUCCESS_CRITERION),
        ):
            if not _same_records(records, _constraints(state.parsed_intent, kind)):
                raise ValueError(f"model output did not preserve all {kind.value} records")

        refs = [item.step_ref for item in output.steps]
        if len(refs) != len(set(refs)):
            raise ValueError("plan step references must be unique")
        known = set(refs)
        graph = {step.step_ref: set(step.dependencies) for step in output.steps}
        if any(not dependencies <= known for dependencies in graph.values()):
            raise ValueError("plan step dependency must reference a known step")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("plan step dependencies must be acyclic")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for ref in refs:
            visit(ref)
        positions = {ref: index for index, ref in enumerate(refs)}
        if any(positions[dependency] >= positions[ref] for ref, dependencies in graph.items() for dependency in dependencies):
            raise ValueError("a plan step may depend only on an earlier step")

        ids = {ref: self._allocate("step") for ref in refs}
        steps: list[PlanStep] = []
        for proposed in output.steps:
            tool = SupportedToolName(proposed.tool_name)
            contract = TOOL_CONTRACTS[tool]
            approval = ApprovalCategory(proposed.approval_category) if proposed.approval_category is not None else None
            if approval is not None and contract.approval_policy is ApprovalPolicy.READ_ONLY:
                raise ValueError("read-only tools cannot represent an approval-sensitive change")
            proposed_inputs = dict(proposed.inputs)
            if tool is SupportedToolName.RUN_CSP:
                # Decision linkage is operational provenance and is system-owned.
                proposed_inputs["parent_decision_id"] = invocation_id
            typed_input = validate_tool_input(tool, proposed_inputs)
            normalized = typed_input.to_dict()
            if tool is SupportedToolName.RUN_CSP:
                request = normalized["request"]
                intent = state.parsed_intent
                if intent.target_formula is None:
                    raise ValueError("run_csp requires parsed_intent.target_formula")
                if request["formula"] != intent.target_formula:
                    raise ValueError("run_csp formula must preserve target_formula")
                if intent.requested_topology_family is not None and request.get("topology_family") != intent.requested_topology_family:
                    raise ValueError("run_csp must preserve requested_topology_family")
                missing = [
                    item.description for item in _constraints(intent, ConstraintKind.HARD_CONSTRAINT)
                    if not _constraint_in_request(item, request)
                ]
                if missing:
                    raise ValueError(f"run_csp request dropped hard constraint(s): {', '.join(missing)}")
            steps.append(PlanStep(
                ids[proposed.step_ref], tool, proposed.purpose, normalized,
                tuple(ids[item] for item in proposed.dependencies), approval,
                PlanStepStatus.AWAITING_APPROVAL if approval is not None else PlanStepStatus.PENDING,
            ))
        plan_id = self._allocate("plan")
        required = tuple(dict.fromkeys(step.approval_category for step in steps if step.approval_category is not None))
        plan = AgentPlan(plan_id, output.goal, tuple(steps), required_approvals=required)
        attempts.append(FormatAttempt(len(attempts) + 1, metadata[-1]))
        return PlannerResult(
            PlannerStatus.PLANNED, plan, metadata[-1], (), None, tuple(attempts), None, budgets,
            PlannerProvenance(invocation_id, input_hash, plan_id, timestamp, len(attempts), tuple(metadata)),
            state.parsed_intent.constraints,
        )

    @staticmethod
    def _failure(
        status: PlannerStatus, state: AgentRunState, budgets: AgentBudgets,
        invocation_id: str, input_hash: str, timestamp: str,
        attempts: list[FormatAttempt], metadata: list[ModelMetadata], error: AgentModelError,
    ) -> PlannerResult:
        return PlannerResult(
            status, None, metadata[-1] if metadata else None, (), error, tuple(attempts), None, budgets,
            PlannerProvenance(invocation_id, input_hash, None, timestamp, len(attempts), tuple(metadata)),
            state.parsed_intent.constraints,
        )


def apply_planner_result(
    state: AgentRunState,
    result: PlannerResult,
    *,
    id_factory: Callable[[str], str] = new_identifier,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> AgentRunState:
    """Apply planning state only; never execute or synthesize scientific results."""
    if result.status is PlannerStatus.PLANNED:
        if result.plan is None:
            raise ValueError("PLANNED result must contain a plan")
        intent_hash = hashlib.sha256(
            json.dumps(state.parsed_intent.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        decision = DecisionRecord(
            id_factory("decision"), ActorRole.PLANNER, "INITIAL_PLAN",
            f"Planner produced validated plan {result.plan.plan_id} with {len(result.plan.steps)} steps.",
            (
                f"planner_input_sha256:{result.provenance.input_hash}",
                f"parsed_intent_sha256:{intent_hash}",
                result.provenance.invocation_id,
                result.plan.plan_id,
            ),
            utc_now_iso(clock),
        )
        return replace(state, plan=result.plan, budgets=result.budgets, decisions=(*state.decisions, decision))
    if result.status is PlannerStatus.USER_INPUT_REQUIRED:
        if result.clarification is None:
            raise ValueError("USER_INPUT_REQUIRED result must contain clarification")
        if state.status is AgentRunStatus.PENDING:
            state = state.transition_status(AgentRunStatus.USER_INPUT_REQUIRED)
        elif state.status is AgentRunStatus.RUNNING:
            state = replace(state, status=AgentRunStatus.USER_INPUT_REQUIRED)
        else:
            raise ValueError("clarification can be applied only to an active state")
        return replace(state, budgets=result.budgets, pending_user_action=result.clarification.question)
    raise ValueError("only successful plans or clarification requests can be applied")


__all__ = [
    "ClarificationRequest", "FormatAttempt", "PLANNER_INSTRUCTIONS", "Planner", "PlannerInput",
    "PlannerModelOutput", "PlannerProvenance", "PlannerResult", "PlannerStatus", "ProposedPlanStep",
    "apply_planner_result", "planner_tool_summaries",
]
