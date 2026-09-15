from __future__ import annotations

import json

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.paired_run import run_paired_baseline_guided
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_branch_smoke_stub(workdir, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir]
    settings.allowed_write_roots = [workdir]

    baseline = run_csp_pipeline("TiO2 branch smoke", with_spp=False, mode="stub", workspace=workdir, settings=settings)
    guided = run_csp_pipeline("TiO2 branch smoke", with_spp=True, mode="stub", workspace=workdir, settings=settings)
    paired = run_paired_baseline_guided("TiO2 branch smoke", mode="stub", workspace=workdir, settings=settings)

    assert baseline.status == "SUCCEEDED"
    assert guided.status == "SUCCEEDED"
    compare = json.loads(paired.report_path.read_text(encoding="utf-8"))
    assert compare["baseline_run_id"] == baseline.run_id
    assert compare["guided_run_id"] == guided.run_id
