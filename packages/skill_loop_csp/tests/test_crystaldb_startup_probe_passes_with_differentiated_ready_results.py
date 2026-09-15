from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_crystaldb_startup_probe_passes_with_differentiated_ready_results(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FAKE_CRYSTALDB_MISSING_DB", raising=False)
    monkeypatch.delenv("FAKE_CRYSTALDB_MISSING_INDEX", raising=False)
    monkeypatch.delenv("FAKE_CRYSTALDB_MISSING_EMBEDDING", raising=False)
    monkeypatch.delenv("FAKE_CRYSTALDB_CANDIDATE_SET_EMPTY", raising=False)
    monkeypatch.delenv("FAKE_CRYSTALDB_EMPTY_RETRIEVAL", raising=False)
    monkeypatch.delenv("FAKE_CRYSTALDB_COLLAPSED", raising=False)
    settings = Settings.from_sources(None)
    report = run_startup_validation(
        mode="stub",
        settings=settings,
        workspace=workdir,
        commands=(
            _stub_command("mcp_crystaldb_server.py"),
            _stub_command("mcp_spp_server.py"),
            _stub_command("mcp_qlip_server.py"),
        ),
        strict=True,
    )
    crystal = report["dependencies"]["crystaldb"]
    probe = crystal["probe"]
    assert crystal["semantic_ok"] is True
    assert probe["neighbor_count_a"] > 0
    assert probe["neighbor_count_b"] > 0
    assert probe["candidate_signature_a"] != probe["candidate_signature_b"]
    assert probe["pack_candidate_signature_a"] != probe["pack_candidate_signature_b"]

