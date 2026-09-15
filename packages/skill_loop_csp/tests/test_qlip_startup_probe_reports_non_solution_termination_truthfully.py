from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import FAIL_QLIP_NON_SOLUTION, run_startup_validation


def test_qlip_startup_probe_reports_non_solution_termination_truthfully(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_QLIP_EXT_SHAPE_MODE", "non_solution")
    settings = Settings.from_sources(None)
    report = run_startup_validation(
        mode="stub",
        settings=settings,
        workspace=workdir,
        commands=(
            _stub_command("mcp_crystaldb_server.py"),
            _stub_command("mcp_spp_server.py"),
            _stub_command("mcp_qlip_server_external_shape.py"),
        ),
        strict=True,
    )
    qlip = report["dependencies"]["qlip"]
    assert report["startup_ok"] is False
    assert qlip["failure_code"] == FAIL_QLIP_NON_SOLUTION
    assert "non-solution termination" in str(qlip["detail"]).lower()

