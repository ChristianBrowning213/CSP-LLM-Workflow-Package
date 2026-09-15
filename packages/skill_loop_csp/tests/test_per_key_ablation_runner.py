from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import (
    regenerate_per_key_ablation_report,
    run_per_key_ablation_experiment,
)


def test_per_key_ablation_runner_emits_baseline_and_variant_rows(workdir: Path) -> None:
    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        overrides = dict(compiled.get("guided_overrides", {}))
        value = 0.3
        if overrides.get("retrieval_mode") != "metadata":
            value += 0.1
        if overrides.get("guidance_mode") != "none":
            value += 0.05
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
        dimensions=["retrieval_policy", "qlip_guidance"],
        executor=_executor,
    )
    results_path = Path(out["results_path"])
    report_path = Path(out["report_path"])
    assert results_path.exists()
    assert report_path.exists()

    raw = json.loads(results_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "key_ablation.run.v1"
    assert report["schema_version"] == "key_ablation.report.v1"
    assert isinstance(raw["baseline"], dict)
    assert len(raw["comparisons"]) == 2
    first = raw["comparisons"][0]
    assert "diff_summary" in first
    assert "classification" in first
    rebuilt = regenerate_per_key_ablation_report(results_path)
    assert rebuilt["diagnostics"]["comparison_count"] == report["diagnostics"]["comparison_count"]

