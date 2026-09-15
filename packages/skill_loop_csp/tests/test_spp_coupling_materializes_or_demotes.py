from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import run_per_key_ablation_experiment


def test_spp_coupling_materializes_or_demotes(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_per_key_ablation_experiment(
        query="TiO2 optimize high property x",
        mode="stub",
        workspace=workdir,
        settings=settings,
        dimensions=["spp_weighting_calibration", "qlip_guidance"],
    )
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    roles = report["diagnostics"]["dimension_role_classification"]
    assert roles["spp_weighting_calibration"] == "metadata_only_demoted"
    assert roles["qlip_guidance"] == "backend_structural"

