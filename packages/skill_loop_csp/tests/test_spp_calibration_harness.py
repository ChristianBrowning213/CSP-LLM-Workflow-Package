from __future__ import annotations

from sok_llm_orchestrator.spp.calibration_harness import run_calibration_harness


def test_spp_calibration_harness_report_shape() -> None:
    report = run_calibration_harness([0.1, 0.3, 0.6, 0.8], target_quantile=0.75)
    assert report["schema_version"] == "spp.calibration_report.v1"
    assert "recommended_weight" in report
    assert report["distribution"]["count"] == 4
