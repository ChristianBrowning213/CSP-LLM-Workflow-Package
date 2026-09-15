from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

RETRIEVAL_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["structure_id", "provenance", "scores", "modality", "why_returned"],
    "properties": {
        "structure_id": {"type": "string"},
        "provenance": {"type": "string"},
        "scores": {"type": "object", "additionalProperties": {"type": "number"}},
        "property_metadata": {"type": ["object", "null"], "additionalProperties": {"type": ["number", "string", "boolean", "null"]}},
        "artifacts": {"type": ["object", "null"], "additionalProperties": {"type": ["number", "string", "boolean", "null"]}},
        "modality": {"type": "string", "enum": ["metadata", "text", "fingerprint", "hybrid"]},
        "identity": {"type": ["object", "null"]},
        "cell_hint": {"type": ["object", "null"]},
        "why_returned": {"type": "string"},
    },
}

RETRIEVAL_BUNDLE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "retrieval_id", "mode", "items"],
    "properties": {
        "schema_version": {"type": "string", "const": "retrieval.result.v2"},
        "retrieval_id": {"type": "string"},
        "mode": {"type": "string", "enum": ["metadata", "text", "fingerprint", "hybrid"]},
        "items": {"type": "array", "items": RETRIEVAL_ITEM_SCHEMA},
        "fusion_notes": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass(slots=True)
class RetrievalBundle:
    retrieval_id: str
    mode: str
    items: list[dict[str, Any]]
    fusion_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "retrieval.result.v2",
            "retrieval_id": self.retrieval_id,
            "mode": self.mode,
            "items": self.items,
            "fusion_notes": self.fusion_notes,
        }

    @property
    def content_hash(self) -> str:
        text = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_retrieval_bundle(payload: dict[str, Any]) -> None:
    validator = Draft202012Validator(RETRIEVAL_BUNDLE_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        pointer = "/" + "/".join(str(x) for x in err.absolute_path)
        raise ValueError(f"{pointer}: {err.message}")
