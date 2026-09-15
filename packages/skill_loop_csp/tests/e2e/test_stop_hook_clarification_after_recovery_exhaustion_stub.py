from __future__ import annotations

from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _always_infeasible(_: Path):  # type: ignore[no-untyped-def]
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


def test_stop_hook_clarification_after_recovery_exhaustion_stub(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 6
    settings.optimization_stagnation_window = 1
    settings.optimization_max_failed_iterations = 1
    settings.optimization_allow_midloop_clarification = True
    settings.optimization_exploration_rate = 0.0
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_always_infeasible(workdir),
    )
    result = engine.start(query="TiO2 optimize property x", auto_run=True)
    session = engine.get(result.session_id)
    assert session.status == "WAITING_CLARIFICATION"
    assert session.termination_reason == "stop_hook_clarification_required"
    pending = session.clarification_state.get("pending_questions", [])
    assert isinstance(pending, list) and pending
    assert "I tried recovery regimes" in str(pending[0])
    evidence = session.clarification_state.get("stop_hook_evidence_summary")
    assert isinstance(evidence, str) and evidence
    assert "recovery_attempt_count=" in evidence
    assert "max_recovery_attempts=" in evidence
    assert "remaining_recovery_attempts=0" in evidence
    budget_state = session.budget_state
    assert budget_state.get("iterations_used") == len(session.iteration_history)
    assert int(budget_state.get("solver_calls_used", 0)) == len(session.iteration_history)
    assert int(budget_state.get("recovery_attempts_used", 0)) > 0
    cfg = budget_state.get("config", {})
    assert int(cfg.get("max_recovery_attempts", 0)) >= int(budget_state.get("recovery_attempts_used", 0))
    invocations = session.policy_state.get("stop_hook_invocations", [])
    assert isinstance(invocations, list) and invocations
