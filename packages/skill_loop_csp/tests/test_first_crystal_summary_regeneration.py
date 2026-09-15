from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import (
    regenerate_first_crystal_summary,
    run_first_crystal_experiment,
)


def test_first_crystal_summary_regeneration(workdir: Path) -> None:
    calls = {"count": 0}

    def _executor_factory(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case["case_id"])

        def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
            calls["count"] += 1
            action = str(compiled["action_id"])
            structure = workdir / "regen_structures" / case_id / f"{action}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}\n", encoding="utf-8")
            value = 0.8 if action == "guided_hybrid_balanced" else 0.2
            return {
                "feasible": True,
                "primary_objective": value,
                "property_estimate": value,
                "valid_for_learning": True,
                "solver_calls": 2,
                "retrieval_calls": 2,
                "run_reference": {"structure_artifact_path": str(structure)},
            }

        return _run

    root = Path(__file__).resolve().parents[1]
    cases = root / "docs" / "branch" / "benchmarks" / "first_crystal_cases.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 3
    settings.optimization_allow_midloop_clarification = False
    out = run_first_crystal_experiment(
        case_file=cases,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=3,
        executor_factory=_executor_factory,
    )
    manifest_path = Path(out["manifest_path"])
    original = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    before = calls["count"]
    regenerated = regenerate_first_crystal_summary(manifest_path)
    after = calls["count"]

    assert after == before
    by_case_orig = {row["case_id"]: row for row in original["rows"]}
    by_case_regen = {row["case_id"]: row for row in regenerated["rows"]}
    assert set(by_case_orig) == set(by_case_regen)
    for case_id in by_case_orig:
        assert by_case_regen[case_id]["best_action_id"] == by_case_orig[case_id]["best_action_id"]
        assert by_case_regen[case_id]["best_structure_artifact_path"] == by_case_orig[case_id]["best_structure_artifact_path"]
        assert by_case_regen[case_id]["final_best_score"] == by_case_orig[case_id]["final_best_score"]

