from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_guidance_mode_materializes_request(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]

    run = run_csp_pipeline(
        query="TiO2 rutile-like",
        with_spp=False,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={"guidance_mode": "guidance_only"},
    )
    req = json.loads((run.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    guidance = req.get("guidance", [])
    assert isinstance(guidance, list) and guidance
    ids = [str(item.get("id")) for item in guidance if isinstance(item, dict)]
    assert "objective.energy_spp" in ids
