from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .agents import (
    Agent,
    EvaluatorAgent,
    OrchestratorAgent,
    PlannerAgent,
    RunManagerAgent,
)
from .schemas import AgentInputEnvelope, assert_json_serializable, to_json_dict
from .schemas import AgenticRunRecord, RUN_RECORD_SCHEMA_VERSION
from .tools import AgenticToolRegistry, default_agentic_tool_registry

RUNTIME_CYCLE_SCHEMA_VERSION = "agentic_csp.runtime_cycle.v1"
PROPOSAL_READINESS_SCHEMA_VERSION = "agentic_csp.proposal_readiness.v1"


def _safe_string(input_payload: Mapping[str, Any], key: str, default: str) -> str:
    value = input_payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


def _normalized_cycle_payload(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(input_payload)
    payload["overall_goal"] = _safe_string(
        input_payload,
        "overall_goal",
        "Advance the current crystal optimization objective.",
    )
    payload["run_goal"] = _safe_string(
        input_payload,
        "run_goal",
        "Prepare a placeholder agentic cycle output.",
    )
    payload["stage"] = _safe_string(input_payload, "stage", "wide_exploration")
    payload["run_id"] = _safe_string(input_payload, "run_id", "run-placeholder")
    return payload


def _plain_artifact_refs(input_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    artifact_refs = input_payload.get("artifact_refs")
    if not isinstance(artifact_refs, list):
        return []
    plain_refs: list[dict[str, Any]] = []
    for item in artifact_refs:
        if isinstance(item, Mapping):
            plain_refs.append(dict(item))
    return plain_refs


def _warnings_from_mapping(mapping: Mapping[str, Any]) -> list[str]:
    warnings = mapping.get("warnings")
    if isinstance(warnings, str) and warnings.strip():
        return [warnings]
    if isinstance(warnings, list):
        return [str(value) for value in warnings]
    if isinstance(warnings, tuple):
        return [str(value) for value in warnings]
    return []


def summarize_tool_validation_results(
    tool_validation_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    valid_tool_names: list[str] = []
    invalid_tool_names: list[str] = []
    warning_count = 0

    for item in tool_validation_results:
        tool_name = item.get("tool_name")
        tool_name_text = str(tool_name) if tool_name is not None else ""
        if item.get("valid") is True:
            valid_tool_names.append(tool_name_text)
        else:
            invalid_tool_names.append(tool_name_text)

        warnings = item.get("warnings")
        if isinstance(warnings, list):
            warning_count += len(warnings)

    summary = {
        "proposal_count": len(tool_validation_results),
        "valid_count": len(valid_tool_names),
        "invalid_count": len(invalid_tool_names),
        "warning_count": warning_count,
        "valid_tool_names": valid_tool_names,
        "invalid_tool_names": invalid_tool_names,
    }
    assert_json_serializable(summary)
    return summary


def classify_proposal_readiness(tool_validation_summary: Mapping[str, Any]) -> dict[str, Any]:
    proposal_count = tool_validation_summary.get("proposal_count", 0)
    valid_count = tool_validation_summary.get("valid_count", 0)
    invalid_count = tool_validation_summary.get("invalid_count", 0)
    warning_count = tool_validation_summary.get("warning_count", 0)

    if proposal_count == 0:
        result = {
            "schema_version": PROPOSAL_READINESS_SCHEMA_VERSION,
            "status": "no_proposals",
            "reason": "No tool proposals were validated.",
            "can_execute_later": False,
        }
    elif invalid_count > 0:
        result = {
            "schema_version": PROPOSAL_READINESS_SCHEMA_VERSION,
            "status": "has_invalid",
            "reason": "One or more validated tool proposals are invalid.",
            "can_execute_later": False,
        }
    elif warning_count > 0 and invalid_count == 0:
        result = {
            "schema_version": PROPOSAL_READINESS_SCHEMA_VERSION,
            "status": "has_warnings",
            "reason": "All validated tool proposals are usable, but warnings remain.",
            "can_execute_later": True,
        }
    elif valid_count == proposal_count and proposal_count > 0:
        result = {
            "schema_version": PROPOSAL_READINESS_SCHEMA_VERSION,
            "status": "all_valid",
            "reason": "All validated tool proposals are ready for a future execution layer.",
            "can_execute_later": True,
        }
    else:
        result = {
            "schema_version": PROPOSAL_READINESS_SCHEMA_VERSION,
            "status": "has_invalid",
            "reason": "Proposal validation state is inconsistent, so execution is blocked.",
            "can_execute_later": False,
        }

    assert_json_serializable(result)
    return result


def _tool_validation_results(
    run_manager_output: Mapping[str, Any],
    tool_registry: AgenticToolRegistry,
) -> list[dict[str, Any]]:
    proposals = run_manager_output.get("tool_calls_attempted")
    if not isinstance(proposals, list):
        return []

    results: list[dict[str, Any]] = []
    for proposal in proposals:
        if isinstance(proposal, Mapping):
            results.append(tool_registry.validate_tool_call_proposal(proposal))
    return results


def _plain_tool_validation_results(runtime_cycle: Mapping[str, Any]) -> list[dict[str, Any]]:
    results = runtime_cycle.get("tool_validation_results")
    if not isinstance(results, list):
        return []

    plain_results: list[dict[str, Any]] = []
    for item in results:
        if isinstance(item, Mapping):
            plain_results.append(to_json_dict(item))
    return plain_results


def _tool_validation_summary_from_runtime_cycle(
    runtime_cycle: Mapping[str, Any],
    tool_validation_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    summary = runtime_cycle.get("tool_validation_summary")
    if isinstance(summary, Mapping):
        plain_summary = to_json_dict(summary)
        assert_json_serializable(plain_summary)
        return plain_summary
    return summarize_tool_validation_results(tool_validation_results)


def _proposal_readiness_from_runtime_cycle(
    runtime_cycle: Mapping[str, Any],
    tool_validation_summary: Mapping[str, Any],
    tool_validation_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    readiness = runtime_cycle.get("proposal_readiness")
    has_explicit_summary = isinstance(runtime_cycle.get("tool_validation_summary"), Mapping)
    if isinstance(readiness, Mapping) and (has_explicit_summary or tool_validation_results):
        plain_readiness = to_json_dict(readiness)
        assert_json_serializable(plain_readiness)
        return plain_readiness
    return classify_proposal_readiness(tool_validation_summary)


def _build_envelope(
    agent_name: str,
    payload: Mapping[str, Any],
    *,
    context_summary: Mapping[str, Any],
    artifact_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    envelope = AgentInputEnvelope(
        agent_name=agent_name,
        payload=dict(payload),
        context_summary=dict(context_summary),
        artifact_refs=list(artifact_refs),
    )
    envelope_dict = to_json_dict(envelope)
    assert_json_serializable(envelope_dict)
    return envelope_dict


def build_run_record(
    input_payload: Mapping[str, Any],
    runtime_cycle: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an archive-ready run record from runtime input and an in-memory cycle result."""

    if not isinstance(input_payload, Mapping):
        msg = "input_payload must be a mapping"
        raise TypeError(msg)
    if not isinstance(runtime_cycle, Mapping):
        msg = "runtime_cycle must be a mapping"
        raise TypeError(msg)

    tool_validation_results = _plain_tool_validation_results(runtime_cycle)
    tool_validation_summary = _tool_validation_summary_from_runtime_cycle(
        runtime_cycle,
        tool_validation_results,
    )

    record = AgenticRunRecord(
        schema_version=RUN_RECORD_SCHEMA_VERSION,
        run_id=_safe_string(input_payload, "run_id", _safe_string(runtime_cycle, "run_id", "run-placeholder")),
        overall_goal=_safe_string(
            input_payload,
            "overall_goal",
            "Advance the current crystal optimization objective.",
        ),
        run_goal=_safe_string(
            input_payload,
            "run_goal",
            "Prepare a placeholder agentic cycle output.",
        ),
        stage=_safe_string(input_payload, "stage", "wide_exploration"),
        runtime_schema_version=_safe_string(
            runtime_cycle,
            "schema_version",
            RUNTIME_CYCLE_SCHEMA_VERSION,
        ),
        agent_order=[
            str(value)
            for value in runtime_cycle.get(
                "agent_order",
                ["planner", "run_manager", "evaluator", "orchestrator"],
            )
        ],
        planner_output=to_json_dict(runtime_cycle["planner_output"]),
        run_manager_output=to_json_dict(runtime_cycle["run_manager_output"]),
        evaluator_output=to_json_dict(runtime_cycle["evaluator_output"]),
        orchestrator_output=to_json_dict(runtime_cycle["orchestrator_output"]),
        tool_validation_results=tool_validation_results,
        tool_validation_summary=tool_validation_summary,
        proposal_readiness=_proposal_readiness_from_runtime_cycle(
            runtime_cycle,
            tool_validation_summary,
            tool_validation_results,
        ),
        artifact_refs=_plain_artifact_refs(input_payload),
        warnings=_warnings_from_mapping(input_payload) + _warnings_from_mapping(runtime_cycle),
    )
    record_dict = to_json_dict(record)
    assert_json_serializable(record_dict)
    return record_dict


@dataclass(frozen=True, slots=True)
class AgenticRuntime:
    """Tiny in-memory placeholder runtime loop for the schema-backed agent stubs."""

    planner: Agent = field(default_factory=PlannerAgent)
    run_manager: Agent = field(default_factory=RunManagerAgent)
    evaluator: Agent = field(default_factory=EvaluatorAgent)
    orchestrator: Agent = field(default_factory=OrchestratorAgent)
    tool_registry: AgenticToolRegistry = field(default_factory=default_agentic_tool_registry)

    def run_cycle(self, input_payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(input_payload, Mapping):
            msg = "input_payload must be a mapping"
            raise TypeError(msg)

        cycle_payload = _normalized_cycle_payload(input_payload)
        agent_order = ["planner", "run_manager", "evaluator", "orchestrator"]

        planner_envelope = _build_envelope(
            "planner",
            cycle_payload,
            context_summary={
                "current_stage": cycle_payload["stage"],
                "prior_agent": None,
                "known_outputs": [],
            },
            artifact_refs=[],
        )
        planner_output = self.planner.run(planner_envelope)

        run_manager_envelope = _build_envelope(
            "run_manager",
            {
                **cycle_payload,
                "planner_output": planner_output,
            },
            context_summary={
                "current_stage": cycle_payload["stage"],
                "prior_agent": "planner",
                "known_outputs": ["planner_output"],
            },
            artifact_refs=[],
        )
        run_manager_output = self.run_manager.run(run_manager_envelope)
        tool_validation_results = _tool_validation_results(
            run_manager_output,
            self.tool_registry,
        )
        tool_validation_summary = summarize_tool_validation_results(tool_validation_results)
        proposal_readiness = classify_proposal_readiness(tool_validation_summary)

        evaluator_envelope = _build_envelope(
            "evaluator",
            {
                **cycle_payload,
                "planner_output": planner_output,
                "run_manager_output": run_manager_output,
                "tool_validation_results": tool_validation_results,
                "tool_validation_summary": tool_validation_summary,
                "proposal_readiness": proposal_readiness,
            },
            context_summary={
                "current_stage": cycle_payload["stage"],
                "prior_agent": "run_manager",
                "known_outputs": [
                    "planner_output",
                    "run_manager_output",
                    "tool_validation_results",
                    "tool_validation_summary",
                    "proposal_readiness",
                ],
            },
            artifact_refs=[],
        )
        evaluator_output = self.evaluator.run(evaluator_envelope)

        orchestrator_envelope = _build_envelope(
            "orchestrator",
            {
                **cycle_payload,
                "planner_output": planner_output,
                "run_manager_output": run_manager_output,
                "evaluator_output": evaluator_output,
                "tool_validation_results": tool_validation_results,
                "tool_validation_summary": tool_validation_summary,
                "proposal_readiness": proposal_readiness,
            },
            context_summary={
                "current_stage": cycle_payload["stage"],
                "prior_agent": "evaluator",
                "known_outputs": [
                    "planner_output",
                    "run_manager_output",
                    "tool_validation_results",
                    "tool_validation_summary",
                    "proposal_readiness",
                    "evaluator_output",
                ],
            },
            artifact_refs=[],
        )
        orchestrator_output = self.orchestrator.run(orchestrator_envelope)

        cycle_result = {
            "schema_version": RUNTIME_CYCLE_SCHEMA_VERSION,
            "run_id": cycle_payload["run_id"],
            "planner_output": planner_output,
            "run_manager_output": run_manager_output,
            "evaluator_output": evaluator_output,
            "orchestrator_output": orchestrator_output,
            "tool_validation_results": tool_validation_results,
            "tool_validation_summary": tool_validation_summary,
            "proposal_readiness": proposal_readiness,
            "agent_order": agent_order,
        }
        assert_json_serializable(cycle_result)
        return cycle_result


def run_placeholder_agentic_cycle(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Run the placeholder in-memory agent loop without tools, LLMs, or file I/O."""

    return AgenticRuntime().run_cycle(input_payload)


def run_placeholder_agentic_cycle_record(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Run the placeholder cycle and package the result as an archive-ready run record."""

    runtime_cycle = run_placeholder_agentic_cycle(input_payload)
    return build_run_record(input_payload, runtime_cycle)


__all__ = [
    "RUNTIME_CYCLE_SCHEMA_VERSION",
    "RUN_RECORD_SCHEMA_VERSION",
    "PROPOSAL_READINESS_SCHEMA_VERSION",
    "AgenticRuntime",
    "build_run_record",
    "classify_proposal_readiness",
    "summarize_tool_validation_results",
    "run_placeholder_agentic_cycle",
    "run_placeholder_agentic_cycle_record",
]
