from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import regenerate_first_crystal_summary, run_first_crystal_experiment


def _executor_factory(case: dict[str, Any]):  # type: ignore[no-untyped-def]
    case_id = str(case["case_id"])

    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        value = 0.6 if action.startswith("guided_") else 0.3
        return {
            "feasible": True,
            "primary_objective": value,
            "property_estimate": value,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"case_id": case_id, "action": action},
        }

    return _run


def test_first_crystal_metadata_preserves_hypotheses(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "multi_hypothesis_complex_cases.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 2
    settings.optimization_allow_midloop_clarification = False

    result = run_first_crystal_experiment(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=2,
        executor_factory=_executor_factory,
    )

    manifest_path = Path(result["manifest_path"])
    summary_path = Path(result["summary_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert all(isinstance(item.get("hypotheses"), list) and len(item["hypotheses"]) >= 2 for item in manifest["cases"])
    assert all(isinstance(row.get("hypothesis_ids"), list) and len(row["hypothesis_ids"]) >= 2 for row in summary["rows"])
    assert all(int(row.get("hypothesis_count", 0)) >= 2 for row in summary["rows"])

    regenerated = regenerate_first_crystal_summary(manifest_path)
    original_ids = {row["case_id"]: row.get("hypothesis_ids", []) for row in summary["rows"]}
    regen_ids = {row["case_id"]: row.get("hypothesis_ids", []) for row in regenerated["rows"]}
    assert regen_ids == original_ids
