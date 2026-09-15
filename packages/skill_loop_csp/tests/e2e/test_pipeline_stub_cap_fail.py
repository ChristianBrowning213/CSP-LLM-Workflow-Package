from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_pipeline_stub_cap_fail(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir]
    settings.allowed_write_roots = [workdir]
    settings.max_output_bytes = 10
    result = run_csp_pipeline(
        query="TiO2",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
    )
    assert result.status == "FAILED"
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "max_output_bytes" in (manifest["failure_reason"] or "")
