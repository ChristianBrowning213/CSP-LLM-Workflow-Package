from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _fixture_executor(path: Path):  # type: ignore[no-untyped-def]
    payload = json.loads(path.read_text(encoding="utf-8"))
    counters: dict[str, int] = {}

    def _run(query: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action_id = str(compiled["action_id"])
        seq = payload["objectives"].get(action_id, [0.0])
        idx = counters.get(action_id, 0)
        counters[action_id] = idx + 1
        value = float(seq[min(idx, len(seq) - 1)])
        feasible = bool(payload.get("feasible", {}).get(action_id, True))
        return {
            "feasible": feasible,
            "primary_objective": value,
            "property_estimate": value,
            "valid_for_learning": feasible,
            "solver_calls": 2,
            "retrieval_calls": 2,
            "run_reference": {"query": query, "action_id": action_id, "fixture": str(path)},
        }

    return _run


def test_optimization_loop_improves_under_fixture(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    fixture = root / "tests" / "fixtures" / "optimization" / "improving_landscape.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 6
    settings.optimization_exploration_rate = 1.0
    settings.optimization_stagnation_window = 5
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_fixture_executor(fixture),
    )
    result = engine.start(query="TiO2 optimize high property x", auto_run=True)
    session = engine.get(result.session_id)
    assert len(session.iteration_history) >= 2
    first = session.iteration_history[0]["score"]
    assert session.best_so_far is not None
    assert session.best_so_far["score"] >= first

