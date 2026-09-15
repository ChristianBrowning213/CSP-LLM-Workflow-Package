from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_phase1_linear_property_proxy_end_to_end_strict_runs_truthfully(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]

    run = run_csp_pipeline(
        query="TiO2 prioritize high linear property",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
        strict_phase1_benchmark_mode=True,
    )
    assert run.status == "SUCCEEDED"
    request = json.loads((run.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    assert request["problem"]["objective"]["type"] == "linear_property"
    assert request["problem"]["objective"]["linear_property"]["kind"] == "occupancy_linear"
