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
            structure = workdir / "baseline_optional_structures" / case_id / f"{action}.cif"
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


def test_baseline_control_is_opt_in_for_live_structural_profile(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_action_allowlist = []

    without_baseline = run_first_crystal_experiment(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=2,
        action_profile="live_structural",
        include_baseline_control=False,
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    without_payload = json.loads(Path(without_baseline["summary_path"]).read_text(encoding="utf-8"))
    without_profile = without_payload["rows"][0]["profile"]
    assert "baseline_control" not in without_profile["action_allowlist"]
    assert int(without_profile["action_family_limits"]["baseline_control"]) == 0

    with_baseline = run_first_crystal_experiment(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=2,
        action_profile="live_structural",
        include_baseline_control=True,
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    with_payload = json.loads(Path(with_baseline["summary_path"]).read_text(encoding="utf-8"))
    with_profile = with_payload["rows"][0]["profile"]
    assert "baseline_control" in with_profile["action_allowlist"]
    assert with_profile["action_allowlist"][-1] == "baseline_control"
    assert int(with_profile["action_family_limits"]["baseline_control"]) == 1
