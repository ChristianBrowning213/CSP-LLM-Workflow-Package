from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sok_llm_orchestrator.llm.client import LLMClient
from sok_llm_orchestrator.optimization.action_gate import ActionGateDecision, approve_action
from sok_llm_orchestrator.optimization.action_registry import registry_summary
from sok_llm_orchestrator.optimization.action_schema import OptimizationAction
from sok_llm_orchestrator.optimization.bandit import EpsilonGreedyBandit
from sok_llm_orchestrator.optimization.llm_action_selector import LLMActionProposal, propose_action


@dataclass(slots=True)
class ArbitrationDecision:
    chosen_action: OptimizationAction
    bandit_choice: str
    bandit_ranked: list[str]
    llm_proposal: LLMActionProposal
    gate: ActionGateDecision
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "chosen_action_id": self.chosen_action.action_id,
            "chosen_action_family": self.chosen_action.action_family,
            "bandit_choice": self.bandit_choice,
            "bandit_ranked": list(self.bandit_ranked),
            "llm_proposal": {
                "action_id": self.llm_proposal.action_id,
                "ranked_action_ids": list(self.llm_proposal.ranked_action_ids),
                "rationale": self.llm_proposal.rationale,
                "source": self.llm_proposal.source,
                "raw_text": self.llm_proposal.raw_text,
                "telemetry": dict(self.llm_proposal.telemetry),
            },
            "gate": {
                "accepted": self.gate.accepted,
                "via_fallback": self.gate.via_fallback,
                "reason": self.gate.reason,
                "final_action_id": self.gate.action.action_id,
            },
            "details": dict(self.details),
        }


def _combine_rankings(
    *,
    bandit_ranked: list[str],
    llm_ranked: list[str],
    shortlist: list[str],
) -> list[str]:
    bandit_pos = {aid: idx for idx, aid in enumerate(bandit_ranked)}
    llm_pos = {aid: idx for idx, aid in enumerate(llm_ranked)}
    return sorted(
        shortlist,
        key=lambda aid: (
            llm_pos.get(aid, len(shortlist) + 2) * 2 + bandit_pos.get(aid, len(shortlist) + 1),
            bandit_pos.get(aid, len(shortlist) + 1),
            aid,
        ),
    )


def arbitrate_action(
    *,
    bandit: EpsilonGreedyBandit,
    candidate_action_ids: list[str],
    llm_client: LLMClient | None,
    session_context: dict[str, object],
) -> ArbitrationDecision:
    epsilon_override: float | None = None
    if isinstance(session_context.get("exploration_rate_override"), (int, float)):
        epsilon_override = float(session_context["exploration_rate_override"])
    bandit_choice, meta = bandit.select(candidate_action_ids, epsilon_override=epsilon_override)
    ranked = list(meta.get("ranked", []))
    shortlist_size = 5
    if isinstance(session_context.get("shortlist_size"), int):
        shortlist_size = max(2, int(session_context["shortlist_size"]))
    shortlist = ranked[:shortlist_size] if len(ranked) >= shortlist_size else ranked
    if llm_client is None:
        proposal = LLMActionProposal(
            action_id=bandit_choice,
            rationale="No live LLM configured; using bandit choice.",
            raw_text="",
            source="fallback",
            ranked_action_ids=list(shortlist),
        )
    else:
        proposal = propose_action(
            llm_client=llm_client,
            candidate_action_ids=shortlist,
            registry_summary_payload=registry_summary(),
            session_context={
                **session_context,
                "bandit_ranked": ranked,
                "shortlist_action_ids": shortlist,
            },
        )
    llm_ranked = list(proposal.ranked_action_ids)
    merged_ranked = _combine_rankings(
        bandit_ranked=ranked,
        llm_ranked=llm_ranked,
        shortlist=shortlist,
    )
    gate = approve_action(
        proposal,
        allowed_candidates=shortlist,
        fallback_action_id=merged_ranked[0] if merged_ranked else bandit_choice,
    )
    return ArbitrationDecision(
        chosen_action=gate.action,
        bandit_choice=bandit_choice,
        bandit_ranked=ranked,
        llm_proposal=proposal,
        gate=gate,
        details={
            "bandit_mode": meta.get("mode"),
            "epsilon_used": meta.get("epsilon_used"),
            "shortlist": shortlist,
            "llm_ranked": llm_ranked,
            "combined_ranked": merged_ranked,
        },
    )
