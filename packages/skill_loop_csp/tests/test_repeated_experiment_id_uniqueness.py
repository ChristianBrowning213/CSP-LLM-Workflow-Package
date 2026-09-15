from __future__ import annotations

from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import run_repeated_first_crystal_analysis


def _executor_factory(workdir: Path):  # type: ignore[no-untyped-def]
    def _build(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case["case_id"])

        def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
            action = str(compiled["action_id"])
            structure = workdir / "id_uniqueness_structures" / case_id / f"{action}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}\n", encoding="utf-8")
            return {
                "feasible": True,
                "primary_objective": -1.53,
                "property_estimate": 0.7,
                "objective_audit": {
                    "objective_total": -1.53,
                    "objective_terms": [{"term": "baseline", "value": -1.53}],
                    "baseline_term": -1.53,
                    "spp_term": None,
                    "guidance_terms": [],
                    "solver_summary": {},
                },
                "guided_request_trace": {"effective_overrides": {}, "request_guidance_ids": []},
                "baseline_request_trace": {"effective_overrides": {}, "request_guidance_ids": []},
                "valid_for_learning": True,
                "solver_calls": 1,
                "retrieval_calls": 1,
                "run_reference": {"structure_artifact_path": str(structure)},
            }

        return _run

    return _build


def test_repeated_experiment_id_changes_with_baseline_control_flag(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    cases = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir

    without_baseline = run_repeated_first_crystal_analysis(
        case_file=cases,
        mode="stub",
        workspace=workdir,
        settings=settings,
        repeats=1,
        max_iterations=1,
        action_profile="live_structural",
        include_baseline_control=False,
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    with_baseline = run_repeated_first_crystal_analysis(
        case_file=cases,
        mode="stub",
        workspace=workdir,
        settings=settings,
        repeats=1,
        max_iterations=1,
        action_profile="live_structural",
        include_baseline_control=True,
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    assert without_baseline["repeated_experiment_id"] != with_baseline["repeated_experiment_id"]

