from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import run_per_key_ablation_experiment


def test_key_ablation_same_request_stub(workdir: Path) -> None:
    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        _ = compiled
        return {
            "feasible": True,
            "primary_objective": 0.2,
            "objective_total": 0.2,
            "objective_terms": [{"term": "baseline", "value": 0.2}],
            "guided_request_trace": {"effective_overrides": {"guidance_mode": "none"}},
        }

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_per_key_ablation_experiment(
        query="TiO2 optimize high property x",
        mode="stub",
        workspace=workdir,
        settings=settings,
        dimensions=["qlip_guidance"],
        executor=_executor,
    )
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    row = report["comparisons"][0]
    assert row["classification"] == "same_effective_request"

