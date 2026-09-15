from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .schemas import (
    AGENT_INPUT_SCHEMA_VERSION,
    ORCHESTRATOR_DECISION_SCHEMA_VERSION,
    RUN_EVALUATION_SCHEMA_VERSION,
    RUN_MANAGER_LOG_SCHEMA_VERSION,
    RUN_PLAN_SCHEMA_VERSION,
    OrchestratorDecision,
    RunEvaluation,
    RunManagerLog,
    RunPlan,
    ToolCallProposal,
    to_json_dict,
)

SCHEMA_VERSION = "agentic.a1.v1"


@runtime_checkable
class Agent(Protocol):
    """Minimal JSON-in/JSON-out contract for the replaceable agent runtime layer."""

    name: str
    role: str

    def run(self, input_payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a plain dictionary response from a dict-like input payload."""


def _safe_string(
    input_payload: Mapping[str, Any],
    key: str,
    default: str,
) -> str:
    value = input_payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


def _safe_input_keys(input_payload: Mapping[str, Any]) -> list[str]:
    return sorted(str(key) for key in input_payload.keys())


def _unique_named_items(items: object) -> list[str]:
    if not isinstance(items, (list, tuple)):
        return []

    names: list[str] = []
    for item in items:
        item_text = str(item).strip()
        if item_text and item_text not in names:
            names.append(item_text)
    return names


def _warning_tool_names(tool_validation_results: object) -> list[str]:
    if not isinstance(tool_validation_results, list):
        return []

    warning_tool_names: list[str] = []
    for item in tool_validation_results:
        if not isinstance(item, Mapping):
            continue
        warnings = item.get("warnings")
        tool_name = str(item.get("tool_name", "")).strip()
        has_warnings = isinstance(warnings, (list, tuple)) and len(warnings) > 0
        if has_warnings and tool_name and tool_name not in warning_tool_names:
            warning_tool_names.append(tool_name)
    return warning_tool_names


def _concise_hint_text(text: object, *, limit: int = 200) -> str | None:
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3].rstrip()}..."


def _single_tool_validation_hint(
    tool_validation_results: object,
    *,
    valid: bool,
    include_warnings: bool,
) -> tuple[str, str] | None:
    if not isinstance(tool_validation_results, list):
        return None

    matching_rows: list[tuple[str, str]] = []
    for item in tool_validation_results:
        if not isinstance(item, Mapping):
            continue

        tool_name = str(item.get("tool_name", "")).strip()
        if not tool_name:
            continue

        is_valid = item.get("valid") is True
        messages = item.get("warnings") if include_warnings else item.get("errors")
        if is_valid != valid or not isinstance(messages, list) or not messages:
            continue

        concise_message = _concise_hint_text(messages[0])
        if concise_message is not None:
            matching_rows.append((tool_name, concise_message))

    if len(matching_rows) == 1:
        return matching_rows[0]
    return None


class _BasePlaceholderAgent:
    default_stage = ""

    def _validated_payload(self, input_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(input_payload, Mapping):
            msg = "input_payload must be a mapping"
            raise TypeError(msg)
        if input_payload.get("schema_version") == AGENT_INPUT_SCHEMA_VERSION:
            payload = input_payload.get("payload")
            if not isinstance(payload, Mapping):
                msg = "AgentInputEnvelope payload must be a mapping"
                raise TypeError(msg)
            return payload
        return input_payload

    def _overall_goal(self, input_payload: Mapping[str, Any]) -> str:
        return _safe_string(
            input_payload,
            "overall_goal",
            "Advance the current crystal optimization objective.",
        )

    def _run_goal(self, input_payload: Mapping[str, Any]) -> str:
        return _safe_string(
            input_payload,
            "run_goal",
            f"Prepare a placeholder output for the {self.name} agent.",
        )

    def _stage(self, input_payload: Mapping[str, Any]) -> str:
        return _safe_string(input_payload, "stage", self.default_stage)

    def _run_id(self, input_payload: Mapping[str, Any]) -> str:
        return _safe_string(input_payload, "run_id", "run-placeholder")


@dataclass(frozen=True, slots=True)
class PlannerAgent(_BasePlaceholderAgent):
    """Planner agent that writes run strategy only and does not execute tools."""

    name: str = "planner"
    role: str = "Writes run strategy only."
    default_stage: str = "planning"

    def run(self, input_payload: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._validated_payload(input_payload)
        stage = self._stage(payload)
        run_goal = self._run_goal(payload)
        plan = RunPlan(
            schema_version=RUN_PLAN_SCHEMA_VERSION,
            overall_goal=self._overall_goal(payload),
            run_goal=run_goal,
            stage=stage,
            detailed_description=(
                f"Placeholder planning output for stage '{stage}' with no tool execution."
            ),
            hoping_to_find="A clear next-run strategy that remains archive-ready.",
            plan_as_text=(
                "Review the provided context and prepare a deterministic next-run strategy.\n"
                "tool_hint: crystal.csp_pack\n"
                "intent: retrieve or discover candidate crystal structures aligned with the run goal.\n"
                "expected_result: ranked candidate set with exportability metadata recorded for later archive-ready use."
            ),
            what_we_tried_previously_that_is_related=(
                f"Known input keys: {', '.join(_safe_input_keys(payload)) or 'none'}."
            ),
            success_criteria=[
                "Run goal is stated clearly.",
                "The plan can be serialized to plain JSON.",
            ],
            stop_conditions_for_this_run=[
                "Required planning context is missing.",
                "The run goal is already satisfied.",
            ],
        )
        return to_json_dict(plan)


@dataclass(frozen=True, slots=True)
class RunManagerAgent(_BasePlaceholderAgent):
    """Run Manager that will later turn plans into tool proposals without executing tools in A1."""

    name: str = "run_manager"
    role: str = "Prepares future tool proposals without direct execution."
    default_stage: str = "run_management"

    def run(self, input_payload: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._validated_payload(input_payload)
        run_goal = self._run_goal(payload)
        overall_goal = self._overall_goal(payload)
        run_id = self._run_id(payload)
        proposal = ToolCallProposal(
            step="Prepare a placeholder CSP pack proposal for later runtime execution.",
            tool_name="crystal.csp_pack",
            arguments={
                "case_id": run_id,
                "objective_family": overall_goal,
                "notes": run_goal,
            },
            expected_result="A candidate CSP pack description is recorded without execution.",
            why="Run Manager stores valid structured proposals before any runtime layer exists.",
            condition="Only execute after a future runtime layer is implemented.",
        )
        log = RunManagerLog(
            schema_version=RUN_MANAGER_LOG_SCHEMA_VERSION,
            run_id=run_id,
            tool_calls_attempted=[proposal],
            failures_handled=["No tool execution is performed in this placeholder layer."],
            manager_notes=(
                "Placeholder run manager output records a proposal without invoking tools."
            ),
            artifacts_created=[],
        )
        return to_json_dict(log)


@dataclass(frozen=True, slots=True)
class EvaluatorAgent(_BasePlaceholderAgent):
    """Evaluator agent that creates durable run memory for later archive-ready persistence."""

    name: str = "evaluator"
    role: str = "Creates durable run memory."
    default_stage: str = "evaluation"

    def run(self, input_payload: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._validated_payload(input_payload)
        run_goal = self._run_goal(payload)
        evaluation = RunEvaluation(
            schema_version=RUN_EVALUATION_SCHEMA_VERSION,
            run_id=self._run_id(payload),
            run_goal=run_goal,
            run_goal_success=False,
            overall_goal_progress="Schema-backed placeholder evaluation prepared.",
            summary="No runtime execution occurred; this is a deterministic evaluation scaffold.",
            what_worked=["Schema-backed output is archive-ready and JSON-serializable."],
            what_failed_or_was_weak=["No experimental execution or scoring has occurred yet."],
            scientific_findings=["No scientific findings are available in the placeholder layer."],
            best_artifacts=[],
            scores={"placeholder_confidence": 0.0},
            comparison_to_previous_best="No previous evaluated run is compared in this stub.",
            recommended_next_run=run_goal,
            should_stop=False,
            stop_reason=None,
            needs_user_clarification=False,
            clarification_question=None,
        )
        return to_json_dict(evaluation)


@dataclass(frozen=True, slots=True)
class OrchestratorAgent(_BasePlaceholderAgent):
    """Orchestrator agent that controls cross-run continue, stop, or ask-user decisions."""

    name: str = "orchestrator"
    role: str = "Controls cross-run decisions."
    default_stage: str = "orchestration"

    def run(self, input_payload: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._validated_payload(input_payload)
        proposal_readiness = payload.get("proposal_readiness")
        tool_validation_summary = payload.get("tool_validation_summary")
        tool_validation_results = payload.get("tool_validation_results")
        invalid_tool_names = []
        warning_tool_names = _warning_tool_names(tool_validation_results)
        invalid_hint = _single_tool_validation_hint(
            tool_validation_results,
            valid=False,
            include_warnings=False,
        )
        warning_hint = _single_tool_validation_hint(
            tool_validation_results,
            valid=True,
            include_warnings=True,
        )
        if isinstance(tool_validation_summary, Mapping):
            invalid_tool_names = _unique_named_items(
                tool_validation_summary.get("invalid_tool_names"),
            )
        next_run_goal = self._run_goal(payload)
        reason = "A schema-backed placeholder decision is available for the next run."
        decision_name = "continue"
        user_message_if_stopping = None
        clarification_question_if_needed = None
        evidence_used = [
            f"known_input_keys={','.join(_safe_input_keys(payload)) or 'none'}",
            "placeholder_schema_outputs_only",
        ]

        if isinstance(proposal_readiness, Mapping):
            readiness_status = _safe_string(
                proposal_readiness,
                "status",
                "unknown",
            )
            evidence_used.append(f"proposal_readiness_status={readiness_status}")

            if readiness_status == "all_valid":
                reason = (
                    "Proposal readiness indicates future execution is allowed by current "
                    "tool validation."
                )
                next_run_goal = self._run_goal(
                    payload,
                ) or "proceed with validated tool proposals"
            elif readiness_status == "has_warnings":
                reason = (
                    "Proposal readiness indicates future execution is allowed with "
                    "warnings, and review is recommended before execution."
                )
                if warning_hint is not None:
                    reason = f"{reason} First warning for {warning_hint[0]}: {warning_hint[1]}"
                if len(warning_tool_names) == 1:
                    next_run_goal = (
                        f"review warnings on {warning_tool_names[0]} proposal before execution"
                    )
                else:
                    next_run_goal = "review warning-bearing tool proposals before execution"
            elif readiness_status == "has_invalid":
                decision_name = "ask_user"
                reason = (
                    "Proposal readiness indicates invalid tool proposals block future "
                    "execution."
                )
                if invalid_hint is not None:
                    reason = f"{reason} First error for {invalid_hint[0]}: {invalid_hint[1]}"
                if len(invalid_tool_names) == 1:
                    next_run_goal = (
                        f"repair invalid {invalid_tool_names[0]} proposal before execution"
                    )
                else:
                    next_run_goal = "repair invalid tool proposals before execution"
                user_message_if_stopping = (
                    "Tool proposal validation found invalid entries, so execution should "
                    "not proceed yet."
                )
                clarification_question_if_needed = (
                    "Should we revise the proposed tool calls before continuing?"
                )
            elif readiness_status == "no_proposals":
                decision_name = "ask_user"
                reason = (
                    "Proposal readiness indicates no executable proposals are currently "
                    "available."
                )
                next_run_goal = "generate executable tool proposals before execution"
                user_message_if_stopping = (
                    "No validated tool proposals are available for a future execution step."
                )
                clarification_question_if_needed = (
                    "Should we request a new proposal strategy before continuing?"
                )
            else:
                decision_name = "ask_user"
                reason = (
                    "Proposal readiness is unknown, so future execution should remain "
                    "blocked pending review."
                )
                next_run_goal = "inspect proposal readiness before execution"
                user_message_if_stopping = (
                    "Proposal readiness could not be interpreted safely."
                )
                clarification_question_if_needed = (
                    "Should we inspect the proposal readiness state before continuing?"
                )

        if isinstance(tool_validation_summary, Mapping):
            proposal_count = int(tool_validation_summary.get("proposal_count", 0))
            valid_count = int(tool_validation_summary.get("valid_count", 0))
            invalid_count = int(tool_validation_summary.get("invalid_count", 0))
            warning_count = int(tool_validation_summary.get("warning_count", 0))
            evidence_used.append("tool_validation_summary")
            evidence_used.append(
                "tool_validation_counts="
                f"proposals={proposal_count},valid={valid_count},"
                f"invalid={invalid_count},warnings={warning_count}"
            )
            reason = (
                f"{reason} proposal counts: proposals={proposal_count} "
                f"valid={valid_count} invalid={invalid_count} warnings={warning_count}."
            )

        decision = OrchestratorDecision(
            schema_version=ORCHESTRATOR_DECISION_SCHEMA_VERSION,
            decision=decision_name,
            reason=reason,
            next_run_goal=next_run_goal,
            current_stage=self._stage(payload),
            evidence_used=evidence_used,
            user_message_if_stopping=user_message_if_stopping,
            clarification_question_if_needed=clarification_question_if_needed,
        )
        return to_json_dict(decision)


__all__ = [
    "SCHEMA_VERSION",
    "Agent",
    "PlannerAgent",
    "RunManagerAgent",
    "EvaluatorAgent",
    "OrchestratorAgent",
]
