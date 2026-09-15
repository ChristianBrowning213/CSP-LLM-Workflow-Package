from __future__ import annotations

import sys
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_startup_qlip_probe_preserves_provenance_after_handshake(workdir: Path) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[1]
    qlip_script = (root / "tests" / "fakes" / "mcp_qlip_server_realistic.py").resolve()
    settings = Settings.from_sources(None)
    report = run_startup_validation(
        mode="stub",
        settings=settings,
        workspace=workdir,
        commands=(
            [sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_crystaldb_server.py")],
            [sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_spp_server.py")],
            [sys.executable, "-u", str(qlip_script)],
        ),
        strict=True,
    )
    qlip_dep = report["dependencies"]["qlip"]
    qlip_probe = qlip_dep["probe"]
    provenance = qlip_dep["provenance"]
    assert report["startup_ok"] is True
    assert qlip_probe.get("server_marker_payload_sha256") == "realistic"
    assert str(provenance.get("script_path")) == str(qlip_script)
    assert provenance.get("connection_mode") == "launched_stdio_subprocess"

