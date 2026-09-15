from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_phase2_external_predictor_provenance_reporting(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]
    run = run_csp_pipeline(
        query="TiO2 external predictor phase2.external.pymatgen_composition_descriptor",
        with_spp=False,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={"guidance_mode": "none"},
    )
    assert run.status == "SUCCEEDED"
    payload = json.loads((run.run_dir / "artifacts" / "external_predictions.json").read_text(encoding="utf-8"))
    prediction = payload["predictions"][0]
    assert prediction["native_phase1_objective"] is False
    assert prediction["value_state"] == "raw"
    assert prediction["provenance"]["predictor_id"] == "phase2.external.pymatgen_composition_descriptor"
    assert prediction["provenance"]["backend"] == "pymatgen"
    assert prediction["provenance"]["calibration_applied"] is False
    assert prediction["calibration"]["calibration_status"] == "uncalibrated_exploratory"
