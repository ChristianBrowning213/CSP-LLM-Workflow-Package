from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sok_llm_orchestrator.optimization.action_schema import OptimizationAction


RECOVERY_REGIMES = {
    0: "normal_search",
    1: "symmetry_soften_feasibility",
    2: "broadened_retrieval_and_templates",
    3: "candidate_pool_and_action_family_diversification",
    4: "strong_structure_perturbation",
    5: "spp_weighting_and_package_variation",
}


@dataclass(slots=True)
class RecoveryState:
    infeasible_streak: int
    stage: int
    regime: str
    recovery_active: bool


def infeasible_streak(iteration_history: list[dict[str, Any]]) -> int:
    streak = 0
    for row in reversed(iteration_history):
        if bool(row.get("feasible", False)):
            break
        streak += 1
    return streak


def recovery_stage_from_infeasible_streak(*, streak: int, repeated_infeasible_limit: int) -> int:
    if streak <= 0:
        return 0
    max_stage = max(3, min(max(RECOVERY_REGIMES), int(repeated_infeasible_limit) + 2))
    return min(int(streak), int(max_stage))


def recovery_regime_for_stage(stage: int) -> str:
    return RECOVERY_REGIMES.get(int(stage), RECOVERY_REGIMES[max(RECOVERY_REGIMES)])


def derive_recovery_state(
    *,
    iteration_history: list[dict[str, Any]],
    repeated_infeasible_limit: int,
    forced_stage: int = 0,
    prefer_feasibility: bool = False,
) -> RecoveryState:
    streak = infeasible_streak(iteration_history)
    stage = recovery_stage_from_infeasible_streak(
        streak=streak,
        repeated_infeasible_limit=repeated_infeasible_limit,
    )
    stage = max(stage, int(forced_stage))
    if prefer_feasibility:
        stage = max(stage, 1)
    return RecoveryState(
        infeasible_streak=streak,
        stage=stage,
        regime=recovery_regime_for_stage(stage),
        recovery_active=stage > 0,
    )


def recovery_priority(
    *,
    action: OptimizationAction,
    stage: int,
    preserve_strict_symmetry: bool = False,
    broaden_retrieval_preference: bool = False,
) -> int:
    if stage <= 0:
        return 0

    symmetry = str(getattr(action, "symmetry_relaxation_profile", "") or "strict").strip().lower()
    lattice = str(getattr(action, "lattice_candidate_profile", "") or "narrow").strip().lower()
    perturb = str(getattr(action, "structure_perturbation_profile", "") or "minimal").strip().lower()
    corpus = str(getattr(action, "corpus_strategy", "") or "top_k").strip().lower()
    retrieval = str(getattr(action, "retrieval_policy", "") or "metadata").strip().lower()
    weight = str(getattr(action, "weighting_profile", "") or "balanced").strip().lower()
    family = str(getattr(action, "action_family", "") or "").strip().lower()
    ordering = str(getattr(action, "ordering_perturbation_profile", "") or "none").strip().lower()
    seed = str(getattr(action, "template_seed_profile", "") or "canonical").strip().lower()
    package_variant = str(getattr(action, "spp_package_variant", "") or "default").strip().lower()
    guidance_weight = getattr(action, "spp_guidance_weight", None)
    retrieval_k = getattr(action, "retrieval_candidate_k", None)
    corpus_top_k = getattr(action, "corpus_top_k", None)
    top_k_breakdown = getattr(action, "spp_top_k_breakdown", None)

    score = 0
    if preserve_strict_symmetry and symmetry != "strict":
        score -= 20
    if stage >= 1:
        if symmetry in {"soft", "relaxed"}:
            score += 6
        if lattice in {"expanded", "multibasin"}:
            score += 5
        if corpus in {"top_k", "family_biased", "property_biased"}:
            score += 3
        if weight in {"balanced", "guidance_dominant"}:
            score += 2
    if stage >= 2:
        if retrieval in {"hybrid", "text", "fingerprint"}:
            score += 5
        if corpus in {"family_biased", "property_biased"}:
            score += 4
        if isinstance(retrieval_k, int) and int(retrieval_k) >= 16:
            score += 3
        if isinstance(corpus_top_k, int) and int(corpus_top_k) >= 6:
            score += 3
        if symmetry == "relaxed":
            score += 2
    if stage >= 3:
        if family in {"guided_explore", "retrieval_explore", "cell_policy"}:
            score += 6
        if ordering in {"site_shuffle", "cation_swap_bias"}:
            score += 4
        if corpus in {"family_biased", "property_biased"}:
            score += 2
    if stage >= 4:
        if perturb == "template_shuffle":
            score += 8
        elif perturb == "aggressive":
            score += 6
        if seed in {"framework_bias", "ordering_bias", "polymorph_mix"}:
            score += 4
        if lattice == "multibasin":
            score += 3
    if stage >= 5:
        if weight in {"property_push_strong", "experimental_extreme"}:
            score += 5
        elif weight == "guidance_dominant":
            score += 3
        if package_variant in {"focus", "broad"}:
            score += 3
        if isinstance(guidance_weight, (int, float)) and float(guidance_weight) >= 1.0:
            score += 2
        if isinstance(top_k_breakdown, int) and int(top_k_breakdown) >= 16:
            score += 1
    if broaden_retrieval_preference:
        if retrieval in {"hybrid", "text"}:
            score += 2
        if corpus in {"family_biased", "top_k"}:
            score += 2
    return score
