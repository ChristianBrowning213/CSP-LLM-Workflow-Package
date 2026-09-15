from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_startup_report_includes_qlip_provenance(workdir: Path) -> None:  # type: ignore[no-untyped-def]
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
    qlip_provenance = report["dependencies"]["qlip"]["provenance"]
    assert qlip_provenance["connection_mode"] == "launched_stdio_subprocess"
    assert qlip_provenance["attached"] is False
    assert isinstance(qlip_provenance.get("resolved_argv"), list)
    assert isinstance(qlip_provenance.get("launch_cwd"), str)
    assert isinstance(qlip_provenance.get("script_path"), str)

