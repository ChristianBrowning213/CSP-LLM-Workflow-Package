from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def _base_settings(workdir: Path) -> Settings:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]
    return settings


def test_spp_falls_back_to_export_ready_corpus_candidate_when_requested_candidate_blocked(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_EXPORT_PATTERN", "blocked,blocked,exported,exported")
    settings = _base_settings(workdir)
    result = run_csp_pipeline(
        query="TiO2 rutile",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={
            "retrieval_candidate_k": 4,
            "corpus_strategy": "top_k",
            "corpus_top_k": 2,
            "corpus_strategy_candidates": ["top_k"],
            "corpus_top_k_candidates": [2, 4],
            "guidance_mode": "guidance_only",
        },
    )
    assert result.status == "SUCCEEDED"

    candidates = json.loads((result.run_dir / "artifacts" / "spp_corpus_candidates.json").read_text(encoding="utf-8"))
    assert candidates["selection_reason"] == "fallback_export_ready_candidate"
    assert str(candidates["selected_candidate_id"]).startswith("top_k:top4:")

    manifest = json.loads((result.run_dir / "artifacts" / "spp_corpus_manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["selection_reason"] == "fallback_export_ready_candidate"
    exportability = manifest["metadata"]["exportability"]
    assert int(exportability["exportable_count"]) == 2
    assert int(exportability["blocked_count"]) == 2

    spp_input = json.loads((result.run_dir / "artifacts" / "spp_input_selection.json").read_text(encoding="utf-8"))
    assert int(spp_input["staged_count"]) == 2

    spp_run = json.loads((result.run_dir / "artifacts" / "spp_run.json").read_text(encoding="utf-8"))
    assert int(spp_run["result"]["cif_count"]) == 2


def test_spp_fails_truthfully_when_no_export_ready_corpus_candidate_exists(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_EXPORT_PATTERN", "blocked,blocked,blocked,blocked")
    settings = _base_settings(workdir)
    result = run_csp_pipeline(
        query="TiO2 rutile",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={
            "retrieval_candidate_k": 4,
            "corpus_strategy": "top_k",
            "corpus_top_k": 2,
            "corpus_strategy_candidates": ["top_k"],
            "corpus_top_k_candidates": [2, 4],
            "guidance_mode": "guidance_only",
        },
    )
    assert result.status == "FAILED"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["failure_reason"] == "spp_corpus_unavailable:no_export_ready_candidate"
