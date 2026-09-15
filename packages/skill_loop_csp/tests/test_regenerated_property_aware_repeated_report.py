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
    run_index_by_case: dict[str, int] = {}

    def _build(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case["case_id"])
        run_index = run_index_by_case.get(case_id, 0)
        run_index_by_case[case_id] = run_index + 1
        call_idx = {"count": 0}

        def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
            step = int(call_idx["count"])
            call_idx["count"] = step + 1
            action = str(compiled["action_id"])
            guidance_mode = str(compiled.get("guided_overrides", {}).get("guidance_mode", "none"))
            guidance_ids = ["objective.energy_spp"] if guidance_mode != "none" else []
            property_x = 0.56 + (0.06 * run_index) + (0.03 * step) + (0.18 if guidance_ids else 0.0)
            structure = workdir / "regen_property_aware_structures" / case_id / f"{action}_{run_index}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}_{run_index}\n", encoding="utf-8")
            terms = [{"term": "baseline", "value": -1.53}]
            if guidance_ids:
                terms.append({"term": "spp", "value": -0.2})
            return {
                "feasible": True,
                "primary_objective": -1.53,
                "property_estimate": property_x,
                "objective_audit": {
                    "objective_total": -1.53,
                    "objective_terms": terms,
                    "baseline_term": -1.53,
                    "spp_term": (-0.2 if guidance_ids else None),
                    "guidance_terms": [],
                    "solver_summary": {"property_x": property_x},
                },
                "guided_request_trace": {
                    "effective_overrides": dict(compiled.get("guided_overrides", {})),
                    "request_guidance_ids": guidance_ids,
                },
                "baseline_request_trace": {"effective_overrides": {}, "request_guidance_ids": []},
                "valid_for_learning": True,
                "solver_calls": 1,
                "retrieval_calls": 1,
                "run_reference": {"structure_artifact_path": str(structure)},
            }

        return _run

    return _build


def test_regenerated_property_aware_repeated_report_preserves_view_summary(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    cases = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_repeated_first_crystal_analysis(
        case_file=cases,
        mode="stub",
        workspace=workdir,
        settings=settings,
        repeats=2,
        max_iterations=3,
        action_profile="live_structural",
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    manifest_path = Path(out["manifest_path"])
    original = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    regenerated = regenerate_repeated_first_crystal_summary(manifest_path)
    assert (
        regenerated["aggregate"]["view_summary"]["property_aware"]["evidence_of_learning_signal"]
        == original["aggregate"]["view_summary"]["property_aware"]["evidence_of_learning_signal"]
    )
    assert (
        regenerated["aggregate"]["view_summary"]["total_objective"]["evidence_of_learning_signal"]
        == original["aggregate"]["view_summary"]["total_objective"]["evidence_of_learning_signal"]
    )
    assert regenerated["aggregate"]["preferred_variant_by_run"] == original["aggregate"]["preferred_variant_by_run"]

