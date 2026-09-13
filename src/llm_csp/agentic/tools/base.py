"""Shared deterministic adapter execution types."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from llm_csp.schemas import RetrievalConfig, WorkflowConfig

from ..models import (
    ArtifactReference,
    SupportedToolName,
    ToolCall,
    ToolResult,
    WorkflowRunReference,
    _jsonable,
    _non_empty,
)
from ..state import WriteScope, new_identifier, utc_now_iso


class ApprovalRequiredError(PermissionError):
    """Raised when a write-capable adapter receives an unapproved call."""


@dataclass(frozen=True, slots=True)
class ToolDependencies:
    """Optional deterministic callable injection for tests."""

    retrieval: Callable[..., Mapping[str, Any]] | None = None
    workflow: Callable[..., Any] | None = None
    validate_general: Callable[..., Any] | None = None
    validate_topology: Callable[..., Any] | None = None
    structure_loader: Callable[[str], Any] | None = None


def _default_id_factory(prefix: str) -> str:
    return new_identifier(prefix)


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Caller-owned resources available to deterministic adapters."""

    agent_run_id: str
    run_root: str
    retrieval_configs: Mapping[str, RetrievalConfig] = field(default_factory=dict)
    workflow_configs: Mapping[str, WorkflowConfig] = field(default_factory=dict)
    workflow_runs: Mapping[str, WorkflowRunReference] = field(default_factory=dict)
    artifact_index: Mapping[str, ArtifactReference] = field(default_factory=dict)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc), repr=False, compare=False)
    id_factory: Callable[[str], str] = field(default=_default_id_factory, repr=False, compare=False)
    write_scope: WriteScope = field(init=False)

    def __post_init__(self) -> None:
        _non_empty(self.agent_run_id, "agent_run_id")
        scope = WriteScope(self.run_root)
        object.__setattr__(self, "run_root", scope.run_root)
        object.__setattr__(self, "write_scope", scope)
        for values, expected, label in (
            (self.retrieval_configs, RetrievalConfig, "retrieval config"),
            (self.workflow_configs, WorkflowConfig, "workflow config"),
            (self.workflow_runs, WorkflowRunReference, "workflow run"),
            (self.artifact_index, ArtifactReference, "artifact"),
        ):
            if not isinstance(values, Mapping):
                raise TypeError(f"{label} registry must be a mapping")
            for key, value in values.items():
                _non_empty(key, f"{label} reference")
                if not isinstance(value, expected):
                    raise TypeError(f"{label} registry values must be {expected.__name__}")
        if any(key != value.run_id for key, value in self.workflow_runs.items()):
            raise ValueError("workflow-run registry keys must match run IDs")
        if any(key != value.artifact_id for key, value in self.artifact_index.items()):
            raise ValueError("artifact registry keys must match artifact IDs")
        for run in self.workflow_runs.values():
            for artifact in (run.result_ref, run.candidate_ref):
                if artifact is not None and self.artifact_index.get(artifact.artifact_id) != artifact:
                    raise ValueError("known workflow-run artifacts must be present in the artifact registry")
        object.__setattr__(self, "retrieval_configs", MappingProxyType(dict(self.retrieval_configs)))
        object.__setattr__(self, "workflow_configs", MappingProxyType(dict(self.workflow_configs)))
        object.__setattr__(self, "workflow_runs", MappingProxyType(dict(self.workflow_runs)))
        object.__setattr__(self, "artifact_index", MappingProxyType(dict(self.artifact_index)))

    def retrieval_config(self, reference: str | None) -> RetrievalConfig:
        if reference is not None:
            try:
                return self.retrieval_configs[reference]
            except KeyError as exc:
                raise ValueError(f"unknown retrieval configuration: {reference}") from exc
        if len(self.retrieval_configs) != 1:
            raise ValueError("retrieval_ref is required unless exactly one retrieval configuration is registered")
        return next(iter(self.retrieval_configs.values()))

    def workflow_config(self, reference: str) -> WorkflowConfig:
        try:
            return self.workflow_configs[reference]
        except KeyError as exc:
            raise ValueError(f"unknown workflow configuration: {reference}") from exc

    def artifact(self, reference: ArtifactReference) -> ArtifactReference:
        known = self.artifact_index.get(reference.artifact_id)
        if known is None or known != reference:
            raise ValueError(f"unknown or mismatched artifact reference: {reference.artifact_id}")
        return known

    def allocate_id(self, prefix: str) -> str:
        identifier = self.id_factory(prefix)
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_\-]+", identifier):
            raise ValueError("injected ID factory returned an unsafe identifier")
        return identifier


@dataclass(frozen=True, slots=True)
class BudgetImpact:
    retrieval_calls: int = 0
    workflow_runs: int = 0


@dataclass(frozen=True, slots=True)
class AdapterExecution:
    result: ToolResult
    workflow_run: WorkflowRunReference | None = None


@dataclass(frozen=True, slots=True)
class ToolExecution:
    initial_call: ToolCall
    terminal_call: ToolCall
    result: ToolResult
    budget_impact: BudgetImpact
    started_at: str
    finished_at: str
    duration_seconds: float
    workflow_run: WorkflowRunReference | None = None


class ToolAdapter(Protocol):
    name: SupportedToolName
    budget_impact: BudgetImpact

    def execute(
        self,
        request: Any,
        context: ToolExecutionContext,
        dependencies: ToolDependencies,
        tool_call_id: str,
    ) -> AdapterExecution: ...


def timed_result(
    result: ToolResult,
    *,
    started: datetime,
    finished: datetime,
    adapter: ToolAdapter,
    context: ToolExecutionContext,
    input_payload: Mapping[str, Any],
    input_schema: str | None,
) -> ToolResult:
    if finished < started:
        raise ValueError("execution clock moved backwards")
    timing = {
        "started_at": utc_now_iso(lambda: started),
        "finished_at": utc_now_iso(lambda: finished),
        "duration_seconds": (finished - started).total_seconds(),
    }
    provenance = dict(result.provenance)
    provenance.update({
        "agent_run_id": context.agent_run_id,
        "adapter": adapter.name.value,
        "input_schema": input_schema,
        "output_schema": result.schema_version,
        "input_payload": _jsonable(input_payload),
        "result_status": result.status,
        "execution": timing,
    })
    return replace(result, provenance=provenance)


__all__ = [
    "AdapterExecution", "ApprovalRequiredError", "BudgetImpact", "ToolAdapter", "ToolDependencies",
    "ToolExecution", "ToolExecutionContext", "timed_result",
]
