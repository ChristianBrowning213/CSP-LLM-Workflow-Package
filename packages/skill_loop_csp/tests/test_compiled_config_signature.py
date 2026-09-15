from __future__ import annotations

from sok_llm_orchestrator.optimization.action_compile import compile_action, compiled_config_signature
from sok_llm_orchestrator.optimization.action_registry import get_action
from sok_llm_orchestrator.optimization.action_schema import OptimizationAction


def test_compiled_config_signature_noop_and_material_change() -> None:
    base = compile_action(get_action("guided_hybrid_balanced")).to_dict()
    same_semantics_different_identity = OptimizationAction(
        action_id="guided_hybrid_balanced_alias",
        action_family="guided_exploit",
        retrieval_policy="hybrid",
        corpus_strategy="top_k",
        spp_calibration_mode="balanced",
        qlip_guidance_mode="guidance_only",
        cell_selection_policy="retrieval_informed",
        retrieval_candidate_k=12,
        corpus_top_k=4,
        corpus_strategy_candidates=["top_k", "family_biased"],
        corpus_top_k_candidates=[3, 4, 6],
        spp_package_variant="default",
        spp_package_alternatives=["default", "focus"],
        spp_package_target=0.9,
        spp_payload_profile="balanced",
        spp_guidance_weight=0.6,
        spp_top_k_breakdown=10,
        spp_pairs_policy="task_pairs",
        spp_oob_policy="max",
        spp_missing_pair_policy="max_global",
        weighting_profile="balanced",
        structure_perturbation_profile="moderate",
        template_seed_profile="polymorph_mix",
        lattice_candidate_profile="expanded",
        symmetry_relaxation_profile="soft",
        ordering_perturbation_profile="site_shuffle",
        rationale="alias",
        expected_risk_reward={"risk": "medium", "reward": "medium"},
    )
    alias = compile_action(same_semantics_different_identity).to_dict()
    changed = compile_action(get_action("guided_property_push")).to_dict()

    assert compiled_config_signature(base) == compiled_config_signature(alias)
    assert (
        compiled_config_signature(base, include_action_identity=True)
        != compiled_config_signature(alias, include_action_identity=True)
    )
    assert compiled_config_signature(base) != compiled_config_signature(changed)
