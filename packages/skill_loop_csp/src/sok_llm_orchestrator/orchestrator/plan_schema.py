from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

PLAN_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "retrieval_mode",
        "use_spp",
        "corpus_strategy",
        "guidance_mode",
        "verification_preset",
        "rerun_permissions",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "run_plan.v1"},
        "retrieval_mode": {"type": "string", "enum": ["metadata", "text", "fingerprint", "hybrid"]},
        "use_spp": {"type": "boolean"},
        "corpus_strategy": {"type": "string", "enum": ["top_k", "composition_tight", "family_biased", "property_biased"]},
        "guidance_mode": {"type": "string", "enum": ["none", "guidance_only", "budget_constraint"]},
        "verification_preset": {"type": "string"},
        "rerun_permissions": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass(slots=True)
class RunPlan:
    retrieval_mode: str
    use_spp: bool
    corpus_strategy: str
    guidance_mode: str
    verification_preset: str
    rerun_permissions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "run_plan.v1",
            "retrieval_mode": self.retrieval_mode,
            "use_spp": self.use_spp,
            "corpus_strategy": self.corpus_strategy,
            "guidance_mode": self.guidance_mode,
            "verification_preset": self.verification_preset,
            "rerun_permissions": list(self.rerun_permissions),
        }


def validate_run_plan(plan: dict[str, Any]) -> None:
    validator = Draft202012Validator(PLAN_SCHEMA)
    errors = sorted(validator.iter_errors(plan), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        pointer = "/" + "/".join(str(x) for x in err.absolute_path)
        raise ValueError(f"{pointer}: {err.message}")
