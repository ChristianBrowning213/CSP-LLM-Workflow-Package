from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import FAIL_CRYSTALDB_BACKEND_NOT_READY, run_startup_validation


def test_crystaldb_startup_probe_reports_missing_index_or_db_truthfully(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTALDB_MISSING_DB", "1")
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
    assert report["startup_ok"] is False
    assert crystal["failure_code"] == FAIL_CRYSTALDB_BACKEND_NOT_READY
    assert "missing_db" in str(crystal["detail"])
    assert "missing_db" in set(crystal["probe"].get("error_codes", []))

