"""Read-only Crystal-DB text-search adapter."""

from __future__ import annotations

from typing import Any, Mapping

from ..contracts import SearchCrystalDBInput
from ..models import SupportedToolName, ToolError, ToolResult
from ._utils import retryable_for
from .base import AdapterExecution, BudgetImpact, ToolDependencies, ToolExecutionContext


def _status(payload: Mapping[str, Any]) -> str:
    neighbors = tuple(payload.get("neighbors") or ())
    if payload.get("status") == "ok":
        if not neighbors:
            return "no_results"
        if all((item.get("provenance") or {}).get("allow_export") in (0, False) for item in neighbors):
            return "no_exportable_cifs"
        return "retrieval_success"
    error = payload.get("errors") or {}
    backend = payload.get("backend_status") or {}
    code = str(error.get("code") or error.get("error") or backend.get("state") or "backend_unavailable")
    lowered = code.lower()
    if "missing" in lowered and ("db" in lowered or "database" in lowered):
        return "missing_db"
    if lowered in {"candidate_set_empty", "no_results"}:
        return "no_results"
    if "embedding" in lowered or "vector" in lowered:
        return "embedding_incompatible"
    if "transient" in lowered or "timeout" in lowered:
        return "retrieval_transient_error"
    return "backend_unavailable"


class SearchCrystalDBAdapter:
    name = SupportedToolName.SEARCH_CRYSTAL_DB
    budget_impact = BudgetImpact(retrieval_calls=1)

    def execute(
        self,
        request: SearchCrystalDBInput,
        context: ToolExecutionContext,
        dependencies: ToolDependencies,
        tool_call_id: str,
    ) -> AdapterExecution:
        if request.formula is not None:
            raise ValueError("formula filtering is not supported by crystal_db.retrieval.text_search")
        config = context.retrieval_config(request.retrieval_ref)
        if dependencies.retrieval is None:
            from crystal_db.retrieval import text_search

            retrieval = text_search
        else:
            retrieval = dependencies.retrieval
        try:
            payload = retrieval(
                query_text=request.query,
                db_path=str(config.db_path) if config.db_path is not None else None,
                k=request.k,
                embed_engine=config.embed_engine,
                model_name=config.model_name,
                model_version=config.model_version,
                text_engine=config.text_engine,
                text_view=config.text_view,
                show_text_top=request.k,
                export_dir=None,
                redacted=True,
                demo_export=False,
            )
        except (ImportError, ModuleNotFoundError, FileNotFoundError, PermissionError, OSError) as exc:
            status = "missing_db" if isinstance(exc, FileNotFoundError) else "backend_unavailable"
            return AdapterExecution(ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status=status,
                data={"subsystem_status": status, "ranked_results": []},
                provenance={"underlying_api": "crystal_db.retrieval.text_search", "read_only": True},
                error=ToolError(
                    code=status,
                    message=f"{type(exc).__name__}: {exc}",
                    details={"exception_type": type(exc).__name__},
                    subsystem_status=status,
                    retryable=False,
                ),
            ))
        if not isinstance(payload, Mapping):
            raise TypeError("crystal_db.retrieval.text_search must return a mapping")
        status = _status(payload)
        neighbors = [dict(item) for item in payload.get("neighbors") or ()]
        data = {
            "subsystem_status": status,
            "query": payload.get("query"),
            "ranked_results": neighbors,
            "backend_state": payload.get("backend_status"),
            "cif_export_readiness": [
                {
                    "structure_id": item.get("structure_id"),
                    "allowed": (item.get("provenance") or {}).get("allow_export") not in (0, False),
                }
                for item in neighbors
            ],
        }
        error_payload = payload.get("errors") or {}
        error = None
        if status != "retrieval_success":
            message = str(error_payload.get("message") or f"Crystal-DB returned {status}")
            error = ToolError(
                code=str(error_payload.get("code") or status),
                message=message,
                details={"backend_status": payload.get("backend_status"), "diagnostics": error_payload.get("diagnostics")},
                subsystem_status=status,
                retryable=retryable_for(status),
            )
        return AdapterExecution(ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status=status,
            data=data,
            provenance={"underlying_api": "crystal_db.retrieval.text_search", "read_only": True},
            error=error,
        ))


__all__ = ["SearchCrystalDBAdapter"]
