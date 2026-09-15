from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import (
    FAIL_CRYSTALDB_BACKEND_NOT_READY,
    FAIL_CRYSTALDB_EMPTY,
    run_startup_validation,
)


def _run_stub_startup(settings: Settings, workdir: Path) -> dict[str, object]:
    return run_startup_validation(
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


def test_crystaldb_startup_probe_distinguishes_healthy_empty_vs_backend_not_ready(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings.from_sources(None)
    monkeypatch.setenv("FAKE_CRYSTALDB_EMPTY_RETRIEVAL", "1")
    monkeypatch.delenv("FAKE_CRYSTALDB_MISSING_INDEX", raising=False)
    empty_report = _run_stub_startup(settings, workdir / "healthy_empty")
    empty_failure = empty_report["dependencies"]["crystaldb"]["failure_code"]  # type: ignore[index]
    assert empty_failure == FAIL_CRYSTALDB_EMPTY

    monkeypatch.delenv("FAKE_CRYSTALDB_EMPTY_RETRIEVAL", raising=False)
    monkeypatch.setenv("FAKE_CRYSTALDB_MISSING_INDEX", "1")
    not_ready_report = _run_stub_startup(settings, workdir / "not_ready")
    not_ready_failure = not_ready_report["dependencies"]["crystaldb"]["failure_code"]  # type: ignore[index]
    assert not_ready_failure == FAIL_CRYSTALDB_BACKEND_NOT_READY

