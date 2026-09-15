from __future__ import annotations

from sok_llm_orchestrator.contracts.spp_normalize import normalize_spp_arguments


def test_alias_hoist_and_unknown_drop() -> None:
    raw = {
        "arguments": {
            "traceId": "t1",
            "cifDir": "in",
            "outDir": "out",
            "name": "run",
            "target": 0.9,
            "dryRun": True,
            "extra_field": 123,
        }
    }
    normalized, warnings = normalize_spp_arguments("spp.run_pipeline", raw)
    assert normalized["trace_id"] == "t1"
    assert normalized["cif_dir"] == "in"
    assert normalized["out_dir"] == "out"
    assert normalized["dry_run"] is True
    assert "calibration" in normalized and normalized["calibration"]["target"] == 0.9
    assert "extra_field" not in normalized
    assert warnings
    assert any(item["code"] == "unknown_key_filtered" for item in warnings)
