from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_pipeline_stub_schema_fail(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir]
    settings.allowed_write_roots = [workdir]
    result = run_csp_pipeline(
        query="TiO2",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
        qlip_request_mutator=lambda request: {**request, "bad_key": 1},
    )
    assert result.status == "FAILED_SCHEMA"
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED_SCHEMA"
