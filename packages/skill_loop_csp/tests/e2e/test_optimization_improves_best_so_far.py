from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _landscape_executor(path: Path):  # type: ignore[no-untyped-def]
    fixture = json.loads(path.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}

    def _run(query: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action_id = str(compiled["action_id"])
        idx = seen.get(action_id, 0)
        seen[action_id] = idx + 1
        seq = fixture["objectives"].get(action_id, [0.0])
        value = float(seq[min(idx, len(seq) - 1)])
        feasible = bool(fixture["feasible"].get(action_id, True))
        return {
            "feasible": feasible,
            "primary_objective": value,
            "property_estimate": value,
            "valid_for_learning": feasible,
            "solver_calls": 2,
            "retrieval_calls": 2,
            "run_reference": {"query": query, "action_id": action_id},
        }

    return _run


def test_optimization_improves_best_so_far(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    fixture = root / "tests" / "fixtures" / "optimization" / "best_so_far_proof_landscape.json"

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_exploration_rate = 0.0
    settings.optimization_max_iterations = 9
    settings.optimization_stagnation_window = 9
    settings.optimization_allow_midloop_clarification = False

    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_landscape_executor(fixture),
    )
    start = engine.start(query="TiO2 optimize high property x", auto_run=True)
    session = engine.get(start.session_id)
    report_path = start.session_path.parent / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert len(session.iteration_history) >= 7
    initial = float(session.iteration_history[0]["score"])
    final_best = float(session.best_so_far["score"]) if session.best_so_far else -1.0
    assert final_best > initial

    first_six = session.iteration_history[:6]
    assert len({item["action_id"] for item in first_six}) >= 3
    assert all(item["arbitration"]["details"]["bandit_mode"] == "warm_start" for item in first_six)

    late = session.iteration_history[-3:]
    assert any(item["action_family"] == "guided_exploit" for item in late)
    assert any(item["action_id"] == "guided_hybrid_balanced" for item in late)

    assert report["improvement_delta"] is not None and report["improvement_delta"] > 0.0
    assert report["best_so_far_curve"][0] < report["best_so_far_curve"][-1]
    assert report["session_id"] == session.session_id

