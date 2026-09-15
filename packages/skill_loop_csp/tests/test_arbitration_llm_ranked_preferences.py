from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.optimization.arbitration import arbitrate_action
from sok_llm_orchestrator.optimization.bandit import EpsilonGreedyBandit


class _RankedLLM:
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = messages, tools
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"action_id":"not_legal_here","ranked_action_ids":["guided_hybrid_balanced","baseline_control"],'
                            '"rationale":"guided option should be tried first"}'
                        )
                    }
                }
            ]
        }


def test_arbitration_accepts_llm_ranked_preference_with_gate() -> None:
    bandit = EpsilonGreedyBandit(epsilon=0.0, seed=0)
    decision = arbitrate_action(
        bandit=bandit,
        candidate_action_ids=[
            "baseline_control",
            "guided_hybrid_balanced",
            "retrieval_text_explore",
        ],
        llm_client=_RankedLLM(),  # type: ignore[arg-type]
        session_context={"iteration_count": 2},
    )
    payload = decision.to_dict()
    assert payload["chosen_action_id"] == "guided_hybrid_balanced"
    assert payload["gate"]["accepted"] is True
    assert payload["gate"]["via_fallback"] is False
    assert payload["gate"]["reason"] in {"accepted_llm_action", "accepted_llm_ranked_candidate"}
    assert payload["llm_proposal"]["ranked_action_ids"][0] == "guided_hybrid_balanced"
