from __future__ import annotations

from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _stagnating_executor(workdir: Path):  # type: ignore[no-untyped-def]
    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action_id = str(compiled["action_id"])
        structure = workdir / "stagnation_structures" / f"{action_id}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_{action_id}\n", encoding="utf-8")
        return {
            "feasible": True,
            "primary_objective": 0.15,
            "property_estimate": 0.15,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"action_id": action_id, "structure_artifact_path": str(structure)},
        }

    return _run


def test_action_diversity_under_stagnation(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 6
    settings.optimization_stagnation_window = 2
    settings.optimization_allow_midloop_clarification = True
    settings.optimization_exploration_rate = 0.0
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_stagnating_executor(workdir),
    )
    result = engine.start(query="TiO2 optimize high property x", auto_run=True)
    session = engine.get(result.session_id)
    families = [str(item.get("action_family")) for item in session.iteration_history]
    assert len(session.iteration_history) >= 4
    assert len(set(families)) >= 2
    assert any(family != "baseline_control" for family in families)

