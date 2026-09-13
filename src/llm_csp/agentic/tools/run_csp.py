"""Adapter for one complete deterministic LLM-CSP workflow run."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from llm_csp.schemas import WorkflowResult

from ..contracts import RunCSPInput
from ..models import SupportedToolName, ToolError, ToolResult, WorkflowRunReference
from ._utils import artifact_reference
from .base import AdapterExecution, BudgetImpact, ToolDependencies, ToolExecutionContext


def _subsystem_statuses(result: WorkflowResult) -> dict[str, Any]:
    stages = result.stages
    retrieval = stages.get("retrieval") or {}
    spp = stages.get("spp") or {}
    qlip = stages.get("qlip") or {}
    candidate = stages.get("candidate") or {}
    validation = stages.get("validation") or {}
    general = (validation.get("general") or {}) if isinstance(validation, dict) else {}
    topology = validation.get("topology") if isinstance(validation, dict) else None
    return {
        "workflow": result.status,
        "retrieval": retrieval.get("status"),
        "spp": spp.get("status"),
        "solver": qlip.get("status") or candidate.get("solver_status"),
        "validation": (general.get("status") or validation.get("status")) if isinstance(validation, dict) else None,
        "topology": topology.get("status") if isinstance(topology, dict) else None,
    }


def _workflow_error(result: WorkflowResult, statuses: dict[str, Any]) -> ToolError | None:
    solver = statuses.get("solver")
    if solver == "INFEASIBLE":
        return None
    if not result.errors:
        return None
    first = dict(result.errors[0])
    code = str(first.get("code") or result.status)
    subsystem_status = code
    details = first.get("details")
    if code == "qlip_backend_unavailable" and isinstance(details, dict):
        nested = details.get("errors") or ()
        if any((item.get("code") if isinstance(item, dict) else None) == "gurobi_unavailable" for item in nested):
            subsystem_status = "gurobi_unavailable"
    if statuses.get("spp") == "spp_incomplete":
        subsystem_status = "spp_incomplete"
    return ToolError(
        code=code,
        message=str(first.get("message") or f"deterministic workflow returned {subsystem_status}"),
        details=first,
        subsystem_status=subsystem_status,
        retryable=False,
    )


class RunCSPAdapter:
    name = SupportedToolName.RUN_CSP
    budget_impact = BudgetImpact(workflow_runs=1)

    def execute(
        self,
        request: RunCSPInput,
        context: ToolExecutionContext,
        dependencies: ToolDependencies,
        tool_call_id: str,
    ) -> AdapterExecution:
        workflow_id = context.allocate_id("workflow_run")
        workflow_output_root = context.write_scope.resolve("workflow_runs")
        config = replace(context.workflow_config(request.config_ref), output_root=workflow_output_root, run_id=workflow_id)
        if dependencies.workflow is None:
            from llm_csp.workflow import run_csp_workflow

            executor = run_csp_workflow
        else:
            executor = dependencies.workflow
        try:
            result = executor(request.request, config)
        except (FileExistsError, FileNotFoundError, PermissionError, OSError) as exc:
            status = "workflow_io_error"
            tool_result = ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status=status,
                data={"subsystem_status": status, "workflow_run_id": workflow_id},
                provenance={"underlying_api": "llm_csp.workflow.run_csp_workflow", "workflow_run_id": workflow_id},
                error=ToolError(
                    code=status, message=f"{type(exc).__name__}: {exc}",
                    details={"exception_type": type(exc).__name__}, subsystem_status=status, retryable=False,
                ),
            )
            return AdapterExecution(tool_result)
        if not isinstance(result, WorkflowResult):
            raise TypeError("llm_csp.workflow.run_csp_workflow must return WorkflowResult")
        if result.run_id != workflow_id:
            raise ValueError("workflow result run ID does not match the allocated ID")
        expected_root = (workflow_output_root / workflow_id).resolve()
        reported_root = Path(result.artifacts.get("run_root", expected_root)).resolve()
        if reported_root != expected_root:
            raise ValueError("workflow result root does not match the allocated run directory")

        manifest_path = result.artifacts.get("run_manifest")
        if manifest_path is None:
            raise ValueError("workflow result did not expose its run manifest")
        manifest_ref = artifact_reference(
            path=manifest_path, kind="workflow_manifest", producing_run_id=workflow_id,
            context=context, id_prefix="artifact_workflow_manifest",
        )
        artifact_refs = [manifest_ref]
        candidate_ref = None
        if result.artifacts.get("candidate_cif") is not None:
            candidate_ref = artifact_reference(
                path=result.artifacts["candidate_cif"], kind="candidate_cif", producing_run_id=workflow_id,
                context=context, id_prefix="artifact_candidate_cif",
            )
            artifact_refs.append(candidate_ref)
        if result.artifacts.get("validation_result") is not None:
            artifact_refs.append(artifact_reference(
                path=result.artifacts["validation_result"], kind="validation_result", producing_run_id=workflow_id,
                context=context, id_prefix="artifact_validation_result",
            ))
        workflow_ref = WorkflowRunReference(workflow_id, result.status, manifest_ref, candidate_ref)
        statuses = _subsystem_statuses(result)
        candidate = result.stages.get("candidate") or {}
        data = {
            "subsystem_status": statuses.get("solver") or statuses.get("spp") or statuses.get("retrieval") or result.status,
            "workflow_status": result.status,
            "subsystem_statuses": statuses,
            "objective": candidate.get("solver_objective"),
            "candidate": candidate or None,
            "validation": result.stages.get("validation"),
            "workflow_run": workflow_ref.to_dict(),
            "errors": list(result.errors),
        }
        return AdapterExecution(
            ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status=result.status,
                data=data,
                artifact_refs=tuple(artifact_refs),
                provenance={
                    "underlying_api": "llm_csp.workflow.run_csp_workflow",
                    "workflow_run_id": workflow_id,
                    "workflow": result.provenance,
                },
                warnings=result.warnings,
                error=_workflow_error(result, statuses),
            ),
            workflow_ref,
        )


__all__ = ["RunCSPAdapter"]
