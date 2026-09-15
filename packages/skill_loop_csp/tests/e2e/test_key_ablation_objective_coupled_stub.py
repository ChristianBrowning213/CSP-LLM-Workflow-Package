from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import run_per_key_ablation_experiment


def test_key_ablation_objective_coupled_stub(workdir: Path) -> None:
    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        overrides = dict(compiled.get("guided_overrides", {}))
        retrieval = str(overrides.get("retrieval_mode"))
        value = 0.2 if retrieval == "metadata" else 0.6
        return {
            "feasible": True,
            "primary_objective": value,
            "objective_total": value,
            "objective_terms": [{"term": "baseline", "value": value}],
            "guided_request_trace": {"effective_overrides": overrides},
        }

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_per_key_ablation_experiment(
        query="TiO2 optimize high property x",
        mode="stub",
        workspace=workdir,
        settings=settings,
        dimensions=["retrieval_policy"],
        executor=_executor,
    )
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    row = report["comparisons"][0]
    assert row["classification"] == "objective_coupled"

