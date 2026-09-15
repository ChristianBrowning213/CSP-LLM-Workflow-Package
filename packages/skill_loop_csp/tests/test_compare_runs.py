from __future__ import annotations

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline
from sok_llm_orchestrator.verification.compare_runs import compare_runs


def test_compare_runs_stub(workdir) -> None:  # type: ignore[no-untyped-def]
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir]
    settings.allowed_write_roots = [workdir]
    left = run_csp_pipeline("TiO2", with_spp=False, mode="stub", workspace=workdir, settings=settings)
    right = run_csp_pipeline("TiO2", with_spp=True, mode="stub", workspace=workdir, settings=settings)
    report = compare_runs(left.run_dir, right.run_dir)
    assert report["schema_version"] == "compare_runs.v1"
    assert report["left_run_id"] == left.run_id
