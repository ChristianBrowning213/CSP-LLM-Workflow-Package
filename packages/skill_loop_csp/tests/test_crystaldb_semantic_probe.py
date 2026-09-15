from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_crystaldb_semantic_probe(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
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
    crystal = report["dependencies"]["crystaldb"]
    assert crystal["semantic_ok"] is True
    probe = crystal["probe"]
    assert probe["neighbor_count_a"] > 0
    assert probe["neighbor_count_b"] > 0
    assert set(probe["candidate_ids_a"]) != set(probe["candidate_ids_b"])
