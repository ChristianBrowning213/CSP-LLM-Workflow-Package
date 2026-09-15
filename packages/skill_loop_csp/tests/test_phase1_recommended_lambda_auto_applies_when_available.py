from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_phase1_recommended_lambda_auto_applies_when_available(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]

    run = run_csp_pipeline(
        query="TiO2 rutile-like optimize",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
    )

    calibration = json.loads((run.run_dir / "artifacts" / "spp_calibration_report.json").read_text(encoding="utf-8"))
    lambda_resolution = json.loads((run.run_dir / "artifacts" / "spp_lambda_resolution.json").read_text(encoding="utf-8"))
    request = json.loads((run.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))

    expected = float(calibration["recommended_weight"])
    assert lambda_resolution["spp_lambda_source"] == "calibration_recommended"
    assert lambda_resolution["spp_lambda_recommended_available"] is True
    assert float(lambda_resolution["spp_lambda_value"]) == expected
    assert float(request["guidance"][0]["params"]["lambda_override"]) == expected
