from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import regenerate_first_crystal_summary, run_first_crystal_experiment


def _executor_factory(_: dict[str, Any]):  # type: ignore[no-untyped-def]
    def _run(__: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action_id = str(compiled["action_id"])
        score = 0.25 if action_id == "baseline_control" else 0.45
        return {
            "feasible": True,
            "primary_objective": score,
            "property_estimate": score,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"action_id": action_id},
        }

    return _run


def test_first_crystal_metadata_preserves_adversarial_fields(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "adversarial_hard_crystal_cases.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 3
    settings.optimization_allow_midloop_clarification = False
    settings.optimization_stagnation_window = 2
    settings.optimization_exploration_rate = 0.0

    result = run_first_crystal_experiment(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=3,
        action_profile="multi_hypothesis_branching",
        analysis_metric_view="property_x",
        executor_factory=_executor_factory,
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary.get("case_pack_metadata", {}).get("pack_id") == "adversarial_hard_crystal_v1"
    rows = summary["rows"]
    assert len(rows) == 5
    assert all(isinstance(row.get("challenge_class"), str) for row in rows)
    assert all(isinstance(row.get("suggested_corpus_bias"), str) and row["suggested_corpus_bias"] for row in rows)
    assert all(
        isinstance(row.get("suggested_perturbation_bias"), str) and row["suggested_perturbation_bias"] for row in rows
    )
    assert all(isinstance(row.get("hypotheses"), list) and len(row["hypotheses"]) >= 2 for row in rows)
    assert all(isinstance(row.get("hypothesis_ids"), list) and len(row["hypothesis_ids"]) >= 2 for row in rows)

    regenerated = regenerate_first_crystal_summary(Path(result["manifest_path"]))
    original = {row["case_id"]: row.get("hypothesis_ids", []) for row in rows}
    rebuilt = {row["case_id"]: row.get("hypothesis_ids", []) for row in regenerated.get("rows", [])}
    assert rebuilt == original
