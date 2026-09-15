from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import (
    regenerate_repeated_first_crystal_summary,
    run_repeated_first_crystal_analysis,
)


def _executor_factory(workdir: Path):  # type: ignore[no-untyped-def]
    run_count: dict[str, int] = {}

    def _build(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case["case_id"])
        idx = run_count.get(case_id, 0)
        run_count[case_id] = idx + 1

        def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
            action = str(compiled["action_id"])
            guidance_mode = str(compiled.get("guided_overrides", {}).get("guidance_mode", "none"))
            guidance_ids = ["objective.energy_spp"] if guidance_mode != "none" else []
            structure = workdir / "repeated_regen_structures" / case_id / f"{action}_{idx}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}_{idx}\n", encoding="utf-8")
            return {
                "feasible": True,
                "primary_objective": -1.53,
                "property_estimate": 0.6 + (0.1 * idx) + (0.1 if guidance_ids else 0.0),
                "objective_audit": {
                    "objective_total": -1.53,
                    "objective_terms": [{"term": "baseline", "value": -1.53}] + ([{"term": "spp", "value": -0.1}] if guidance_ids else []),
                    "baseline_term": -1.53,
                    "spp_term": (-0.1 if guidance_ids else None),
                    "guidance_terms": [],
                    "solver_summary": {},
                },
                "guided_request_trace": {
                    "effective_overrides": dict(compiled.get("guided_overrides", {})),
                    "request_guidance_ids": guidance_ids,
                },
                "baseline_request_trace": {
                    "effective_overrides": dict(compiled.get("baseline_overrides", {})),
                    "request_guidance_ids": [],
                },
                "valid_for_learning": True,
                "solver_calls": 1,
                "retrieval_calls": 1,
                "run_reference": {"structure_artifact_path": str(structure)},
            }

        return _run

    return _build


def test_regenerated_repeated_analysis_report(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_repeated_first_crystal_analysis(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        repeats=2,
        max_iterations=2,
        action_profile="live_structural",
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    manifest_path = Path(out["manifest_path"])
    original = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    regenerated = regenerate_repeated_first_crystal_summary(manifest_path)
    assert regenerated["schema_version"] == "first_crystal.repeated.summary.v1"
    assert regenerated["aggregate"]["total_runs"] == original["aggregate"]["total_runs"]
    assert regenerated["aggregate"]["total_case_runs"] == original["aggregate"]["total_case_runs"]
    assert regenerated["aggregate"]["guidance_activation_rate"] == original["aggregate"]["guidance_activation_rate"]
    assert regenerated["aggregate"]["property_improved_case_run_rate"] == original["aggregate"]["property_improved_case_run_rate"]
    assert regenerated["per_case_table"] == original["per_case_table"]
