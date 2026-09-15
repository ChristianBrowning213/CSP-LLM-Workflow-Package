from __future__ import annotations

from sok_llm_orchestrator.optimization.arbitration import arbitrate_action
from sok_llm_orchestrator.optimization.bandit import EpsilonGreedyBandit


def test_arbitration_records_bandit_and_llm_roles() -> None:
    bandit = EpsilonGreedyBandit(epsilon=0.0, seed=0)
    decision = arbitrate_action(
        bandit=bandit,
        candidate_action_ids=["baseline_control", "guided_hybrid_balanced"],
        llm_client=None,
        session_context={"iteration_count": 0},
    )
    payload = decision.to_dict()
    assert payload["bandit_choice"] in {"baseline_control", "guided_hybrid_balanced"}
    assert payload["chosen_action_id"] in {"baseline_control", "guided_hybrid_balanced"}
    assert "llm_proposal" in payload

