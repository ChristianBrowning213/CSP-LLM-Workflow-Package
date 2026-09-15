from __future__ import annotations

from sok_llm_orchestrator.optimization.backend_sensitivity import (
    extract_objective_audit_from_solve_payload,
    objective_audit_from_execution,
)
from sok_llm_orchestrator.optimization.reward_schema import RewardRecord
from sok_llm_orchestrator.optimization.scoring import score_reward


def test_objective_term_audit_extracts_terms_and_preserves_raw_vs_score() -> None:
    payload = {
        "result": {
            "result": {
                "summary": {"objective_value": -1.53, "solver": "gurobi"},
                "outputs": {
                    "objective_terms": [
                        {"term": "baseline", "value": 2.83},
                        {"term": "SPP", "value": -4.36},
                    ]
                },
            }
        }
    }
    audit = extract_objective_audit_from_solve_payload(payload)
    reward = RewardRecord(
        action_id="guided_hybrid_balanced",
        action_family="guided_exploit",
        primary_objective=audit["objective_total"],
        feasibility=True,
        valid_for_learning=True,
    )
    score = score_reward(reward, objective_direction="maximize")
    assert audit["objective_total"] == -1.53
    assert audit["baseline_term"] == 2.83
    assert audit["spp_term"] == -4.36
    assert score == -1.53
    assert audit["objective_total"] == score


def test_objective_term_audit_from_execution_fallback() -> None:
    audit = objective_audit_from_execution({"primary_objective": 0.42})
    assert audit["objective_total"] == 0.42
    assert audit["objective_terms"]
    assert isinstance(audit["objective_terms_signature"], str)

