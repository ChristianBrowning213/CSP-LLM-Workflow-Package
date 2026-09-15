from __future__ import annotations

from sok_llm_orchestrator.bench.reporting import build_benchmark_report


def test_benchmark_reporting_outputs_tables() -> None:
    raw = {
        "benchmark_id": "bench-1",
        "rows": [
            {
                "case_id": "c1",
                "baseline_status": "SUCCEEDED",
                "guided_status": "SUCCEEDED",
                "property_key": "property_x",
                "baseline_property": 0.6,
                "guided_property": 0.8,
                "retrieval_nn": {"mode": "metadata"},
            }
        ],
    }
    report = build_benchmark_report(raw)
    assert report["schema_version"] == "benchmark.report.v1"
    assert "baseline_vs_guided" in report
    assert report["property_comparison"]["all_pass"] is True
    assert "metrics_payload" in report
