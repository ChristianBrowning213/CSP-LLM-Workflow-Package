from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import run_first_crystal_experiment


def _executor_factory(workdir: Path):  # type: ignore[no-untyped-def]
    def _build(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case["case_id"])

        def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
            action = str(compiled["action_id"])
            value = 0.2 if action == "baseline_control" else 0.45
            structure = workdir / "sensitivity_summary_structures" / case_id / f"{action}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}\n", encoding="utf-8")
            return {
                "feasible": True,
                "primary_objective": value,
                "objective_total": value,
                "objective_terms": [{"term": "baseline", "value": value}],
                "guided_request_trace": {"effective_overrides": dict(compiled["guided_overrides"])},
                "run_reference": {"structure_artifact_path": str(structure)},
            }

        return _run

    return _build


def test_first_crystal_summary_exposes_sensitivity_fields(workdir: Path) -> None:
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
        executor_factory=_executor_factory(workdir),
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    row = summary["rows"][0]
    assert "objective_total_diversity_count" in row
    assert "objective_term_signature_diversity_count" in row
    assert "backend_sensitivity_classification" in row
    assert "dimension_sensitivity_summary" in row

