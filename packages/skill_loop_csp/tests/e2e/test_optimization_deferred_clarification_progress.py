from __future__ import annotations

from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _flat_executor(workdir: Path):  # type: ignore[no-untyped-def]
    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        structure = workdir / "structures" / f"{action}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_{action}\n", encoding="utf-8")
        return {
            "feasible": True,
            "primary_objective": 0.2,
            "property_estimate": 0.2,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"action": action, "structure_artifact_path": str(structure)},
        }

    return _run


def test_deferred_clarification_does_not_immediately_hard_stop(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 5
    settings.optimization_stagnation_window = 2
    settings.optimization_exploration_rate = 0.0
    settings.optimization_allow_midloop_clarification = True

    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_flat_executor(workdir),
    )
    result = engine.start(query="TiO2 optimize high property x", auto_run=True)
    session = engine.get(result.session_id)

    assert len(session.iteration_history) >= 3
    assert session.termination_reason != "midloop_clarification_required"
    assert session.status in {"STOPPED", "COMPLETED", "READY"}
    assert session.clarification_state.get("deferred_questions")
    assert session.clarification_state.get("assumptions_log")

