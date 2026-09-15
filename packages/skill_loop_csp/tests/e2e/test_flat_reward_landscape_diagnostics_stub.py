from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _flat_executor(workdir: Path):  # type: ignore[no-untyped-def]
    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        structure = workdir / "flat_diag_structures" / f"{action}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_{action}\n", encoding="utf-8")
        return {
            "feasible": True,
            "primary_objective": 0.1,
            "property_estimate": 0.1,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"structure_artifact_path": str(structure)},
        }

    return _run


def test_flat_landscape_report_contains_flatness_diagnostics(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 4
    settings.optimization_exploration_rate = 0.0
    settings.optimization_allow_midloop_clarification = False
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_flat_executor(workdir),
    )
    result = engine.start(query="TiO2 optimize high property x", auto_run=True)
    report = json.loads((result.session_path.parent / "report.json").read_text(encoding="utf-8"))
    diag = report["diagnostics"]
    assert report["iteration_count"] >= 3
    assert diag["flat_objective_flag"] is True
    assert diag["unique_score_value_count"] == 1
    assert report["iteration_effectiveness_trace"]
    assert len(report["iteration_effectiveness_trace"]) == report["iteration_count"]

