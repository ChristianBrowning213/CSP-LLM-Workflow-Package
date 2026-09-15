from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

OPTIMIZATION_ACTION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "action_id",
        "action_family",
        "retrieval_policy",
        "corpus_strategy",
        "spp_calibration_mode",
        "qlip_guidance_mode",
        "cell_selection_policy",
        "rationale",
        "expected_risk_reward",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "optimization.action.v1"},
        "action_id": {"type": "string"},
        "action_family": {"type": "string"},
        "retrieval_policy": {"type": "string", "enum": ["metadata", "text", "fingerprint", "hybrid"]},
        "corpus_strategy": {
            "type": "string",
            "enum": ["top_k", "composition_tight", "family_biased", "property_biased"],
        },
        "spp_calibration_mode": {"type": "string", "enum": ["balanced", "aggressive", "conservative"]},
        "qlip_guidance_mode": {"type": "string", "enum": ["none", "guidance_only", "budget_constraint"]},
        "cell_selection_policy": {"type": "string", "enum": ["baseline_default", "retrieval_informed", "fixed_benchmark"]},
        "rationale": {"type": "string"},
        "expected_risk_reward": {
            "type": "object",
            "additionalProperties": False,
            "required": ["risk", "reward"],
            "properties": {
                "risk": {"type": "string"},
                "reward": {"type": "string"},
            },
        },
        "retrieval_candidate_k": {"type": "integer", "minimum": 1, "maximum": 50},
        "corpus_top_k": {"type": "integer", "minimum": 1, "maximum": 50},
        "corpus_strategy_candidates": {
            "type": "array",
            "items": {"type": "string", "enum": ["top_k", "composition_tight", "family_biased", "property_biased"]},
            "minItems": 1,
            "maxItems": 8,
        },
        "corpus_top_k_candidates": {
            "type": "array",
            "items": {"type": "integer", "minimum": 1, "maximum": 50},
            "minItems": 1,
            "maxItems": 8,
        },
        "spp_package_variant": {"type": "string", "enum": ["default", "focus", "broad"]},
        "spp_package_alternatives": {
            "type": "array",
            "items": {"type": "string", "enum": ["default", "focus", "broad"]},
            "minItems": 1,
            "maxItems": 6,
        },
        "spp_package_target": {"type": "number", "minimum": 0.0, "maximum": 10.0},
        "spp_payload_profile": {"type": "string", "enum": ["weak", "balanced", "strong"]},
        "spp_guidance_weight": {"type": "number", "minimum": 0.0, "maximum": 10.0},
        "spp_top_k_breakdown": {"type": "integer", "minimum": 0, "maximum": 100},
        "spp_pairs_policy": {"type": "string", "enum": ["task_pairs", "all_available"]},
        "spp_oob_policy": {"type": "string", "enum": ["zero", "clamp", "max"]},
        "spp_missing_pair_policy": {"type": "string", "enum": ["zero", "max_global", "error"]},
        "weighting_profile": {
            "type": "string",
            "enum": [
                "base_dominant",
                "balanced",
                "guidance_dominant",
                "property_push_strong",
                "experimental_extreme",
            ],
        },
        "structure_perturbation_profile": {
            "type": "string",
            "enum": ["minimal", "moderate", "aggressive", "template_shuffle"],
        },
        "template_seed_profile": {
            "type": "string",
            "enum": ["canonical", "polymorph_mix", "framework_bias", "ordering_bias"],
        },
        "lattice_candidate_profile": {
            "type": "string",
            "enum": ["narrow", "expanded", "multibasin"],
        },
        "symmetry_relaxation_profile": {
            "type": "string",
            "enum": ["strict", "soft", "relaxed"],
        },
        "ordering_perturbation_profile": {
            "type": "string",
            "enum": ["none", "site_shuffle", "cation_swap_bias"],
        },
    },
}


