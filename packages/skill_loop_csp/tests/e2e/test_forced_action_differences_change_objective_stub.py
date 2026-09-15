from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import run_forced_sensitivity_experiment


def test_forced_action_differences_change_objective_stub(workdir: Path) -> None:
    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action_id = str(compiled["action_id"])
        value = 0.2 if action_id == "baseline_control" else 0.55
        terms = [{"term": "baseline", "value": value}]
        return {
            "feasible": True,
            "primary_objective": value,
            "objective_total": value,
            "objective_terms": terms,
            "guided_request_trace": {"effective_overrides": dict(compiled["guided_overrides"])},
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
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    assert report["diagnostics"]["backend_sensitivity_classification"] == "different_action_different_config_different_objective"

