from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import run_repeated_first_crystal_analysis


def _executor_factory(workdir: Path):  # type: ignore[no-untyped-def]
    run_counts: dict[str, int] = {}

    def _build(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case["case_id"])
        run_idx = run_counts.get(case_id, 0)
        run_counts[case_id] = run_idx + 1
        call_idx = {"count": 0}

        def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
            step = int(call_idx["count"])
            call_idx["count"] = step + 1
            action = str(compiled["action_id"])
            guidance = str(compiled.get("guided_overrides", {}).get("guidance_mode", "none"))
            guidance_ids = ["objective.energy_spp"] if guidance != "none" else []
            property_x = 0.52 + (0.05 * run_idx) + (0.04 * step) + (0.19 if guidance_ids else 0.0)
            structure = workdir / "flat_total_property_best_so_far" / case_id / f"{action}_{run_idx}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}_{run_idx}\n", encoding="utf-8")
            return {
                "feasible": True,
                "primary_objective": -1.53,
                "property_estimate": property_x,
                "objective_audit": {
                    "objective_total": -1.53,
                    "objective_terms": [{"term": "baseline", "value": -1.53}] + ([{"term": "spp", "value": -0.2}] if guidance_ids else []),
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


def test_total_flat_but_property_best_so_far_improves_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    case_file = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_repeated_first_crystal_analysis(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        repeats=2,
        max_iterations=3,
        action_profile="live_structural",
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    summary = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    total_view = summary["aggregate"]["view_summary"]["total_objective"]
    property_view = summary["aggregate"]["view_summary"]["property_aware"]
    assert bool(total_view["evidence_of_learning_signal"]) is False
    assert bool(property_view["evidence_of_learning_signal"]) is True
    assert float(property_view["best_so_far_delta"]) > 0.0

