from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_pipeline_tracks_multiple_spp_package_candidates(workdir: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]

    run = run_csp_pipeline(
        query="BaTiO3 polymorph search",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={
            "guidance_mode": "guidance_only",
            "spp_package_variant": "focus",
            "spp_package_alternatives": ["default", "focus", "broad"],
            "spp_package_target": 1.0,
        },
    )
    assert run.status == "SUCCEEDED"
    candidates_path = run.run_dir / "artifacts" / "spp_package_candidates.json"
    assert candidates_path.exists()
    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "spp.package_candidates.v1"
    assert payload["selected_variant"] == "focus"
    assert len(payload["items"]) >= 2

    artifact_manifest = json.loads((run.run_dir / "artifacts" / "spp_artifact_manifest.json").read_text(encoding="utf-8"))
    meta = artifact_manifest["metadata"]
    assert meta["package_variant"] == "focus"
    assert isinstance(meta.get("package_candidate_ids"), list) and len(meta["package_candidate_ids"]) >= 2
