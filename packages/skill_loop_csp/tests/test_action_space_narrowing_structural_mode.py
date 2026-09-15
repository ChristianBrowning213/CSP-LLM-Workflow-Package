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
            guidance_mode = str(compiled.get("guided_overrides", {}).get("guidance_mode", "none"))
            structure = workdir / "structural_mode_structures" / case_id / f"{action}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}\n", encoding="utf-8")
            guidance_ids = ["objective.energy_spp"] if guidance_mode != "none" else []
            terms = [{"term": "baseline", "value": -1.53}]
            if guidance_ids:
                terms.append({"term": "spp", "value": -0.25})
            return {
                "feasible": True,
                "primary_objective": -1.53,
                "property_estimate": 0.72 if guidance_ids else 0.61,
                "objective_audit": {
                    "objective_total": -1.53,
                    "objective_terms": terms,
                    "baseline_term": -1.53,
                    "spp_term": (-0.25 if guidance_ids else None),
                    "guidance_terms": [],
                    "solver_summary": {"property_x": (0.72 if guidance_ids else 0.61)},
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


def test_action_space_narrowing_structural_mode(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    cases = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_first_crystal_experiment(
        case_file=cases,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=3,
        action_profile="live_structural",
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    summary = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    row = summary["rows"][0]
    profile = row["profile"]
    assert profile["name"] == "live_structural"
    assert int(profile["action_family_limits"]["retrieval_explore"]) == 0
    assert int(profile["action_family_limits"]["cell_policy"]) == 0
    assert int(profile["action_family_limits"]["guided_exploit"]) >= 1

    session_path = Path(str(row["session_path"]))
    report = json.loads((session_path.parent / "report.json").read_text(encoding="utf-8"))
    families = {
        str(item.get("action_family"))
        for item in report.get("iteration_trace", [])
        if isinstance(item, dict) and isinstance(item.get("action_family"), str)
    }
    assert families.issubset({"baseline_control", "guided_exploit"})
