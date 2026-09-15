from __future__ import annotations

import json
import os
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.crystaldb import apply_crystal_policy_defaults
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_demo_export_forced_off_in_safe_mode() -> None:
    args, notes = apply_crystal_policy_defaults({"demo_export": True}, "safe")
    assert args["demo_export"] is False
    assert any("forced:demo_export=false" in note for note in notes)


def test_safe_mode_blocks_export_when_allow_export_zero(workdir: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "0")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.crystaldb_policy_mode = "safe"
    settings.allowed_read_roots = [workdir]
    settings.allowed_write_roots = [workdir]
    result = run_csp_pipeline(
        query="TiO2 rutile",
        with_spp=False,
        mode="stub",
        workspace=workdir,
        settings=settings,
    )
    assert result.status == "SUCCEEDED"
    crystal_payload = json.loads((result.run_dir / "artifacts" / "crystal_csp_pack.json").read_text(encoding="utf-8"))
    assert crystal_payload["neighbors"][0]["cif_export"]["status"] == "blocked"
