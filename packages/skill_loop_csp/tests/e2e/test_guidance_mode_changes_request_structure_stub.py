from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import run_per_key_ablation_experiment


def test_guidance_mode_changes_request_structure_stub(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_per_key_ablation_experiment(
        query="TiO2 optimize high property x",
        mode="stub",
        workspace=workdir,
        settings=settings,
        dimensions=["qlip_guidance"],
    )
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    row = report["comparisons"][0]
    req_diff = row["diff_summary"]["executable_request_diff"]
    assert req_diff["request_structure_changed"] is True
    assert row["propagation_classification"] == "propagates_to_request_structure"
    assert "objective.energy_spp" in req_diff["variant_guidance_ids"]
