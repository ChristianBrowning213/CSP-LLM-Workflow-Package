"""Paper-diversity benchmark preparation helpers."""

from .smoke_preparation import (
    DEFAULT_SCAFFOLDS,
    canonical_hash,
    load_frozen_e4_tasks,
    preflight_task,
    resolve_skill_loop_root,
    task_orbits,
    explicit_charge_assumptions,
    sha256_file,
    sha256_text,
    structured_intent_hash,
)
from .record_identity import CanonicalRecordKey, IdentityVerification, RecordIdentity, canonical_record_key, verify_embedding_record

__all__ = [
    "DEFAULT_SCAFFOLDS",
    "canonical_hash",
    "load_frozen_e4_tasks",
    "preflight_task",
    "resolve_skill_loop_root",
    "task_orbits",
    "explicit_charge_assumptions",
    "sha256_file",
    "sha256_text",
    "structured_intent_hash",
    "CanonicalRecordKey",
    "IdentityVerification",
    "RecordIdentity",
    "canonical_record_key",
    "verify_embedding_record",
]
