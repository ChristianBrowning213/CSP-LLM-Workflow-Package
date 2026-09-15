from __future__ import annotations

from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _constant_executor(workdir: Path):  # type: ignore[no-untyped-def]
    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        structure = workdir / "iteration_delta_structures" / f"{action}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_{action}\n", encoding="utf-8")
        return {
            "feasible": True,
            "primary_objective": 0.2,
            "property_estimate": 0.2,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"structure_artifact_path": str(structure)},
        }

    return _run


def test_iteration_config_delta_detects_changes(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 2
    settings.optimization_exploration_rate = 0.0
    settings.optimization_allow_midloop_clarification = False
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_constant_executor(workdir),
    )
    result = engine.start(query="TiO2 optimize high property x", auto_run=True)
    session = engine.get(result.session_id)
    assert len(session.iteration_history) == 2
    first = session.iteration_history[0]
    second = session.iteration_history[1]
    assert first["compiled_delta"]["category"] == "initial"
    assert second["compiled_delta"]["category"] != "initial"
    assert second["material_config_change"] is True
    assert second["material_executable_change"] is True

