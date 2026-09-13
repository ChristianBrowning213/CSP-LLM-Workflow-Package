"""Filesystem and error helpers shared by deterministic adapters."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from ..models import ArtifactReference, SupportedToolName, ToolError, ToolResult
from .base import ToolExecutionContext


NON_RETRYABLE_STATUSES = frozenset({
    "missing_db", "embedding_incompatible", "backend_unavailable", "no_exportable_cifs",
    "INFEASIBLE", "gurobi_unavailable", "candidate_missing", "parse_failure",
    "unsupported_policy", "unknown_run", "missing_manifest", "corrupt_manifest", "hash_mismatch",
})
RETRYABLE_STATUSES = frozenset({"retrieval_transient_error", "transient_io_error"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_artifact_path(path: str | Path, context: ToolExecutionContext) -> str:
    candidate = Path(path).resolve()
    root = Path(context.run_root)
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact path is outside the agent run root: {candidate}") from exc
    context.write_scope.resolve(relative.as_posix())
    return relative.as_posix()


def artifact_reference(
    *, path: str | Path, kind: str, producing_run_id: str, context: ToolExecutionContext,
    id_prefix: str = "artifact",
) -> ArtifactReference:
    absolute = Path(path).resolve()
    if not absolute.is_file():
        raise FileNotFoundError(f"expected artifact does not exist: {absolute}")
    return ArtifactReference(
        artifact_id=context.allocate_id(id_prefix),
        kind=kind,
        path=relative_artifact_path(absolute, context),
        producing_run_id=producing_run_id,
        sha256=sha256_file(absolute),
    )


def tool_failure(
    *, tool_call_id: str, tool_name: SupportedToolName, status: str, code: str,
    message: str, details: Mapping[str, Any] | None = None, retryable: bool = False,
    provenance: Mapping[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        status=status,
        data={"subsystem_status": status},
        provenance=dict(provenance or {}),
        error=ToolError(
            code=code,
            message=message,
            details=dict(details or {}),
            subsystem_status=status,
            retryable=retryable,
        ),
    )


def retryable_for(status: str) -> bool:
    return status in RETRYABLE_STATUSES


__all__ = [
    "NON_RETRYABLE_STATUSES", "RETRYABLE_STATUSES", "artifact_reference", "relative_artifact_path",
    "retryable_for", "sha256_file", "tool_failure",
]
