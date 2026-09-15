from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.optimization.reporting import build_optimization_report


def _load_executor(path: Path):  # type: ignore[no-untyped-def]
    fixture = json.loads(path.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}

    def _run(query: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        idx = seen.get(action, 0)
        seen[action] = idx + 1
        values = fixture["objectives"].get(action, [0.0])
        value = float(values[min(idx, len(values) - 1)])
        feasible = bool(fixture.get("feasible", {}).get(action, True))
        return {
            "feasible": feasible,
            "primary_objective": value,
            "property_estimate": value,
            "valid_for_learning": feasible,
            "solver_calls": 2,
            "retrieval_calls": 2,
            "run_reference": {"query": query, "action": action},
        }

    return _run


def test_optimization_loop_e2e_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    fixture = root / "tests" / "fixtures" / "optimization" / "improving_landscape.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_exploration_rate = 1.0
    settings.optimization_max_iterations = 5
    settings.optimization_stagnation_window = 5
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_load_executor(fixture),
    )
    result = engine.start(query="TiO2 optimize high property x", auto_run=True)
    session = engine.get(result.session_id)
    report = build_optimization_report(session)
    assert len(report["iteration_trace"]) >= 2
    assert report["best_so_far"] is not None
    curve = [item for item in report["best_so_far_curve"] if isinstance(item, (int, float))]
    assert curve[-1] >= curve[0]

