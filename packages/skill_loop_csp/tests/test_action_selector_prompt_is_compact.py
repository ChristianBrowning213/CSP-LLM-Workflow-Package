from __future__ import annotations

import json

from sok_llm_orchestrator.optimization.llm_action_selector import build_compact_action_selector_prompt


def test_action_selector_prompt_is_compact() -> None:
    candidates = ["guided_hybrid_balanced", "guided_property_push", "baseline_control"]
    registry = []
    for i in range(120):
        aid = f"action_{i}"
        registry.append(
            {
                "action_id": aid,
                "family": "guided_explore",
                "retrieval_policy": "hybrid",
                "corpus_strategy": "top_k",
                "qlip_guidance_mode": "guidance_only",
                "weighting_profile": "balanced",
                "structure_perturbation_profile": "moderate",
                "symmetry_relaxation_profile": "soft",
                "risk_reward": {"risk": "m", "reward": "m"},
                "noise_blob": "x" * 500,
            }
        )
    registry.extend(
        [
            {
                "action_id": "guided_hybrid_balanced",
                "family": "guided_exploit",
                "retrieval_policy": "hybrid",
                "corpus_strategy": "top_k",
                "qlip_guidance_mode": "guidance_only",
                "weighting_profile": "balanced",
                "structure_perturbation_profile": "moderate",
                "symmetry_relaxation_profile": "soft",
                "risk_reward": {"risk": "m", "reward": "m"},
            },
            {
                "action_id": "guided_property_push",
                "family": "guided_exploit",
                "retrieval_policy": "hybrid",
                "corpus_strategy": "property_biased",
                "qlip_guidance_mode": "budget_constraint",
                "weighting_profile": "property_push_strong",
                "structure_perturbation_profile": "aggressive",
                "symmetry_relaxation_profile": "soft",
                "risk_reward": {"risk": "h", "reward": "h"},
            },
            {
                "action_id": "baseline_control",
                "family": "baseline_control",
                "retrieval_policy": "metadata",
                "corpus_strategy": "composition_tight",
                "qlip_guidance_mode": "none",
                "weighting_profile": "base_dominant",
                "structure_perturbation_profile": "minimal",
                "symmetry_relaxation_profile": "strict",
                "risk_reward": {"risk": "l", "reward": "l"},
            },
        ]
    )
    session_context = {
        "iteration_count": 42,
        "task_spec": {
            "query_text": "BaTiO3 optimize property x",
            "composition_target": "BaTiO3",
            "property_bias": "property_x",
            "solve_mode": "optimize",
            "symmetry_request": {"hardness": "soft"},
        },
        "recovery_stage": 2,
        "recovery_regime": "broadened_retrieval_and_templates",
        "infeasible_streak": 3,
        "no_improve_streak": 5,
        "structure_static_streak": 4,
        "recent_iterations": [{"blob": "y" * 4000} for _ in range(20)],
        "bandit_ranked": [f"action_{i}" for i in range(100)],
    }
    prompt = build_compact_action_selector_prompt(
        candidate_action_ids=candidates,
        registry_summary_payload=registry,
        session_context=session_context,
    )
    raw = json.dumps(prompt, separators=(",", ":"), sort_keys=True)
    assert len(raw) < 5000
    assert "noise_blob" not in raw
    assert "blob" not in raw
    assert len(prompt.get("candidates", [])) == 3
