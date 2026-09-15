from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_qlip_startup_probe_accepts_valid_external_result_shape(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_QLIP_EXT_SHAPE_MODE", "valid")
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
    assert report["startup_ok"] is True
    assert qlip["semantic_ok"] is True
    assert qlip["probe"]["cif_source_a"] == "inline"
    assert qlip["probe"]["cif_source_b"] == "inline"
    assert qlip["probe"]["server_marker_payload_sha256"] == "external-shape"

