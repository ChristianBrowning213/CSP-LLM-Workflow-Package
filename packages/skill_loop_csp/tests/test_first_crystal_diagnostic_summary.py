from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import run_first_crystal_experiment


def _flat_executor_factory(workdir: Path):  # type: ignore[no-untyped-def]
    def _build(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case["case_id"])

        def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
            action = str(compiled["action_id"])
            structure = workdir / "first_crystal_diag_structures" / case_id / f"{action}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}\n", encoding="utf-8")
            return {
                "feasible": True,
                "primary_objective": 0.2,
                "property_estimate": 0.2,
                "valid_for_learning": True,
                "solver_calls": 1,
                "retrieval_calls": 1,
                "run_reference": {"case_id": case_id, "structure_artifact_path": str(structure)},
            }

        return _run

    return _build


def test_first_crystal_summary_includes_flatness_diagnostics(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 3
    settings.optimization_allow_midloop_clarification = False
    result = run_first_crystal_experiment(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=3,
        executor_factory=_flat_executor_factory(workdir),
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    row = summary["rows"][0]
    assert "action_diversity_count" in row
    assert "compiled_config_diversity_count" in row
    assert "score_diversity_count" in row
    assert "flat_objective_flag" in row
    assert "likely_flatness_reason" in row
    assert "diagnostic_recommendation" in row
    assert "flat_cases" in summary["aggregate"]
    assert "iteration_zero_best_cases" in summary["aggregate"]

