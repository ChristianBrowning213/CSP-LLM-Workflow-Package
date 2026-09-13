"""Closed adapter registry and deterministic execution entry point."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Mapping

from ..contracts import TOOL_CONTRACTS, WriteScopePolicy, get_tool_contract
from ..models import SupportedToolName, ToolCall, ToolCallStatus
from ..state import AgentRunState
from ..termination import transition_tool_call
from .base import (
    ApprovalRequiredError,
    ToolAdapter,
    ToolDependencies,
    ToolExecution,
    ToolExecutionContext,
    timed_result,
)
from .inspect_run import InspectRunAdapter
from .run_csp import RunCSPAdapter
from .search_crystal_db import SearchCrystalDBAdapter
from .validate_candidate import ValidateCandidateAdapter


_ADAPTERS: dict[SupportedToolName, ToolAdapter] = {
    SupportedToolName.SEARCH_CRYSTAL_DB: SearchCrystalDBAdapter(),
    SupportedToolName.RUN_CSP: RunCSPAdapter(),
    SupportedToolName.VALIDATE_CANDIDATE: ValidateCandidateAdapter(),
    SupportedToolName.INSPECT_RUN: InspectRunAdapter(),
}
ADAPTER_REGISTRY: Mapping[SupportedToolName, ToolAdapter] = MappingProxyType(_ADAPTERS)

if set(ADAPTER_REGISTRY) != set(TOOL_CONTRACTS):
    raise RuntimeError("agent tool adapter registry does not match the contract registry")


def get_tool_adapter(name: SupportedToolName | str) -> ToolAdapter:
    contract = get_tool_contract(name)
    return ADAPTER_REGISTRY[contract.name]


def execute_tool(
    call: ToolCall,
    context: ToolExecutionContext,
    *,
    dependencies: ToolDependencies | None = None,
) -> ToolExecution:
    """Validate and execute one call; this function does not schedule or retry."""

    contract = get_tool_contract(call.tool_name)
    if contract.allowed_write_scope is WriteScopePolicy.AGENT_RUN_ROOT and call.status is not ToolCallStatus.APPROVED:
        raise ApprovalRequiredError(f"{call.tool_name.value} requires an approved tool call")
    if call.status not in {ToolCallStatus.PROPOSED, ToolCallStatus.APPROVED}:
        raise ValueError(f"tool call cannot execute from {call.status.value}")
    request = contract.validate_input(call.arguments)
    adapter = get_tool_adapter(call.tool_name)
    started = context.clock()
    running = transition_tool_call(call, ToolCallStatus.RUNNING)
    execution = adapter.execute(request, context, dependencies or ToolDependencies(), call.tool_call_id)
    finished = context.clock()
    result = timed_result(
        execution.result,
        started=started,
        finished=finished,
        adapter=adapter,
        context=context,
        input_payload=call.arguments,
        input_schema=getattr(request, "schema_version", None),
    )
    terminal_status = ToolCallStatus.FAILED if result.error is not None else ToolCallStatus.SUCCEEDED
    result_ref = (
        execution.workflow_run.run_id
        if execution.workflow_run is not None
        else result.artifact_refs[0].artifact_id if result.artifact_refs else None
    )
    terminal = transition_tool_call(running, terminal_status, result_ref=result_ref)
    terminal = replace(terminal, error=result.error)
    return ToolExecution(
        initial_call=call,
        terminal_call=terminal,
        result=result,
        budget_impact=adapter.budget_impact,
        started_at=result.provenance["execution"]["started_at"],
        finished_at=result.provenance["execution"]["finished_at"],
        duration_seconds=result.provenance["execution"]["duration_seconds"],
        workflow_run=execution.workflow_run,
    )


def apply_execution_to_state(state: AgentRunState, execution: ToolExecution) -> AgentRunState:
    """Apply records only; scientific interpretation remains an Evaluator concern."""

    updated = state
    if execution.workflow_run is not None:
        updated = updated.append_workflow_run(execution.workflow_run)
    updated = updated.replace_tool_call(execution.terminal_call)
    if execution.workflow_run is not None and execution.workflow_run.candidate_ref is not None:
        updated = updated.set_current_candidate(execution.workflow_run.candidate_ref)
    return updated


__all__ = ["ADAPTER_REGISTRY", "apply_execution_to_state", "execute_tool", "get_tool_adapter"]
