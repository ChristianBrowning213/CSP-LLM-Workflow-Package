from __future__ import annotations

from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _infeasible_executor(_: Path):  # type: ignore[no-untyped-def]
    def _run(__: str, compiled: dict[str, Any]) -> dict[str, Any]:
        return {
            "feasible": False,
            "primary_objective": None,
            "property_estimate": None,
            "valid_for_learning": False,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"action": str(compiled.get("action_id", ""))},
        }

    return _run


def test_live_like_infeasible_search_prefers_recovery_over_early_stop_stub(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 5
    settings.optimization_stagnation_window = 3
    settings.optimization_max_failed_iterations = 3
    settings.optimization_allow_midloop_clarification = True
    settings.optimization_exploration_rate = 0.0
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_infeasible_executor(workdir),
    )
    result = engine.start(query="TiO2 rutile-like optimize property x", auto_run=True)
    session = engine.get(result.session_id)
    assert session.termination_reason != "midloop_clarification_required"
    assert session.termination_reason != "repeated_blocked_state"
    assert len(session.iteration_history) >= 3
    assert any(int(item.get("recovery_stage", 0)) > 0 for item in session.iteration_history)
