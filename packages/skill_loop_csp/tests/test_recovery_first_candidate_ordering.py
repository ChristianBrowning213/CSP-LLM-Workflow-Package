from __future__ import annotations

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.budget import BudgetTracker, OptimizationBudgetConfig
from sok_llm_orchestrator.optimization.action_registry import get_action
from sok_llm_orchestrator.optimization.loop import _ordered_candidates
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession


def _session_with_last_action(*, action_id: str, action_family: str) -> OptimizationSession:
    return OptimizationSession(
        session_id="recovery-order",
        status="READY",
        task_spec={"query_text": "TiO2", "composition_target": "TiO2"},
        clarification_state={"ready": True},
        optimization_plan=None,
        budget_state={"config": {"max_iterations": 5}},
        iteration_history=[
            {
                "iteration_index": 0,
                "action_id": action_id,
                "action_family": action_family,
                "feasible": False,
            }
        ],
        best_so_far={"action_family": action_family, "score": 0.0},
        policy_state={},
    )


def test_recovery_ordering_penalizes_repeating_last_action_and_family() -> None:
    settings = Settings.from_sources(None)
    config = OptimizationBudgetConfig.from_settings(settings)
    budget = BudgetTracker(config=config)
    session = _session_with_last_action(
        action_id="guided_extreme_structure_probe",
        action_family="guided_explore",
    )

    candidates = _ordered_candidates(
        session=session,
        budget=budget,
        enforce_diversity=False,
        structure_stagnation_escalation=False,
        recovery_stage=3,
        clarification_policy={},
    )

    assert candidates
    assert candidates[0] != "guided_extreme_structure_probe"
    chosen = get_action(candidates[0])
    if chosen.action_family == "guided_explore":
        assert chosen.action_id in {"guided_corpus_branch", "retrieval_text_explore"}
    else:
        assert chosen.action_family in {"guided_exploit", "retrieval_explore", "cell_policy"}
