from __future__ import annotations

from sok_llm_orchestrator.optimization.action_compile import compile_action
from sok_llm_orchestrator.optimization.action_registry import get_action, list_registered_actions


def test_spp_exploration_actions_exist_and_compile_to_real_overrides() -> None:
    action_ids = {action.action_id for action in list_registered_actions()}
    assert {"guided_corpus_branch", "guided_payload_probe", "guided_property_push"}.issubset(action_ids)

    compiled = compile_action(get_action("guided_corpus_branch")).to_dict()
    guided = compiled["guided_overrides"]
    assert guided["corpus_strategy"] in {"family_biased", "top_k", "composition_tight"}
    assert isinstance(guided.get("corpus_strategy_candidates"), list) and len(guided["corpus_strategy_candidates"]) >= 2
    assert isinstance(guided.get("corpus_top_k_candidates"), list) and len(guided["corpus_top_k_candidates"]) >= 2
    assert guided.get("spp_package_variant") in {"default", "focus", "broad"}
    assert guided.get("spp_payload_profile") in {"weak", "balanced", "strong"}


def test_guided_payload_probe_compiles_payload_tuning_knobs() -> None:
    compiled = compile_action(get_action("guided_payload_probe")).to_dict()
    guided = compiled["guided_overrides"]
    assert isinstance(guided.get("spp_guidance_weight"), float)
    assert isinstance(guided.get("spp_top_k_breakdown"), int)
    assert guided.get("spp_pairs_policy") in {"task_pairs", "all_available"}
    assert guided.get("spp_oob_policy") in {"zero", "clamp", "max"}
    assert guided.get("spp_missing_pair_policy") in {"zero", "max_global", "error"}

