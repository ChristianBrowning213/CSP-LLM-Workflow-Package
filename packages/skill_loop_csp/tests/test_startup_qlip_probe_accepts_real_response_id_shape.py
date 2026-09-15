from __future__ import annotations

import sys
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_startup_qlip_probe_accepts_real_response_id_shape(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("FAKE_MCP_RESPONSE_ID_STRING", "1")
    settings = Settings.from_sources(None)
    report = run_startup_validation(
        mode="stub",
        settings=settings,
        workspace=workdir,
        commands=(
            [sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_crystaldb_server.py")],
            [sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_spp_server.py")],
            [sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_qlip_server_realistic.py")],
        ),
        strict=True,
    )
    qlip_dep = report["dependencies"]["qlip"]
    assert report["startup_ok"] is True
    assert qlip_dep["startup_ok"] is True
    assert qlip_dep["surface_ok"] is True
    assert qlip_dep["semantic_ok"] is True

