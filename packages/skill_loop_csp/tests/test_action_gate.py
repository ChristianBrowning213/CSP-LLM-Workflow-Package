from __future__ import annotations

from sok_llm_orchestrator.optimization.action_gate import approve_action
from sok_llm_orchestrator.optimization.llm_action_selector import LLMActionProposal


def test_action_gate_fallback_on_invalid_action() -> None:
    decision = approve_action(
        LLMActionProposal(action_id="not-allowed", rationale="x", raw_text="", source="llm"),
        allowed_candidates=["baseline_control"],
        fallback_action_id="baseline_control",
    )
    assert decision.via_fallback is True
    assert decision.action.action_id == "baseline_control"

