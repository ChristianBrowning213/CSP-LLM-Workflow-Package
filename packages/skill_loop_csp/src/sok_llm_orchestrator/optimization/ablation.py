from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_TOP_LEVEL_ALLOWED = {
    "action_id",
    "action_family",
    "compiled_id",
    "execution_mode",
    "query_suffix",
    "guided_with_spp",
    "baseline_overrides",
    "guided_overrides",
}
_OVERRIDES_ALLOWED = {
    "retrieval_mode",
    "retrieval_candidate_k",
    "corpus_strategy",
    "corpus_top_k",
    "corpus_strategy_candidates",
    "corpus_top_k_candidates",
    "guidance_mode",
    "spp_package_variant",
    "spp_package_alternatives",
    "spp_package_target",
    "spp_payload_profile",
    "spp_guidance_weight",
    "spp_top_k_breakdown",
    "spp_pairs_policy",
    "spp_oob_policy",
    "spp_missing_pair_policy",
    "weighting_profile",
    "structure_perturbation_profile",
    "template_seed_profile",
    "lattice_candidate_profile",
    "symmetry_relaxation_profile",
    "ordering_perturbation_profile",
    "verification_preset",
    "cell_selection_policy",
    "spp_calibration_mode",
}
_KNOB_KEY_MAP = {
    "retrieval_policy": "retrieval_mode",
    "spp_corpus_strategy": "corpus_strategy",
    "spp_weighting_calibration": "spp_calibration_mode",
    "qlip_guidance": "guidance_mode",
    "cell_selection": "cell_selection_policy",
    "template_seed": "template_seed_profile",
    "lattice_candidate": "lattice_candidate_profile",
    "symmetry_relaxation": "symmetry_relaxation_profile",
    "ordering_perturbation": "ordering_perturbation_profile",
}


@dataclass(slots=True)
class ActionAblationDelta:
    changed_knobs: list[str]
    category: str

    def to_dict(self) -> dict[str, Any]:
        return {"changed_knobs": list(self.changed_knobs), "category": self.category}


def validate_compiled_action_surface(compiled: dict[str, Any]) -> None:
    extra_top = sorted(set(compiled.keys()) - _TOP_LEVEL_ALLOWED)
    if extra_top:
        raise ValueError(f"Unvalidated compiled action top-level keys: {extra_top}")
    for key in ("baseline_overrides", "guided_overrides"):
        overrides = compiled.get(key, {})
        if not isinstance(overrides, dict):
            raise ValueError(f"{key} must be an object.")
        extra = sorted(set(overrides.keys()) - _OVERRIDES_ALLOWED)
        if extra:
            raise ValueError(f"Unvalidated {key} keys: {extra}")


def _knob_state(compiled: dict[str, Any]) -> dict[str, Any]:
    guided = compiled.get("guided_overrides", {})
    if not isinstance(guided, dict):
        return {}
    return {label: guided.get(source_key) for label, source_key in _KNOB_KEY_MAP.items()}


def classify_ablation_change(previous: dict[str, Any] | None, current: dict[str, Any]) -> ActionAblationDelta:
    validate_compiled_action_surface(current)
    if previous is None:
        return ActionAblationDelta(changed_knobs=["initial_action"], category="initial")
    validate_compiled_action_surface(previous)
    prev_state = _knob_state(previous)
    curr_state = _knob_state(current)
    changed = sorted([knob for knob in _KNOB_KEY_MAP if prev_state.get(knob) != curr_state.get(knob)])
    if not changed:
        return ActionAblationDelta(changed_knobs=[], category="no_change")
    if len(changed) == 1:
        mapping = {
            "retrieval_policy": "retrieval-policy-only change",
            "spp_corpus_strategy": "SPP-corpus-only change",
            "spp_weighting_calibration": "SPP-weighting-only change",
            "qlip_guidance": "QLIP-guidance-only change",
            "cell_selection": "cell-selection-only change",
            "template_seed": "template-seed-only change",
            "lattice_candidate": "lattice-candidate-only change",
            "symmetry_relaxation": "symmetry-relaxation-only change",
            "ordering_perturbation": "ordering-perturbation-only change",
        }
        return ActionAblationDelta(changed_knobs=changed, category=mapping[changed[0]])
    return ActionAblationDelta(changed_knobs=changed, category="bundled/full-action change")
