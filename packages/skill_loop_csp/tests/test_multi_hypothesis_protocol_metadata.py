from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import regenerate_first_crystal_summary, run_first_crystal_experiment


def _executor_factory(_: dict[str, Any]):  # type: ignore[no-untyped-def]
    def _run(__: str, ___: dict[str, Any]) -> dict[str, Any]:
        return {
            "feasible": True,
            "primary_objective": 0.4,
            "property_estimate": 0.4,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {},
        }

    return _run


def test_multi_hypothesis_protocol_metadata_and_regeneration(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "multi_hypothesis_complex_cases.json"

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 3
    settings.optimization_stagnation_window = 2
    settings.optimization_allow_midloop_clarification = False
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
    manifest_path = Path(result["manifest_path"])
    summary_path = Path(result["summary_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    pack_meta = manifest.get("case_pack_metadata", {})
    assert pack_meta.get("pack_id") == "multi_hypothesis_complex_v1"
    assert all(isinstance(case.get("hypotheses"), list) and len(case["hypotheses"]) >= 2 for case in manifest["cases"])
    assert all(int(row.get("hypothesis_count", 0)) >= 2 for row in summary["rows"])

    regenerated = regenerate_first_crystal_summary(manifest_path)
    assert regenerated.get("case_pack_metadata", {}).get("pack_id") == "multi_hypothesis_complex_v1"
    original = {row["case_id"]: row.get("hypothesis_ids", []) for row in summary["rows"]}
    rebuilt = {row["case_id"]: row.get("hypothesis_ids", []) for row in regenerated["rows"]}
    assert rebuilt == original
