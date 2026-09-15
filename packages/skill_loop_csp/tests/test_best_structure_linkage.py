from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.optimization.reporting import regenerate_report_from_session_artifacts


def test_best_structure_linkage_survives_regeneration(workdir: Path) -> None:
    seen = {"calls": 0}

    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        seen["calls"] += 1
        action = str(compiled["action_id"])
        idx = seen["calls"]
        structure = workdir / "linkage" / f"{action}_{idx}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_{action}_{idx}\n", encoding="utf-8")
        value = 0.2
        if action == "guided_hybrid_balanced":
            value = 0.9
        return {
            "feasible": True,
            "primary_objective": value,
            "property_estimate": value,
            "valid_for_learning": True,
            "solver_calls": 2,
            "retrieval_calls": 2,
            "run_reference": {
                "structure_artifact_path": str(structure),
                "tag": f"{action}:{idx}",
            },
        }

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_exploration_rate = 1.0
    settings.optimization_max_iterations = 4
    settings.optimization_allow_midloop_clarification = False
    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_executor)
    start = engine.start(query="TiO2 optimize high property x", auto_run=True)
    original = json.loads((start.session_path.parent / "report.json").read_text(encoding="utf-8"))
    rebuilt = regenerate_report_from_session_artifacts(start.session_path)

    assert original["best_iteration_index"] == rebuilt["best_iteration_index"]
    assert original["best_action_id"] == rebuilt["best_action_id"]
    assert original["best_action_family"] == rebuilt["best_action_family"]
    assert original["best_structure_artifact_path"] == rebuilt["best_structure_artifact_path"]
    assert original["best_structure_linkage"] == rebuilt["best_structure_linkage"]
    assert isinstance(rebuilt["best_structure_artifact_path"], str)
    assert Path(rebuilt["best_structure_artifact_path"]).exists()

