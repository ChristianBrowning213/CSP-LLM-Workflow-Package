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
            structure = workdir / "live_profile_structures" / case_id / f"{action}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}\n", encoding="utf-8")
            return {
                "feasible": True,
                "primary_objective": 0.3 if action == "guided_hybrid_balanced" else 0.2,
                "property_estimate": 0.0,
                "valid_for_learning": True,
                "solver_calls": 1,
                "retrieval_calls": 1,
                "run_reference": {"structure_artifact_path": str(structure)},
            }

        return _run

    return _build


def test_live_assisted_profile_serializes_in_manifest_and_rows(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    cases = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_exploration_rate = 0.05
    settings.optimization_stagnation_window = 2

    result = run_first_crystal_experiment(
        case_file=cases,
        mode="live",
        workspace=workdir,
        settings=settings,
        max_iterations=2,
        action_profile="live_assisted",
        executor_factory=_executor_factory(workdir),
    )
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert manifest["action_profile"] == "live_assisted"
    assert summary["action_profile"] == "live_assisted"
    assert summary["rows"]
    profile = summary["rows"][0]["profile"]
    assert profile["name"] == "live_assisted"
    assert float(profile["exploration_rate"]) >= 0.35
    assert int(profile["stagnation_window"]) >= 4

