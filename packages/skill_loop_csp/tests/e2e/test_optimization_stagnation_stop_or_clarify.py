from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _flat_executor(path: Path):  # type: ignore[no-untyped-def]
    fixture = json.loads(path.read_text(encoding="utf-8"))

    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        value = float(fixture["objectives"].get(action, [0.0])[0])
        feasible = bool(fixture["feasible"].get(action, True))
        return {
            "feasible": feasible,
            "primary_objective": value,
            "property_estimate": value,
            "valid_for_learning": feasible,
            "solver_calls": 2,
            "retrieval_calls": 2,
            "run_reference": {"action": action},
        }

    return _run


def test_optimization_stagnation_stop_or_clarify(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    fixture = root / "tests" / "fixtures" / "optimization" / "flat_blocked_landscape.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_exploration_rate = 0.0
    settings.optimization_stagnation_window = 3
    settings.optimization_max_iterations = 10
    settings.optimization_allow_midloop_clarification = True
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_flat_executor(fixture),
    )
    start = engine.start(query="TiO2 optimize high property x", auto_run=True)
    session = engine.get(start.session_id)
    report = json.loads((start.session_path.parent / "report.json").read_text(encoding="utf-8"))

    assert session.status in {"WAITING_CLARIFICATION", "STOPPED"}
    if session.status == "WAITING_CLARIFICATION":
        assert session.blocked_state is not None
        assert session.blocked_state["reason"] in {"stagnation", "repeated_infeasibility", "action_family_ambiguity"}
    else:
        assert session.termination_reason is not None
    assert report["failure_taxonomy"]["primary_category"] in {
        "stagnation",
        "blocked-clarification-needed",
        "budget_exhaustion",
    }

