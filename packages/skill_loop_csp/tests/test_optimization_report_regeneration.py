from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.optimization.reporting import regenerate_report_from_session_artifacts


def test_optimization_report_regeneration_from_artifacts_only(workdir: Path) -> None:
    calls = {"count": 0}

    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        calls["count"] += 1
        action = str(compiled["action_id"])
        base = 0.1
        if action == "guided_hybrid_balanced":
            base = 0.6
        return {
            "feasible": True,
            "primary_objective": base,
            "property_estimate": base,
            "valid_for_learning": True,
            "solver_calls": 2,
            "retrieval_calls": 2,
            "run_reference": {"action": action},
        }

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_exploration_rate = 0.0
    settings.optimization_max_iterations = 7
    settings.optimization_stagnation_window = 7
    settings.optimization_allow_midloop_clarification = False
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_executor,
    )
    start = engine.start(query="TiO2 optimize high property x", auto_run=True)
    original = json.loads((start.session_path.parent / "report.json").read_text(encoding="utf-8"))
    before = calls["count"]
    regenerated = regenerate_report_from_session_artifacts(start.session_path)
    after = calls["count"]

    assert after == before
    assert regenerated["best_so_far_curve"] == original["best_so_far_curve"]
    assert regenerated["termination_reason"] == original["termination_reason"]
    assert regenerated["iteration_count"] == original["iteration_count"]
    assert regenerated["best_so_far"] == original["best_so_far"]

