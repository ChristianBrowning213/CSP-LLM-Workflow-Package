from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sok_llm_orchestrator.optimization.action_schema import OptimizationAction
from sok_llm_orchestrator.orchestrator.logging import canonical_json, sha256_text


@dataclass(slots=True)
class CompiledOptimizationAction:
    action_id: str
    action_family: str
    compiled_id: str
    execution_mode: str
    query_suffix: str
    guided_with_spp: bool
    baseline_overrides: dict[str, Any]
    guided_overrides: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_family": self.action_family,
            "compiled_id": self.compiled_id,
            "execution_mode": self.execution_mode,
            "query_suffix": self.query_suffix,
            "guided_with_spp": self.guided_with_spp,
            "baseline_overrides": self.baseline_overrides,
            "guided_overrides": self.guided_overrides,
        }


def enforce_compiled_action_semantics(compiled: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(compiled))
    guided = out.get("guided_overrides", {})
    if not isinstance(guided, dict):
        guided = {}
        out["guided_overrides"] = guided
    guidance_mode = str(guided.get("guidance_mode") or "none").strip().lower()
    out["guided_with_spp"] = guidance_mode != "none"
    return out


def compiled_config_signature(compiled: dict[str, Any], *, include_action_identity: bool = False) -> str:
    payload = dict(compiled)
    if not include_action_identity:
        payload.pop("action_id", None)
        payload.pop("action_family", None)
        payload.pop("compiled_id", None)
    return sha256_text(canonical_json(payload))


