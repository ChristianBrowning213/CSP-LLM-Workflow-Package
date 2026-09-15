from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

SPP_ARTIFACT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "artifact_id",
        "corpus_hash",
        "weighting_policy",
        "bin_policy",
        "smoothing_params",
        "calibration_summary",
        "neighbor_policy",
        "cutoff_policy",
        "shrink_protection",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "spp.artifact.v1"},
        "artifact_id": {"type": "string"},
        "corpus_hash": {"type": "string"},
        "weighting_policy": {"type": "string"},
        "bin_policy": {"type": "object"},
        "smoothing_params": {"type": "object"},
        "calibration_summary": {"type": "object"},
        "neighbor_policy": {"type": "string"},
        "cutoff_policy": {"type": "string"},
        "shrink_protection": {"type": "object"},
        "metadata": {"type": "object"},
    },
}


@dataclass(slots=True)
class SPPArtifactManifest:
    artifact_id: str
    corpus_hash: str
    weighting_policy: str
    bin_policy: dict[str, Any]
    smoothing_params: dict[str, Any]
    calibration_summary: dict[str, Any]
    neighbor_policy: str
    cutoff_policy: str
    shrink_protection: dict[str, Any]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "spp.artifact.v1",
            "artifact_id": self.artifact_id,
            "corpus_hash": self.corpus_hash,
            "weighting_policy": self.weighting_policy,
            "bin_policy": self.bin_policy,
            "smoothing_params": self.smoothing_params,
            "calibration_summary": self.calibration_summary,
            "neighbor_policy": self.neighbor_policy,
            "cutoff_policy": self.cutoff_policy,
            "shrink_protection": self.shrink_protection,
            "metadata": self.metadata,
        }

    @property
    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_spp_artifact(payload: dict[str, Any]) -> None:
    validator = Draft202012Validator(SPP_ARTIFACT_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        pointer = "/" + "/".join(str(x) for x in err.absolute_path)
        raise ValueError(f"{pointer}: {err.message}")
