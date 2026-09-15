from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import FAIL_QLIP_PLACEHOLDER, run_startup_validation


def test_qlip_placeholder_solution_blocks_startup(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_QLIP_PLACEHOLDER_SOLUTION", "1")
    monkeypatch.delenv("FAKE_QLIP_CONSTANT_SOLUTION", raising=False)
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
    assert report["startup_ok"] is False
    assert report["blocked_by"] == FAIL_QLIP_PLACEHOLDER
