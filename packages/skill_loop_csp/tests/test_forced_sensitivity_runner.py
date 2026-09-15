from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import (
    regenerate_forced_sensitivity_report,
    run_forced_sensitivity_experiment,
)


def test_forced_sensitivity_runner_writes_artifacts(workdir: Path) -> None:
    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action_id = str(compiled["action_id"])
        value = 0.2 if action_id == "baseline_control" else 0.4
        return {
            "feasible": True,
            "primary_objective": value,
            "objective_total": value,
            "objective_terms": [{"term": "baseline", "value": value}],
            "guided_request_trace": {"effective_overrides": dict(compiled["guided_overrides"])},
            "run_reference": {"action_id": action_id},
        }

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_forced_sensitivity_experiment(
        query="TiO2 optimize high property x",
        mode="stub",
        workspace=workdir,
        settings=settings,
        action_ids=["baseline_control", "guided_hybrid_balanced"],
        executor=_executor,
    )
    results_path = Path(out["results_path"])
    report_path = Path(out["report_path"])
    assert results_path.exists()
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "forced_sensitivity.report.v1"
    assert len(report["rows"]) == 2
    assert report["diagnostics"]["unique_action_id_count"] == 2
    rebuilt = regenerate_forced_sensitivity_report(results_path)
    assert rebuilt["diagnostics"]["backend_sensitivity_classification"] == report["diagnostics"]["backend_sensitivity_classification"]
