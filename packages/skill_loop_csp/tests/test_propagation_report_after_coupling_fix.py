from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import run_per_key_ablation_experiment


def test_propagation_report_after_coupling_fix(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_per_key_ablation_experiment(
        query="TiO2 optimize high property x",
        mode="stub",
        workspace=workdir,
        settings=settings,
    )
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    diag = report["diagnostics"]
    roles = diag["dimension_role_classification"]
    assert roles["qlip_guidance"] == "backend_structural"
    assert roles["spp_weighting_calibration"] == "metadata_only_demoted"
    summary = diag["override_key_propagation_summary"]
    assert isinstance(summary.get("recommendations"), list) and summary["recommendations"]

