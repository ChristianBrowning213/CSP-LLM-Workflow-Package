from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_pipeline_surfaces_multiple_corpus_candidates(workdir: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]

    run = run_csp_pipeline(
        query="SrTiO3 hard structural case",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={
            "retrieval_mode": "hybrid",
            "retrieval_candidate_k": 8,
            "corpus_strategy": "top_k",
            "corpus_top_k": 4,
            "corpus_strategy_candidates": ["top_k", "family_biased", "composition_tight"],
            "corpus_top_k_candidates": [3, 4, 6],
            "guidance_mode": "guidance_only",
        },
    )
    assert run.status == "SUCCEEDED"
    candidates_path = run.run_dir / "artifacts" / "spp_corpus_candidates.json"
    assert candidates_path.exists()
    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "spp.corpus_candidates.v1"
    assert len(payload["items"]) >= 2

    builder_meta = json.loads((run.run_dir / "artifacts" / "qlip_builder_meta.json").read_text(encoding="utf-8"))
    trace = builder_meta["builder_input_trace"]
    assert int(trace["builder_inputs"]["corpus_candidate_count"]) >= 2
    assert "corpus_strategy_candidates" in trace["consumed_override_keys"]
    assert "corpus_top_k_candidates" in trace["consumed_override_keys"]
