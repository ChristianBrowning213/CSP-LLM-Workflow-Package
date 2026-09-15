from __future__ import annotations

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.budget import BudgetTracker, OptimizationBudgetConfig


def test_budget_from_settings_defaults() -> None:
    settings = Settings.from_sources(None)
    cfg = OptimizationBudgetConfig.from_settings(settings)
    assert cfg.max_iterations > 0
    assert cfg.max_recovery_attempts >= 2
    assert 0.0 <= cfg.exploration_rate <= 1.0


def test_budget_tracker_enforces_limits() -> None:
    cfg = OptimizationBudgetConfig(
        max_iterations=1,
        max_solver_calls=10,
        max_retrieval_calls=10,
        max_failed_iterations=3,
        max_recovery_attempts=5,
        stagnation_window=2,
        exploration_rate=0.2,
        allow_midloop_clarification=True,
    )
    tracker = BudgetTracker(config=cfg)
    assert tracker.can_take_iteration() is None
    tracker.consume(action_family="f", solver_calls=1, retrieval_calls=1, failed=False, recovery_attempt=False)
    assert tracker.can_take_iteration() == "budget_exhausted:max_iterations"


def test_budget_tracker_tracks_recovery_attempts_separately() -> None:
    cfg = OptimizationBudgetConfig(
        max_iterations=4,
        max_solver_calls=10,
        max_retrieval_calls=10,
        max_failed_iterations=3,
        max_recovery_attempts=2,
        stagnation_window=2,
        exploration_rate=0.2,
        allow_midloop_clarification=True,
    )
    tracker = BudgetTracker(config=cfg)
    tracker.consume(action_family="f", solver_calls=2, retrieval_calls=1, failed=True, recovery_attempt=True)
    assert tracker.iterations_used == 1
    assert tracker.solver_calls_used == 2
    assert tracker.failed_iterations_used == 1
    assert tracker.recovery_attempts_used == 1
    assert tracker.remaining_iterations() == 3
    assert tracker.remaining_solver_calls() == 8
    assert tracker.remaining_recovery_attempts() == 1
    assert tracker.recovery_exhausted() is False
