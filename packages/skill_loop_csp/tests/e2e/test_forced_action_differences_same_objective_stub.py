from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import run_forced_sensitivity_experiment


def test_forced_action_differences_same_objective_stub(workdir: Path) -> None:
    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        value = 0.33
        return {
            "feasible": True,
            "primary_objective": value,
            "objective_total": value,
            "objective_terms": [{"term": "baseline", "value": value}],
            "guided_request_trace": {"effective_overrides": dict(compiled["guided_overrides"])},
        }

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_forced_sensitivity_experiment(
        query="TiO2 optimize high property x",
        mode="stub",
        workspace=workdir,
        settings=settings,
        action_ids=["baseline_control", "guided_hybrid_balanced", "guided_property_push"],
        executor=_executor,
    )
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    assert report["diagnostics"]["backend_sensitivity_classification"] == "different_action_different_config_same_objective"

