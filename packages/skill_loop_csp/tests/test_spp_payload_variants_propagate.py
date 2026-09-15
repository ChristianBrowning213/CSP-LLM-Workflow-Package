from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def _guidance_params(run_dir: Path) -> dict:
    request = json.loads((run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    guidance = request.get("guidance", [])
    if not isinstance(guidance, list) or not guidance:
        return {}
    row = guidance[0]
    return row.get("params", {}) if isinstance(row, dict) else {}


def test_spp_payload_variants_change_request_guidance_structure(workdir: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]

    weak = run_csp_pipeline(
        query="Sr2FeMoO6 ordered structure",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={
            "guidance_mode": "guidance_only",
            "spp_payload_profile": "weak",
            "spp_guidance_weight": 0.25,
            "spp_top_k_breakdown": 4,
            "spp_pairs_policy": "task_pairs",
            "spp_oob_policy": "clamp",
            "spp_missing_pair_policy": "zero",
        },
    )
    assert weak.status == "SUCCEEDED"
    strong = run_csp_pipeline(
        query="Sr2FeMoO6 ordered structure",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={
            "guidance_mode": "guidance_only",
            "spp_payload_profile": "strong",
            "spp_guidance_weight": 1.4,
            "spp_top_k_breakdown": 24,
            "spp_pairs_policy": "all_available",
            "spp_oob_policy": "max",
            "spp_missing_pair_policy": "max_global",
        },
    )
    assert strong.status == "SUCCEEDED"
    weak_params = _guidance_params(weak.run_dir)
    strong_params = _guidance_params(strong.run_dir)
    assert weak_params != strong_params
    assert float(weak_params["lambda_override"]) < float(strong_params["lambda_override"])
    assert int(weak_params["top_k_breakdown"]) < int(strong_params["top_k_breakdown"])
    assert weak_params["pairs_policy"] != strong_params["pairs_policy"]
