from __future__ import annotations

from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _always_infeasible_executor(_: Path):  # type: ignore[no-untyped-def]
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


def test_repeated_infeasibility_triggers_recovery_before_clarification(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 4
    settings.optimization_stagnation_window = 3
    settings.optimization_max_failed_iterations = 3
    settings.optimization_allow_midloop_clarification = True
    settings.optimization_exploration_rate = 0.0
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_always_infeasible_executor(workdir),
    )
    result = engine.start(query="TiO2 rutile-like optimize property x", auto_run=True)
    session = engine.get(result.session_id)
    recovery = session.policy_state.get("recovery_state", {})
    assert session.termination_reason != "midloop_clarification_required"
    assert session.termination_reason != "stop_hook_clarification_required"
    assert isinstance(recovery, dict)
    assert int(recovery.get("attempt_count", 0)) > 0
    assert len(list(recovery.get("regimes_tried", []))) >= 2
    assert int(session.iteration_history[1].get("recovery_stage", 0)) >= 1
    assert any(int(item.get("recovery_stage", 0)) > 0 for item in session.iteration_history if isinstance(item, dict))
    assert not session.policy_state.get("stop_hook_invocations")
    report = (result.session_path.parent / "report.json").read_text(encoding="utf-8")
    assert "recovery_regimes_tried" in report
    assert "stop_hook_invocations" in report
