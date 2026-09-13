"""Read-only adapter for the public LLM-CSP validation boundary."""

from __future__ import annotations

from llm_csp.validation import TopologyValidationResult, ValidationResult

from ..contracts import ValidateCandidateInput
from ..models import SupportedToolName, ToolError, ToolResult
from .base import AdapterExecution, BudgetImpact, ToolDependencies, ToolExecutionContext


_VALIDATION_OPTIONS = frozenset({
    "target_space_group", "method", "query_id", "require_spacegroup", "run_alignn", "reference_structures",
})


class ValidateCandidateAdapter:
    name = SupportedToolName.VALIDATE_CANDIDATE
    budget_impact = BudgetImpact()

    def execute(
        self,
        request: ValidateCandidateInput,
        context: ToolExecutionContext,
        dependencies: ToolDependencies,
        tool_call_id: str,
    ) -> AdapterExecution:
        try:
            reference = context.artifact(request.candidate_ref)
        except ValueError as exc:
            status = "candidate_unknown"
            return AdapterExecution(ToolResult(
                tool_call_id=tool_call_id, tool_name=self.name, status=status,
                data={"subsystem_status": status, "candidate_ref": request.candidate_ref.to_dict()},
                provenance={"underlying_api": "llm_csp.validation.validate_cif", "read_only": True},
                error=ToolError(
                    code=status, message=str(exc), details={"artifact_id": request.candidate_ref.artifact_id},
                    subsystem_status=status, retryable=False,
                ),
            ))
        candidate_path = context.write_scope.resolve(reference.path)
        if not candidate_path.is_file():
            status = "candidate_missing"
            return AdapterExecution(ToolResult(
                tool_call_id=tool_call_id, tool_name=self.name, status=status,
                data={"subsystem_status": status, "candidate_ref": reference.to_dict()},
                provenance={"underlying_api": "llm_csp.validation.validate_cif", "read_only": True},
                error=ToolError(
                    code=status, message=f"candidate artifact does not exist: {reference.path}",
                    details={"artifact_id": reference.artifact_id}, subsystem_status=status, retryable=False,
                ),
            ))
        options = dict(request.validation_options)
        unknown = set(options) - _VALIDATION_OPTIONS
        if unknown:
            raise ValueError(f"unsupported validation option(s): {', '.join(sorted(unknown))}")
        if dependencies.validate_general is None:
            from llm_csp.validation import validate_cif

            validate_general = validate_cif
        else:
            validate_general = dependencies.validate_general
        general = validate_general(
            candidate_path,
            target_formula=request.target_formula,
            run_id=context.agent_run_id,
            **options,
        )
        if not isinstance(general, ValidationResult):
            raise TypeError("llm_csp.validation.validate_cif must return ValidationResult")

        topology = None
        if request.topology_family is not None and general.parseable:
            if dependencies.structure_loader is None:
                from pymatgen.core import Structure

                structure_loader = Structure.from_file
            else:
                structure_loader = dependencies.structure_loader
            structure = structure_loader(str(candidate_path))
            if dependencies.validate_topology is None:
                from llm_csp.validation import validate_family_topology

                validate_topology = validate_family_topology
            else:
                validate_topology = dependencies.validate_topology
            topology = validate_topology(structure, request.topology_family)
            if not isinstance(topology, TopologyValidationResult):
                raise TypeError("llm_csp.validation.validate_family_topology must return TopologyValidationResult")

        status = general.status
        if status == "evaluated" and topology is not None and topology.status != "evaluated":
            status = topology.status
        errors = list(general.errors)
        if topology is not None:
            errors.extend(topology.errors)
        error = None
        if status != "evaluated":
            first = errors[0] if errors else None
            code = first.kind if first is not None else status
            message = first.message if first is not None else f"validation returned {status}"
            error = ToolError(
                code=code,
                message=message,
                details={"candidate_artifact_id": reference.artifact_id},
                subsystem_status=status,
                retryable=False,
            )
        warnings = tuple(general.warnings) + (tuple(topology.warnings) if topology is not None else ())
        return AdapterExecution(ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status=status,
            data={
                "subsystem_status": status,
                "candidate_ref": reference.to_dict(),
                "general": general.to_dict(),
                "topology": topology.to_dict() if topology is not None else None,
            },
            provenance={
                "underlying_api": "llm_csp.validation.validate_cif",
                "topology_api": "llm_csp.validation.validate_family_topology" if request.topology_family else None,
                "read_only": True,
            },
            warnings=warnings,
            error=error,
        ))


__all__ = ["ValidateCandidateAdapter"]
