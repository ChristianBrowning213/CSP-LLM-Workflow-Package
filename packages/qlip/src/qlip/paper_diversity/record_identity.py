"""Source-aware record identity and embedding content verification."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable


IDENTITY_STATUSES = {
    "PASS", "MISSING_IDENTITY", "MISSING_EMBEDDING", "DESCRIPTION_HASH_MISMATCH",
    "EMBEDDING_HASH_MISMATCH", "DIMENSION_MISMATCH", "MODEL_MISMATCH", "AMBIGUOUS_IDENTITY",
}
_MP_SOURCES = {"materials project", "materials_project", "materials-project"}
_MP_ID = re.compile(r"^(?:nasicon-)?mp-?(\d+)(?:\.cif)?$", re.IGNORECASE)


@dataclass(frozen=True)
class CanonicalRecordKey:
    canonical_source: str
    canonical_source_id: str


@dataclass(frozen=True)
class RecordIdentity:
    raw_internal_id: str
    raw_source: str
    raw_source_id: str
    description_sha256: str = ""
    embedding_sha256: str = ""
    embedding_dimension: int | None = None
    embedding_model: str = ""
    embedding_vector: str | None = None
    archive_key: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_key(self) -> CanonicalRecordKey:
        return canonical_record_key(self.raw_source, self.raw_source_id)

    def provenance(self) -> dict[str, str]:
        key = self.canonical_key
        return {
            "raw_internal_id": self.raw_internal_id,
            "raw_source": self.raw_source,
            "raw_source_id": self.raw_source_id,
            "canonical_source": key.canonical_source,
            "canonical_source_id": key.canonical_source_id,
        }


@dataclass(frozen=True)
class IdentityVerification:
    status: str
    archive: RecordIdentity
    database: RecordIdentity | None
    resolution_method: str
    candidates_considered: int


def canonical_source(source: str) -> str:
    value = str(source or "").strip().lower()
    return "materials_project" if value in _MP_SOURCES else value


def canonical_source_id(source: str, source_id: str) -> str:
    source_key = canonical_source(source)
    raw = str(source_id or "").strip()
    if source_key == "materials_project":
        match = _MP_ID.fullmatch(raw)
        if match:
            return f"mp-{match.group(1)}"
    return raw


def canonical_record_key(source: str, source_id: str) -> CanonicalRecordKey:
    return CanonicalRecordKey(canonical_source(source), canonical_source_id(source, source_id))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unique(matches: list[RecordIdentity], archive: RecordIdentity, method: str) -> IdentityVerification | None:
    if len(matches) == 1:
        return IdentityVerification("PASS", archive, matches[0], method, 1)
    if len(matches) > 1:
        return IdentityVerification("AMBIGUOUS_IDENTITY", archive, None, method, len(matches))
    return None


def resolve_identity(archive: RecordIdentity, database_records: Iterable[RecordIdentity]) -> IdentityVerification:
    candidates = list(database_records)
    exact = _unique([row for row in candidates if row.raw_internal_id == archive.raw_internal_id], archive, "exact_internal_structure_id")
    if exact is not None:
        return exact
    key = archive.canonical_key
    canonical = _unique([row for row in candidates if row.canonical_key == key], archive, "canonical_source_and_source_id")
    if canonical is not None:
        return canonical
    if archive.description_sha256:
        description = _unique([row for row in candidates if row.description_sha256 == archive.description_sha256], archive, "description_sha256")
        if description is not None:
            return description
    return IdentityVerification("MISSING_IDENTITY", archive, None, "unresolved", 0)


def verify_embedding_record(archive: RecordIdentity, database_records: Iterable[RecordIdentity]) -> IdentityVerification:
    resolved = resolve_identity(archive, database_records)
    if resolved.status != "PASS" or resolved.database is None:
        return resolved
    actual = resolved.database
    if actual.embedding_vector is None or not actual.embedding_sha256:
        return IdentityVerification("MISSING_EMBEDDING", archive, actual, resolved.resolution_method, 1)
    if actual.embedding_model != archive.embedding_model:
        return IdentityVerification("MODEL_MISMATCH", archive, actual, resolved.resolution_method, 1)
    if actual.embedding_dimension != archive.embedding_dimension:
        return IdentityVerification("DIMENSION_MISMATCH", archive, actual, resolved.resolution_method, 1)
    if actual.description_sha256 != archive.description_sha256:
        return IdentityVerification("DESCRIPTION_HASH_MISMATCH", archive, actual, resolved.resolution_method, 1)
    if actual.embedding_sha256 != archive.embedding_sha256:
        return IdentityVerification("EMBEDDING_HASH_MISMATCH", archive, actual, resolved.resolution_method, 1)
    return resolved
