from __future__ import annotations

from dataclasses import dataclass

from sok_llm_orchestrator.optimization.action_registry import get_action
from sok_llm_orchestrator.optimization.action_schema import OptimizationAction
from sok_llm_orchestrator.optimization.llm_action_selector import LLMActionProposal


@dataclass(slots=True)
class ActionGateDecision:
    action: OptimizationAction
    accepted: bool
    via_fallback: bool
    reason: str


def approve_action(
    proposal: LLMActionProposal,
    *,
    allowed_candidates: list[str],
    fallback_action_id: str,
) -> ActionGateDecision:
    attempts: list[str] = []
    if proposal.action_id:
        attempts.append(proposal.action_id)
    for ranked_id in proposal.ranked_action_ids:
        if ranked_id not in attempts:
            attempts.append(ranked_id)

    for idx, candidate in enumerate(attempts):
        if candidate not in allowed_candidates:
            continue
        return ActionGateDecision(
            action=get_action(candidate),
            accepted=True,
            via_fallback=False,
            reason="accepted_llm_action" if idx == 0 else "accepted_llm_ranked_candidate",
        )
    return ActionGateDecision(
        action=get_action(fallback_action_id),
        accepted=False,
        via_fallback=True,
        reason="fallback_to_policy_candidate",
    )
