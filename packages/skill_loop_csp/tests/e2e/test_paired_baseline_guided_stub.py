from __future__ import annotations

import json

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.paired_run import run_paired_baseline_guided


def test_paired_baseline_guided_stub(workdir, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir]
    settings.allowed_write_roots = [workdir]
    result = run_paired_baseline_guided(
        query="TiO2 rutile-like prioritize high property X",
        mode="stub",
        workspace=workdir,
        settings=settings,
    )
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["baseline_status"] == "SUCCEEDED"
    assert report["guided_status"] == "SUCCEEDED"
    assert report["property_key"] == "property_x"
    assert report["property_assertion_pass"] is True
