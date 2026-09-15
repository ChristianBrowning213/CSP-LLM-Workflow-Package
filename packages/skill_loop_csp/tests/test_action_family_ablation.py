from __future__ import annotations

import pytest

from sok_llm_orchestrator.optimization.ablation import classify_ablation_change, validate_compiled_action_surface
from sok_llm_orchestrator.optimization.action_compile import compile_action
from sok_llm_orchestrator.optimization.action_schema import OptimizationAction


def _mk_action(
    *,
    retrieval_policy: str = "metadata",
    corpus_strategy: str = "composition_tight",
    spp_calibration_mode: str = "conservative",
    qlip_guidance_mode: str = "none",
    cell_selection_policy: str = "baseline_default",
) -> OptimizationAction:
    return OptimizationAction(
        action_id="base",
        action_family="baseline_control",
        retrieval_policy=retrieval_policy,
        corpus_strategy=corpus_strategy,
        spp_calibration_mode=spp_calibration_mode,
        qlip_guidance_mode=qlip_guidance_mode,
        cell_selection_policy=cell_selection_policy,
        rationale="test",
        expected_risk_reward={"risk": "low", "reward": "low"},
    )


def test_action_family_ablation_categories() -> None:
    base = compile_action(_mk_action()).to_dict()

    retrieval_only = compile_action(_mk_action(retrieval_policy="text")).to_dict()
    assert classify_ablation_change(base, retrieval_only).category == "retrieval-policy-only change"

    corpus_only = compile_action(_mk_action(corpus_strategy="top_k")).to_dict()
    assert classify_ablation_change(base, corpus_only).category == "SPP-corpus-only change"

    weighting_only = compile_action(_mk_action(spp_calibration_mode="balanced")).to_dict()
    assert classify_ablation_change(base, weighting_only).category == "SPP-weighting-only change"

    guidance_only = compile_action(_mk_action(qlip_guidance_mode="guidance_only")).to_dict()
    assert classify_ablation_change(base, guidance_only).category == "QLIP-guidance-only change"

    cell_only = compile_action(_mk_action(cell_selection_policy="retrieval_informed")).to_dict()
    assert classify_ablation_change(base, cell_only).category == "cell-selection-only change"

    bundled = compile_action(
        _mk_action(
            retrieval_policy="hybrid",
            corpus_strategy="top_k",
            spp_calibration_mode="balanced",
            qlip_guidance_mode="guidance_only",
            cell_selection_policy="retrieval_informed",
        )
    ).to_dict()
    assert classify_ablation_change(base, bundled).category == "bundled/full-action change"


def test_compiled_action_surface_rejects_unvalidated_injection() -> None:
    compiled = compile_action(_mk_action()).to_dict()
    compiled["guided_overrides"]["unexpected"] = "bad"
    with pytest.raises(ValueError, match="Unvalidated guided_overrides keys"):
        validate_compiled_action_surface(compiled)

