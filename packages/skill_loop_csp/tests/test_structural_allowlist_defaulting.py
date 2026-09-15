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
            structure = workdir / "structural_allowlist_defaulting" / case_id / f"{action}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}\n", encoding="utf-8")
            guidance_mode = str(compiled.get("guided_overrides", {}).get("guidance_mode", "none"))
            guidance_ids = ["objective.energy_spp"] if guidance_mode != "none" else []
            return {
                "feasible": True,
                "primary_objective": -1.53,
                "property_estimate": 0.78 if guidance_ids else 0.61,
                "objective_audit": {
                    "objective_total": -1.53,
                    "objective_terms": [{"term": "baseline", "value": -1.53}],
                    "baseline_term": -1.53,
                    "spp_term": (-4.36 if guidance_ids else None),
                    "guidance_terms": [],
                    "solver_summary": {},
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


def test_structural_allowlist_defaults_to_productive_variants(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_action_allowlist = []
    out = run_first_crystal_experiment(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=2,
        action_profile="live_structural",
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    summary = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    profile = summary["rows"][0]["profile"]
    assert profile["action_allowlist"] == ["guided_property_push", "guided_hybrid_balanced"]
    assert "baseline_control" not in profile["action_allowlist"]

    session_path = Path(str(summary["rows"][0]["session_path"]))
    report = json.loads((session_path.parent / "report.json").read_text(encoding="utf-8"))
    first_action = report.get("iteration_trace", [{}])[0].get("action_id")
    assert first_action == "guided_property_push"
