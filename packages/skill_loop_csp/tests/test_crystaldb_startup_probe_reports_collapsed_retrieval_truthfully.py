from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import FAIL_CRYSTALDB_COLLAPSED, run_startup_validation


def test_crystaldb_startup_probe_reports_collapsed_retrieval_truthfully(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTALDB_COLLAPSED", "1")
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
    assert crystal["failure_code"] == FAIL_CRYSTALDB_COLLAPSED
    assert "query-insensitive retrieval" in str(crystal["detail"])

