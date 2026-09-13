"""Strictly read-only inspection of registered deterministic workflow runs."""

from __future__ import annotations

import json
from typing import Any

from ..contracts import InspectRunInput
from ..models import SupportedToolName, ToolResult
from ._utils import relative_artifact_path, sha256_file, tool_failure
from .base import AdapterExecution, BudgetImpact, ToolDependencies, ToolExecutionContext


def _portable_artifacts(values: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        if not isinstance(value, str):
            result[key] = value
            continue
        try:
            result[key] = relative_artifact_path(value, context)
        except ValueError:
            result[key] = {"status": "unauthorized_path"}
    return result


def _section(name: str, payload: dict[str, Any], context: ToolExecutionContext) -> Any:
    stages = payload.get("stages") or {}
    if name == "summary":
        return {"run_id": payload.get("run_id"), "status": payload.get("status"), "request": payload.get("request")}
    if name == "retrieval":
        return stages.get("retrieval")
    if name == "spp":
        return stages.get("spp")
    if name == "solver":
        return {"request_validation": stages.get("qlip_request_validation"), "result": stages.get("qlip")}
    if name == "candidate":
        candidate = dict(stages.get("candidate") or {})
        if candidate.get("path"):
            candidate["path"] = relative_artifact_path(candidate["path"], context)
        return candidate or None
    if name == "validation":
        return stages.get("validation")
    if name == "stages":
        return stages
    if name == "artifacts":
        return _portable_artifacts(dict(payload.get("artifacts") or {}), context)
    return payload.get(name)


class InspectRunAdapter:
    name = SupportedToolName.INSPECT_RUN
    budget_impact = BudgetImpact()

    def execute(
        self,
        request: InspectRunInput,
        context: ToolExecutionContext,
        dependencies: ToolDependencies,
        tool_call_id: str,
    ) -> AdapterExecution:
        del dependencies
        reference = context.workflow_runs.get(request.workflow_run_id)
        provenance = {"underlying_api": "WorkflowResult JSON manifest", "read_only": True}
        if reference is None:
            return AdapterExecution(tool_failure(
                tool_call_id=tool_call_id, tool_name=self.name, status="unknown_run", code="unknown_run",
                message=f"workflow run is not registered: {request.workflow_run_id}", provenance=provenance,
            ))
        try:
            manifest_path = context.write_scope.resolve(reference.result_ref.path)
        except ValueError as exc:
            return AdapterExecution(tool_failure(
                tool_call_id=tool_call_id, tool_name=self.name, status="unauthorized_path", code="unauthorized_path",
                message=str(exc), provenance=provenance,
            ))
        if not manifest_path.is_file():
            return AdapterExecution(tool_failure(
                tool_call_id=tool_call_id, tool_name=self.name, status="missing_manifest", code="missing_manifest",
                message=f"workflow manifest does not exist: {reference.result_ref.path}", provenance=provenance,
            ))
        if reference.result_ref.sha256 is not None and sha256_file(manifest_path) != reference.result_ref.sha256:
            return AdapterExecution(tool_failure(
                tool_call_id=tool_call_id, tool_name=self.name, status="hash_mismatch", code="hash_mismatch",
                message="workflow manifest hash does not match its registered artifact reference", provenance=provenance,
            ))
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return AdapterExecution(tool_failure(
                tool_call_id=tool_call_id, tool_name=self.name, status="corrupt_manifest", code="corrupt_manifest",
                message=f"{type(exc).__name__}: {exc}", provenance=provenance,
            ))
        except OSError as exc:
            return AdapterExecution(tool_failure(
                tool_call_id=tool_call_id, tool_name=self.name, status="transient_io_error", code="transient_io_error",
                message=f"{type(exc).__name__}: {exc}", retryable=True, provenance=provenance,
            ))
        if not isinstance(payload, dict) or payload.get("run_id") != reference.run_id:
            return AdapterExecution(tool_failure(
                tool_call_id=tool_call_id, tool_name=self.name, status="corrupt_manifest", code="corrupt_manifest",
                message="workflow manifest does not match its registered run ID", provenance=provenance,
            ))
        selected = {name: _section(name, payload, context) for name in request.include}
        return AdapterExecution(ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status="inspected",
            data={"subsystem_status": "inspected", "workflow_run_id": reference.run_id, "sections": selected},
            artifact_refs=tuple(item for item in (reference.result_ref, reference.candidate_ref) if item is not None),
            provenance=provenance,
        ))


__all__ = ["InspectRunAdapter"]
