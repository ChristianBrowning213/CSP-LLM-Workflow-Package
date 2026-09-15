from __future__ import annotations

from sok_llm_orchestrator.contracts.phase1_properties import phase1_property_report


def test_doctor_phase1_properties_reports_all_phase1_entries_implemented() -> None:
    report = phase1_property_report()
    assert report["counts"] == {
        "total": 8,
        "implemented_now": 8,
        "small_wiring_needed": 0,
        "benchmark_ready_now": 8,
    }
    assert report["small_wiring_needed"] == []
    ids = {row["id"] for row in report["implemented_now"]}
    assert {
        "qlip.native.density_packing_proxy",
        "qlip.native.linear_property_proxy",
        "qlip.native.threshold_tradeoff",
    }.issubset(ids)
