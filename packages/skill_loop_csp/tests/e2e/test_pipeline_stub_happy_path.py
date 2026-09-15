from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_pipeline_stub_happy_path_and_stable_hashes(workdir: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir]
    settings.allowed_write_roots = [workdir]
    settings.max_cif_count = 10
    settings.max_output_bytes = 1_000_000
    settings.max_runtime_seconds = 120

    run1 = run_csp_pipeline(
        query="TiO2 rutile-like",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
    )
    assert run1.status == "SUCCEEDED"
    required = [
        "manifest.json",
        "tool_call_log.jsonl",
        "artifacts/task_spec.json",
        "artifacts/run_plan.json",
        "artifacts/clarification_decision.json",
        "artifacts/crystal_csp_pack.json",
        "artifacts/retrieval_bundle.json",
        "artifacts/cell_candidates.json",
        "artifacts/spp_corpus_manifest.json",
        "artifacts/spp_run.json",
        "artifacts/spp_package.json",
        "artifacts/spp_artifact_manifest.json",
        "artifacts/spp_calibration_report.json",
        "artifacts/qlip_request.json",
        "artifacts/qlip_validate.json",
        "artifacts/qlip_solve.json",
        "artifacts/verification_report.json",
        "artifacts/novelty_check.json",
    ]
    for rel in required:
        assert (run1.run_dir / rel).exists(), rel

    manifest1 = json.loads((run1.run_dir / "manifest.json").read_text(encoding="utf-8"))
    run2 = run_csp_pipeline(
        query="TiO2 rutile-like",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
    )
    manifest2 = json.loads((run2.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert run1.run_id == run2.run_id
    assert manifest1["artifacts"] == manifest2["artifacts"]
