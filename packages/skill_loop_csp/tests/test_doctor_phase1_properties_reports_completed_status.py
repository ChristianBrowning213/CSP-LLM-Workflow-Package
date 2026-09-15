from __future__ import annotations

from sok_llm_orchestrator.contracts.phase1_properties import phase1_property_report


def test_doctor_phase1_properties_reports_completed_status() -> None:
    report = phase1_property_report()
    assert report["schema_version"] == "phase1.property_library.v1"
    assert int(report["counts"]["implemented_now"]) == 8
    assert int(report["counts"]["small_wiring_needed"]) == 0

    rows = {row["id"]: row for row in report["all_entries"]}
    calibrated = rows["spp.calibration.recommended_lambda"]
    assert calibrated["implementation_status"] == "implemented_now"
    assert bool(calibrated["benchmark_ready_now"]) is True

    for key in (
        "qlip.native.density_packing_proxy",
        "qlip.native.linear_property_proxy",
        "qlip.native.threshold_tradeoff",
    ):
        assert rows[key]["implementation_status"] == "implemented_now"
        assert bool(rows[key]["benchmark_ready_now"]) is True