def _normalized_hypothesis(hypothesis: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(hypothesis, dict):
        return {}
    return {str(key): value for key, value in hypothesis.items()}


def _with_hypothesis_biases(
    action: OptimizationAction,
    hypothesis: dict[str, Any],
) -> dict[str, Any]:
    knobs: dict[str, Any] = {
        "retrieval_policy": action.retrieval_policy,
        "corpus_strategy": action.corpus_strategy,
        "weighting_profile": action.weighting_profile,
        "structure_perturbation_profile": action.structure_perturbation_profile,
        "template_seed_profile": action.template_seed_profile,
        "lattice_candidate_profile": action.lattice_candidate_profile,
        "symmetry_relaxation_profile": action.symmetry_relaxation_profile,
        "ordering_perturbation_profile": action.ordering_perturbation_profile,
    }
    if not hypothesis:
        return knobs

    family = str(hypothesis.get("hypothesis_family", "")).strip().lower()
    challenge = str(hypothesis.get("challenge_type", "")).strip().lower()
    corpus_bias = str(hypothesis.get("suggested_corpus_bias", "")).strip().lower()
    perturb_bias = str(hypothesis.get("suggested_perturbation_bias", "")).strip().lower()

    if "framework" in family or "nasicon" in family:
        knobs["corpus_strategy"] = "family_biased"
        knobs["template_seed_profile"] = "framework_bias"
        knobs["lattice_candidate_profile"] = "multibasin"
        knobs["symmetry_relaxation_profile"] = "relaxed"
    elif "ordering" in family:
        knobs["template_seed_profile"] = "ordering_bias"
        knobs["ordering_perturbation_profile"] = "cation_swap_bias"
        knobs["symmetry_relaxation_profile"] = "soft"
    elif "tilted" in family or "distorted" in family:
        knobs["template_seed_profile"] = "polymorph_mix"
        knobs["symmetry_relaxation_profile"] = "soft"
        knobs["structure_perturbation_profile"] = "moderate"
    elif "template_relaxed" in family:
        knobs["structure_perturbation_profile"] = "template_shuffle"
        knobs["lattice_candidate_profile"] = "multibasin"
        knobs["symmetry_relaxation_profile"] = "relaxed"
    elif "perovskite" in family:
        knobs["template_seed_profile"] = "polymorph_mix"
        knobs["symmetry_relaxation_profile"] = "soft"

    if challenge == "ordering_sensitive":
        knobs["ordering_perturbation_profile"] = "cation_swap_bias"
        knobs["template_seed_profile"] = "ordering_bias"
    elif challenge == "framework_sensitive":
        knobs["template_seed_profile"] = "framework_bias"
        knobs["lattice_candidate_profile"] = "multibasin"
    elif challenge == "polymorph_ambiguous":
        knobs["template_seed_profile"] = "polymorph_mix"
        knobs["structure_perturbation_profile"] = "moderate"

    if "tight" in corpus_bias:
        knobs["corpus_strategy"] = "composition_tight"
    elif "family" in corpus_bias:
        knobs["corpus_strategy"] = "family_biased"
    elif "property" in corpus_bias:
        knobs["corpus_strategy"] = "property_biased"
    elif "top_k" in corpus_bias or "broader" in corpus_bias or "broad" in corpus_bias:
        knobs["corpus_strategy"] = "top_k"

    if "ordering" in perturb_bias:
        knobs["ordering_perturbation_profile"] = "cation_swap_bias"
    if "symmetry" in perturb_bias and "relax" in perturb_bias:
        knobs["symmetry_relaxation_profile"] = "relaxed"
    if "template" in perturb_bias:
        knobs["structure_perturbation_profile"] = "template_shuffle"
    if "aggressive" in perturb_bias or "strong" in perturb_bias:
        knobs["structure_perturbation_profile"] = "aggressive"
        if not isinstance(knobs.get("weighting_profile"), str) or not knobs.get("weighting_profile"):
            knobs["weighting_profile"] = "guidance_dominant"
    return knobs


def compile_action(
    action: OptimizationAction,
    *,
    hypothesis: dict[str, Any] | None = None,
) -> CompiledOptimizationAction:
    hypothesis_ctx = _normalized_hypothesis(hypothesis)
    knobs = _with_hypothesis_biases(action, hypothesis_ctx)
    query_hints: list[str] = []
    if knobs["retrieval_policy"] == "text":
        query_hints.append("broad")
    if knobs["retrieval_policy"] == "fingerprint":
        query_hints.append("prototype")
    if knobs["corpus_strategy"] == "property_biased":
        query_hints.append("high property x")
    if action.cell_selection_policy == "fixed_benchmark":
        query_hints.append("fixed cells")
    if isinstance(hypothesis_ctx.get("label"), str) and str(hypothesis_ctx.get("label")).strip():
        query_hints.append(f"hypothesis {str(hypothesis_ctx['label']).strip()}")
    elif isinstance(hypothesis_ctx.get("hypothesis_family"), str) and str(hypothesis_ctx.get("hypothesis_family")).strip():
        query_hints.append(f"family {str(hypothesis_ctx['hypothesis_family']).strip()}")
    if isinstance(hypothesis_ctx.get("suggested_guidance_focus"), str) and str(hypothesis_ctx.get("suggested_guidance_focus")).strip():
        query_hints.append(str(hypothesis_ctx["suggested_guidance_focus"]).strip())

    guided_overrides = {
        "retrieval_mode": knobs["retrieval_policy"],
        "corpus_strategy": knobs["corpus_strategy"],
        "guidance_mode": action.qlip_guidance_mode,
        "verification_preset": "benchmark",
        "cell_selection_policy": action.cell_selection_policy,
        "spp_calibration_mode": action.spp_calibration_mode,
    }
    if isinstance(action.retrieval_candidate_k, int):
        guided_overrides["retrieval_candidate_k"] = int(action.retrieval_candidate_k)
    if isinstance(action.corpus_top_k, int):
        guided_overrides["corpus_top_k"] = int(action.corpus_top_k)
    if isinstance(action.corpus_strategy_candidates, list) and action.corpus_strategy_candidates:
        guided_overrides["corpus_strategy_candidates"] = [str(item) for item in action.corpus_strategy_candidates]
    if isinstance(action.corpus_top_k_candidates, list) and action.corpus_top_k_candidates:
        guided_overrides["corpus_top_k_candidates"] = [int(item) for item in action.corpus_top_k_candidates]
    if isinstance(action.spp_package_variant, str) and action.spp_package_variant:
        guided_overrides["spp_package_variant"] = str(action.spp_package_variant)
    if isinstance(action.spp_package_alternatives, list) and action.spp_package_alternatives:
        guided_overrides["spp_package_alternatives"] = [str(item) for item in action.spp_package_alternatives]
    if isinstance(action.spp_package_target, (int, float)):
        guided_overrides["spp_package_target"] = float(action.spp_package_target)
    if isinstance(action.spp_payload_profile, str) and action.spp_payload_profile:
        guided_overrides["spp_payload_profile"] = str(action.spp_payload_profile)
    if isinstance(action.spp_guidance_weight, (int, float)):
        guided_overrides["spp_guidance_weight"] = float(action.spp_guidance_weight)
    if isinstance(action.spp_top_k_breakdown, int):
        guided_overrides["spp_top_k_breakdown"] = int(action.spp_top_k_breakdown)
    if isinstance(action.spp_pairs_policy, str) and action.spp_pairs_policy:
        guided_overrides["spp_pairs_policy"] = str(action.spp_pairs_policy)
    if isinstance(action.spp_oob_policy, str) and action.spp_oob_policy:
        guided_overrides["spp_oob_policy"] = str(action.spp_oob_policy)
    if isinstance(action.spp_missing_pair_policy, str) and action.spp_missing_pair_policy:
        guided_overrides["spp_missing_pair_policy"] = str(action.spp_missing_pair_policy)
    if isinstance(knobs.get("weighting_profile"), str) and str(knobs["weighting_profile"]).strip():
        guided_overrides["weighting_profile"] = str(knobs["weighting_profile"])
    if isinstance(knobs.get("structure_perturbation_profile"), str) and str(knobs["structure_perturbation_profile"]).strip():
        guided_overrides["structure_perturbation_profile"] = str(knobs["structure_perturbation_profile"])
    if isinstance(knobs.get("template_seed_profile"), str) and str(knobs["template_seed_profile"]).strip():
        guided_overrides["template_seed_profile"] = str(knobs["template_seed_profile"])
    if isinstance(knobs.get("lattice_candidate_profile"), str) and str(knobs["lattice_candidate_profile"]).strip():
        guided_overrides["lattice_candidate_profile"] = str(knobs["lattice_candidate_profile"])
    if isinstance(knobs.get("symmetry_relaxation_profile"), str) and str(knobs["symmetry_relaxation_profile"]).strip():
        guided_overrides["symmetry_relaxation_profile"] = str(knobs["symmetry_relaxation_profile"])
    if isinstance(knobs.get("ordering_perturbation_profile"), str) and str(knobs["ordering_perturbation_profile"]).strip():
        guided_overrides["ordering_perturbation_profile"] = str(knobs["ordering_perturbation_profile"])
    baseline_overrides = {
        "retrieval_mode": knobs["retrieval_policy"],
        "corpus_strategy": knobs["corpus_strategy"],
        "guidance_mode": "none",
        "verification_preset": "benchmark",
        "cell_selection_policy": action.cell_selection_policy,
        "spp_calibration_mode": action.spp_calibration_mode,
    }
    if isinstance(action.retrieval_candidate_k, int):
        baseline_overrides["retrieval_candidate_k"] = int(action.retrieval_candidate_k)
    if isinstance(action.corpus_top_k, int):
        baseline_overrides["corpus_top_k"] = int(action.corpus_top_k)
    if isinstance(action.corpus_strategy_candidates, list) and action.corpus_strategy_candidates:
        baseline_overrides["corpus_strategy_candidates"] = [str(item) for item in action.corpus_strategy_candidates]
    if isinstance(action.corpus_top_k_candidates, list) and action.corpus_top_k_candidates:
        baseline_overrides["corpus_top_k_candidates"] = [int(item) for item in action.corpus_top_k_candidates]
    if isinstance(action.spp_package_variant, str) and action.spp_package_variant:
        baseline_overrides["spp_package_variant"] = str(action.spp_package_variant)
    if isinstance(action.spp_package_alternatives, list) and action.spp_package_alternatives:
        baseline_overrides["spp_package_alternatives"] = [str(item) for item in action.spp_package_alternatives]
    if isinstance(action.spp_package_target, (int, float)):
        baseline_overrides["spp_package_target"] = float(action.spp_package_target)
    if isinstance(action.spp_payload_profile, str) and action.spp_payload_profile:
        baseline_overrides["spp_payload_profile"] = str(action.spp_payload_profile)
    if isinstance(action.spp_guidance_weight, (int, float)):
        baseline_overrides["spp_guidance_weight"] = float(action.spp_guidance_weight)
    if isinstance(action.spp_top_k_breakdown, int):
        baseline_overrides["spp_top_k_breakdown"] = int(action.spp_top_k_breakdown)
    if isinstance(action.spp_pairs_policy, str) and action.spp_pairs_policy:
        baseline_overrides["spp_pairs_policy"] = str(action.spp_pairs_policy)
    if isinstance(action.spp_oob_policy, str) and action.spp_oob_policy:
        baseline_overrides["spp_oob_policy"] = str(action.spp_oob_policy)
    if isinstance(action.spp_missing_pair_policy, str) and action.spp_missing_pair_policy:
        baseline_overrides["spp_missing_pair_policy"] = str(action.spp_missing_pair_policy)
    if isinstance(knobs.get("weighting_profile"), str) and str(knobs["weighting_profile"]).strip():
        baseline_overrides["weighting_profile"] = str(knobs["weighting_profile"])
    if isinstance(knobs.get("structure_perturbation_profile"), str) and str(knobs["structure_perturbation_profile"]).strip():
        baseline_overrides["structure_perturbation_profile"] = str(knobs["structure_perturbation_profile"])
    if isinstance(knobs.get("template_seed_profile"), str) and str(knobs["template_seed_profile"]).strip():
        baseline_overrides["template_seed_profile"] = str(knobs["template_seed_profile"])
    if isinstance(knobs.get("lattice_candidate_profile"), str) and str(knobs["lattice_candidate_profile"]).strip():
        baseline_overrides["lattice_candidate_profile"] = str(knobs["lattice_candidate_profile"])
    if isinstance(knobs.get("symmetry_relaxation_profile"), str) and str(knobs["symmetry_relaxation_profile"]).strip():
        baseline_overrides["symmetry_relaxation_profile"] = str(knobs["symmetry_relaxation_profile"])
    if isinstance(knobs.get("ordering_perturbation_profile"), str) and str(knobs["ordering_perturbation_profile"]).strip():
        baseline_overrides["ordering_perturbation_profile"] = str(knobs["ordering_perturbation_profile"])
    payload = {
        "action_id": action.action_id,
        "baseline_overrides": baseline_overrides,
        "guided_overrides": guided_overrides,
        "query_hints": query_hints,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    compiled = CompiledOptimizationAction(
        action_id=action.action_id,
        action_family=action.action_family,
        compiled_id=f"optcfg-{digest}",
        execution_mode="paired",
        query_suffix=(" " + " ".join(query_hints)).strip(),
        guided_with_spp=action.qlip_guidance_mode != "none",
        baseline_overrides=baseline_overrides,
        guided_overrides=guided_overrides,
    )
    normalized = enforce_compiled_action_semantics(compiled.to_dict())
    return CompiledOptimizationAction(
        action_id=str(normalized["action_id"]),
        action_family=str(normalized["action_family"]),
        compiled_id=str(normalized["compiled_id"]),
        execution_mode=str(normalized["execution_mode"]),
        query_suffix=str(normalized["query_suffix"]),
        guided_with_spp=bool(normalized["guided_with_spp"]),
        baseline_overrides=dict(normalized["baseline_overrides"]),
        guided_overrides=dict(normalized["guided_overrides"]),
    )
