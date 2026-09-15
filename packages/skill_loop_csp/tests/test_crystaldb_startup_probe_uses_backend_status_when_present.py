from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_crystaldb_startup_probe_uses_backend_status_when_present(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FAKE_CRYSTALDB_MISSING_DB", raising=False)
    monkeypatch.delenv("FAKE_CRYSTALDB_MISSING_INDEX", raising=False)
    monkeypatch.delenv("FAKE_CRYSTALDB_MISSING_EMBEDDING", raising=False)
    monkeypatch.delenv("FAKE_CRYSTALDB_CANDIDATE_SET_EMPTY", raising=False)
    monkeypatch.delenv("FAKE_CRYSTALDB_EMPTY_RETRIEVAL", raising=False)
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
    assert probe["status_tool_available"] is True
    assert probe["status_tool_backend_state"] == "ready"
    assert probe["status_a"] == "ok"
    assert probe["pack_status_a"] == "ok"
    assert isinstance(probe["backend_status_a"], dict)
    assert isinstance(probe["pack_backend_status_a"], dict)

