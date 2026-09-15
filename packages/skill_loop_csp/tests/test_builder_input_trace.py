from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_builder_input_trace_maps_overrides_and_surfaces_dropped_keys(workdir: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]

    run = run_csp_pipeline(
        query="TiO2 rutile-like",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={
            "retrieval_mode": "hybrid",
            "cell_selection_policy": "fixed_benchmark",
            "spp_calibration_mode": "aggressive",
            "spp_payload_profile": "strong",
            "spp_guidance_weight": 1.1,
        },
    )
    assert run.status == "SUCCEEDED"
    meta_path = run.run_dir / "artifacts" / "qlip_builder_meta.json"
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    trace = payload["builder_input_trace"]
    assert trace["schema_version"] == "qlip.builder_input_trace.v1"
    assert set(trace["override_keys_present"]) >= {
        "retrieval_mode",
        "cell_selection_policy",
        "spp_calibration_mode",
        "spp_payload_profile",
        "spp_guidance_weight",
    }
    assert "spp_calibration_mode" not in trace["dropped_override_keys"]
    assert "spp_payload_profile" not in trace["dropped_override_keys"]
    assert "spp_guidance_weight" not in trace["dropped_override_keys"]
    projection = trace["override_key_projection"]
    assert projection["retrieval_mode"] == "hybrid"
    assert projection["cell_selection_policy"] == "fixed_benchmark"
    assert projection["spp_calibration_mode"] == "aggressive"
