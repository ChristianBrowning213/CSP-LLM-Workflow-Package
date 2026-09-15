from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _stagnating_executor(path: Path):  # type: ignore[no-untyped-def]
    fixture = json.loads(path.read_text(encoding="utf-8"))

    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        value = float(fixture["objectives"].get(action, [0.2])[0])
        return {
            "feasible": True,
            "primary_objective": value,
            "property_estimate": value,
            "valid_for_learning": True,
            "solver_calls": 2,
            "retrieval_calls": 2,
            "run_reference": {"action": action},
        }

    return _run


def test_stagnation_triggers_midloop_clarification(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    fixture = root / "tests" / "fixtures" / "optimization" / "stagnating_landscape.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_exploration_rate = 1.0
    settings.optimization_stagnation_window = 3
    settings.optimization_max_iterations = 6
    settings.optimization_allow_midloop_clarification = True
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_stagnating_executor(fixture),
    )
    result = engine.start(query="TiO2 optimize high property x", auto_run=True)
    session = engine.get(result.session_id)
    assert len(session.iteration_history) >= 3
    assert session.status in {"STOPPED", "COMPLETED", "READY"}
    assert session.termination_reason != "midloop_clarification_required"
    assert session.clarification_state.get("deferred_questions")
    assert session.clarification_state.get("assumptions_log")
