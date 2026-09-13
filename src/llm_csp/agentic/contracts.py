"""Validated metadata contracts for the initial closed agent tool surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from llm_csp.schemas import CSPWorkflowRequest

from .models import (
    ArtifactReference,
    JSONMapping,
    SupportedToolName,
    ToolResult,
    _freeze,
    _jsonable,
    _non_empty,
    _require_mapping,
    _strict_payload,
)


class UnknownToolError(ValueError):
    pass


class ApprovalPolicy(str, Enum):
    PLAN_APPROVAL = "PLAN_APPROVAL"
    EXISTING_APPROVAL = "EXISTING_APPROVAL"
    READ_ONLY = "READ_ONLY"


class WriteScopePolicy(str, Enum):
    AGENT_RUN_ROOT = "AGENT_RUN_ROOT"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class SearchCrystalDBInput:
    query: str
    k: int = 10
    formula: str | None = None
    retrieval_ref: str | None = None
    schema_version: str = "llm_csp.agentic.search_crystal_db.input.v1"

    def __post_init__(self) -> None:
        _non_empty(self.query, "query")
        if type(self.k) is not int or not 1 <= self.k <= 50:
            raise ValueError("k must be an integer from 1 through 50")
        if self.formula is not None:
            _non_empty(self.formula, "formula")
        if self.retrieval_ref is not None:
            _non_empty(self.retrieval_ref, "retrieval_ref")
        if self.schema_version != "llm_csp.agentic.search_crystal_db.input.v1":
            raise ValueError("unsupported search_crystal_db input schema version")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "SearchCrystalDBInput":
        return cls(**_strict_payload(value, set(cls.__dataclass_fields__), {"query"}))


@dataclass(frozen=True, slots=True)
class RunCSPInput:
    request: CSPWorkflowRequest
    config_ref: str
    parent_decision_id: str
    schema_version: str = "llm_csp.agentic.run_csp.input.v1"

    def __post_init__(self) -> None:
        if not isinstance(self.request, CSPWorkflowRequest):
            raise TypeError("request must be a CSPWorkflowRequest")
        _non_empty(self.config_ref, "config_ref")
        _non_empty(self.parent_decision_id, "parent_decision_id")
        if self.schema_version != "llm_csp.agentic.run_csp.input.v1":
            raise ValueError("unsupported run_csp input schema version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(), "config_ref": self.config_ref,
            "parent_decision_id": self.parent_decision_id, "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "RunCSPInput":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"request", "config_ref", "parent_decision_id"})
        p["request"] = CSPWorkflowRequest.from_dict(_jsonable(_require_mapping(p["request"], "request")))
        return cls(**p)


@dataclass(frozen=True, slots=True)
class ValidateCandidateInput:
    candidate_ref: ArtifactReference
    target_formula: str | None = None
    topology_family: str | None = None
    validation_options: JSONMapping = field(default_factory=dict)
    schema_version: str = "llm_csp.agentic.validate_candidate.input.v1"

    def __post_init__(self) -> None:
        if self.candidate_ref.kind.lower() not in {"candidate", "cif", "candidate_cif"}:
            raise ValueError("candidate_ref must identify a candidate or CIF artifact")
        object.__setattr__(self, "validation_options", _freeze(_require_mapping(self.validation_options, "validation_options")))
        for value, name in ((self.target_formula, "target_formula"), (self.topology_family, "topology_family")):
            if value is not None:
                _non_empty(value, name)
        if self.schema_version != "llm_csp.agentic.validate_candidate.input.v1":
            raise ValueError("unsupported validate_candidate input schema version")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "ValidateCandidateInput":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"candidate_ref"})
        p["candidate_ref"] = ArtifactReference.from_dict(p["candidate_ref"])
        return cls(**p)


_INSPECT_SECTIONS = frozenset({
    "summary", "retrieval", "spp", "solver", "candidate", "validation",
    "stages", "artifacts", "provenance", "warnings", "errors",
})


@dataclass(frozen=True, slots=True)
class InspectRunInput:
    workflow_run_id: str
    include: tuple[str, ...] = tuple(sorted(_INSPECT_SECTIONS))
    schema_version: str = "llm_csp.agentic.inspect_run.input.v1"

    def __post_init__(self) -> None:
        _non_empty(self.workflow_run_id, "workflow_run_id")
        object.__setattr__(self, "include", tuple(self.include))
        unknown = set(self.include) - _INSPECT_SECTIONS
        if unknown:
            raise ValueError(f"unsupported inspection section(s): {', '.join(sorted(unknown))}")
        if self.schema_version != "llm_csp.agentic.inspect_run.input.v1":
            raise ValueError("unsupported inspect_run input schema version")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "InspectRunInput":
        p = _strict_payload(value, set(cls.__dataclass_fields__), {"workflow_run_id"})
        p["include"] = tuple(p.get("include", tuple(sorted(_INSPECT_SECTIONS))))
        return cls(**p)


@dataclass(frozen=True, slots=True)
class ToolContract:
    name: SupportedToolName
    description: str
    input_model: type
    output_model: type[ToolResult]
    side_effects: tuple[str, ...]
    approval_policy: ApprovalPolicy
    allowed_write_scope: WriteScopePolicy
    failure_states: tuple[str, ...]
    read_only: bool = False

    def validate_input(self, payload: Mapping[str, Any]) -> Any:
        return self.input_model.from_dict(payload)

    def validate_output(self, payload: Mapping[str, Any]) -> ToolResult:
        result = self.output_model.from_dict(payload)
        if result.tool_name is not self.name:
            raise ValueError("tool result name does not match its contract")
        return result


_CONTRACTS = {
    SupportedToolName.SEARCH_CRYSTAL_DB: ToolContract(
        SupportedToolName.SEARCH_CRYSTAL_DB, "Retrieve attributable crystallographic evidence.",
        SearchCrystalDBInput, ToolResult, (), ApprovalPolicy.READ_ONLY,
        WriteScopePolicy.NONE, ("missing_db", "embedding_incompatible", "backend_unavailable", "retrieval_transient_error", "no_results", "no_exportable_cifs"), True,
    ),
    SupportedToolName.RUN_CSP: ToolContract(
        SupportedToolName.RUN_CSP, "Run the deterministic CSP workflow.", RunCSPInput, ToolResult,
        ("create deterministic workflow run and artifacts",), ApprovalPolicy.PLAN_APPROVAL, WriteScopePolicy.AGENT_RUN_ROOT,
        ("missing_db", "embedding_incompatible", "spp_incomplete", "gurobi_unavailable", "INFEASIBLE", "validation_failed", "workflow_io_error", "system_error"),
    ),
    SupportedToolName.VALIDATE_CANDIDATE: ToolContract(
        SupportedToolName.VALIDATE_CANDIDATE, "Validate a registered candidate through the SCA boundary.",
        ValidateCandidateInput, ToolResult, (), ApprovalPolicy.READ_ONLY, WriteScopePolicy.NONE,
        ("candidate_unknown", "candidate_missing", "parse_failure", "backend_unavailable", "unsupported_topology_policy", "system_error"), True,
    ),
    SupportedToolName.INSPECT_RUN: ToolContract(
        SupportedToolName.INSPECT_RUN, "Read selected fields from an existing deterministic run.",
        InspectRunInput, ToolResult, (), ApprovalPolicy.READ_ONLY, WriteScopePolicy.NONE,
        ("unknown_run", "missing_manifest", "corrupt_manifest", "hash_mismatch", "unauthorized_path", "transient_io_error", "system_error"), True,
    ),
}
TOOL_CONTRACTS: Mapping[SupportedToolName, ToolContract] = MappingProxyType(_CONTRACTS)


def get_tool_contract(name: SupportedToolName | str) -> ToolContract:
    try:
        key = SupportedToolName(name)
    except (TypeError, ValueError) as exc:
        raise UnknownToolError(f"unsupported agent tool: {name!r}") from exc
    return TOOL_CONTRACTS[key]


def validate_tool_input(name: SupportedToolName | str, payload: Mapping[str, Any]) -> Any:
    return get_tool_contract(name).validate_input(payload)


def validate_tool_output(name: SupportedToolName | str, payload: Mapping[str, Any]) -> ToolResult:
    return get_tool_contract(name).validate_output(payload)


__all__ = [
    "ApprovalPolicy", "InspectRunInput", "RunCSPInput", "SearchCrystalDBInput", "TOOL_CONTRACTS",
    "ToolContract", "UnknownToolError", "ValidateCandidateInput", "WriteScopePolicy", "get_tool_contract",
    "validate_tool_input", "validate_tool_output",
]
