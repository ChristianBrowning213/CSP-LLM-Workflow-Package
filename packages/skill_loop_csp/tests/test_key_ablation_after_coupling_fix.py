from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import run_per_key_ablation_experiment


def test_key_ablation_after_coupling_fix_reports_structural_dimension(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_per_key_ablation_experiment(
        query="TiO2 optimize high property x",
        mode="stub",
        workspace=workdir,
        settings=settings,
    )
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    classes = [str(row.get("propagation_classification")) for row in report.get("comparisons", [])]
    assert any(
        cls in {"propagates_to_request_structure", "propagates_but_no_backend_effect"}
        for cls in classes
    )

