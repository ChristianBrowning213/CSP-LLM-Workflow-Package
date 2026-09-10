"""Normalize Crystal-DB and deterministic fixture retrieval results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from llm_csp.schemas.workflow import CSPWorkflowRequest, RetrievalConfig


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    structure_id: str
    score: float
    cif_path: str | None
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RetrievalStageResult:
    status: str
    backend: str
    records: tuple[EvidenceRecord, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "backend": self.backend,
            "records": [record.to_dict() for record in self.records],
            "diagnostics": self.diagnostics,
        }


def _fixture_result(value: Any) -> RetrievalStageResult:
    if isinstance(value, RetrievalStageResult):
        return value
    if not isinstance(value, dict):
        raise TypeError("retrieval provider must return RetrievalStageResult or a dictionary")
    records = tuple(
        item if isinstance(item, EvidenceRecord) else EvidenceRecord(**item)
        for item in value.get("records", ())
    )
    return RetrievalStageResult(
        status=str(value.get("status", "retrieval_success")),
        backend=str(value.get("backend", "configured_retrieval_provider")),
        records=records,
        diagnostics=dict(value.get("diagnostics", {})),
    )


def _error_status(payload: dict[str, Any]) -> str:
    error = payload.get("errors") or {}
    code = str(error.get("code") or error.get("error") or "").lower()
    if "embedding" in code or "vector" in code:
        return "retrieval_embedding_incompatible"
    backend = payload.get("backend_status") or {}
    if backend and not backend.get("ready", False):
        return "retrieval_backend_unavailable"
    return "retrieval_backend_unavailable"


def retrieve_evidence(
    request: CSPWorkflowRequest,
    config: RetrievalConfig,
    export_dir: Path,
    *,
    provider: Any = None,
) -> RetrievalStageResult:
    """Retrieve ranked evidence without opening Crystal-DB storage internally."""

    export_dir.mkdir(parents=True, exist_ok=True)
    if provider is not None:
        try:
            value = provider(request=request, config=config, export_dir=export_dir)
            result = _fixture_result(value)
        except Exception as exc:
            return RetrievalStageResult(
                status="retrieval_backend_unavailable",
                backend="configured_retrieval_provider",
                diagnostics={"error_type": type(exc).__name__, "message": str(exc)},
            )
    else:
        try:
            from crystal_db.retrieval import text_search

            payload = text_search(
                query_text=request.query,
                db_path=str(config.db_path) if config.db_path is not None else None,
                k=config.k,
                embed_engine=config.embed_engine,
                model_name=config.model_name,
                model_version=config.model_version,
                text_engine=config.text_engine,
                text_view=config.text_view,
                show_text_top=config.k,
                export_dir=str(export_dir),
                export_top=config.k,
                redacted=False,
                demo_export=config.demo_export,
            )
        except Exception as exc:
            return RetrievalStageResult(
                status="retrieval_backend_unavailable",
                backend="crystal_db.retrieval.text_search",
                diagnostics={"error_type": type(exc).__name__, "message": str(exc)},
            )
        if payload.get("status") != "ok":
            return RetrievalStageResult(
                status=_error_status(payload),
                backend="crystal_db.retrieval.text_search",
                diagnostics=dict(payload),
            )
        records: list[EvidenceRecord] = []
        for neighbor in payload.get("neighbors", []):
            export = neighbor.get("cif_export") or {}
            records.append(
                EvidenceRecord(
                    structure_id=str(neighbor.get("structure_id")),
                    score=float(neighbor.get("score", neighbor.get("similarity", 0.0))),
                    cif_path=str(export.get("path")) if export.get("status") == "exported" else None,
                    provenance=dict(neighbor.get("provenance") or {}),
                    metadata=dict(neighbor.get("metadata") or {}),
                )
            )
        result = RetrievalStageResult(
            status="retrieval_success" if records else "retrieval_empty",
            backend="crystal_db.retrieval.text_search",
            records=tuple(records),
            diagnostics={"query": payload.get("query"), "backend_status": payload.get("backend_status")},
        )

    if result.status != "retrieval_success":
        return result
    if not result.records:
        return RetrievalStageResult("retrieval_empty", result.backend, diagnostics=result.diagnostics)
    usable = tuple(
        record
        for record in result.records
        if record.cif_path is not None and Path(record.cif_path).is_file()
    )
    if not usable:
        return RetrievalStageResult(
            "retrieval_no_exportable_cifs",
            result.backend,
            result.records,
            result.diagnostics,
        )
    return RetrievalStageResult("retrieval_success", result.backend, usable, result.diagnostics)