@dataclass(slots=True)
class OptimizationAction:
    action_id: str
    action_family: str
    retrieval_policy: str
    corpus_strategy: str
    spp_calibration_mode: str
    qlip_guidance_mode: str
    cell_selection_policy: str
    rationale: str
    expected_risk_reward: dict[str, str]
    retrieval_candidate_k: int | None = None
    corpus_top_k: int | None = None
    corpus_strategy_candidates: list[str] | None = None
    corpus_top_k_candidates: list[int] | None = None
    spp_package_variant: str | None = None
    spp_package_alternatives: list[str] | None = None
    spp_package_target: float | None = None
    spp_payload_profile: str | None = None
    spp_guidance_weight: float | None = None
    spp_top_k_breakdown: int | None = None
    spp_pairs_policy: str | None = None
    spp_oob_policy: str | None = None
    spp_missing_pair_policy: str | None = None
    weighting_profile: str | None = None
    structure_perturbation_profile: str | None = None
    template_seed_profile: str | None = None
    lattice_candidate_profile: str | None = None
    symmetry_relaxation_profile: str | None = None
    ordering_perturbation_profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "optimization.action.v1",
            "action_id": self.action_id,
            "action_family": self.action_family,
            "retrieval_policy": self.retrieval_policy,
            "corpus_strategy": self.corpus_strategy,
            "spp_calibration_mode": self.spp_calibration_mode,
            "qlip_guidance_mode": self.qlip_guidance_mode,
            "cell_selection_policy": self.cell_selection_policy,
            "rationale": self.rationale,
            "expected_risk_reward": dict(self.expected_risk_reward),
        }
        if isinstance(self.retrieval_candidate_k, int):
            payload["retrieval_candidate_k"] = int(self.retrieval_candidate_k)
        if isinstance(self.corpus_top_k, int):
            payload["corpus_top_k"] = int(self.corpus_top_k)
        if isinstance(self.corpus_strategy_candidates, list) and self.corpus_strategy_candidates:
            payload["corpus_strategy_candidates"] = [str(item) for item in self.corpus_strategy_candidates]
        if isinstance(self.corpus_top_k_candidates, list) and self.corpus_top_k_candidates:
            payload["corpus_top_k_candidates"] = [int(item) for item in self.corpus_top_k_candidates]
        if isinstance(self.spp_package_variant, str) and self.spp_package_variant:
            payload["spp_package_variant"] = self.spp_package_variant
        if isinstance(self.spp_package_alternatives, list) and self.spp_package_alternatives:
            payload["spp_package_alternatives"] = [str(item) for item in self.spp_package_alternatives]
        if isinstance(self.spp_package_target, (int, float)):
            payload["spp_package_target"] = float(self.spp_package_target)
        if isinstance(self.spp_payload_profile, str) and self.spp_payload_profile:
            payload["spp_payload_profile"] = self.spp_payload_profile
        if isinstance(self.spp_guidance_weight, (int, float)):
            payload["spp_guidance_weight"] = float(self.spp_guidance_weight)
        if isinstance(self.spp_top_k_breakdown, int):
            payload["spp_top_k_breakdown"] = int(self.spp_top_k_breakdown)
        if isinstance(self.spp_pairs_policy, str) and self.spp_pairs_policy:
            payload["spp_pairs_policy"] = self.spp_pairs_policy
        if isinstance(self.spp_oob_policy, str) and self.spp_oob_policy:
            payload["spp_oob_policy"] = self.spp_oob_policy
        if isinstance(self.spp_missing_pair_policy, str) and self.spp_missing_pair_policy:
            payload["spp_missing_pair_policy"] = self.spp_missing_pair_policy
        if isinstance(self.weighting_profile, str) and self.weighting_profile:
            payload["weighting_profile"] = self.weighting_profile
        if isinstance(self.structure_perturbation_profile, str) and self.structure_perturbation_profile:
            payload["structure_perturbation_profile"] = self.structure_perturbation_profile
        if isinstance(self.template_seed_profile, str) and self.template_seed_profile:
            payload["template_seed_profile"] = self.template_seed_profile
        if isinstance(self.lattice_candidate_profile, str) and self.lattice_candidate_profile:
            payload["lattice_candidate_profile"] = self.lattice_candidate_profile
        if isinstance(self.symmetry_relaxation_profile, str) and self.symmetry_relaxation_profile:
            payload["symmetry_relaxation_profile"] = self.symmetry_relaxation_profile
        if isinstance(self.ordering_perturbation_profile, str) and self.ordering_perturbation_profile:
            payload["ordering_perturbation_profile"] = self.ordering_perturbation_profile
        return payload


def validate_optimization_action(payload: dict[str, Any]) -> None:
    validator = Draft202012Validator(OPTIMIZATION_ACTION_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        pointer = "/" + "/".join(str(x) for x in err.absolute_path)
        raise ValueError(f"{pointer}: {err.message}")
