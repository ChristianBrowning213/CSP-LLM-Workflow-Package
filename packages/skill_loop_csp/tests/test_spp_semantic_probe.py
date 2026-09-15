from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_spp_semantic_probe(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FAKE_QLIP_PLACEHOLDER_SOLUTION", raising=False)
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
    spp = report["dependencies"]["spp"]
    assert spp["semantic_ok"] is True
    probe = spp["probe"]
    assert probe["package_path_a"]
    assert probe["package_path_b"]
    assert probe["package_signature_a"] != probe["package_signature_b"]
