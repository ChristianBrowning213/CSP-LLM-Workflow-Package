from __future__ import annotations

from sok_llm_orchestrator.metrics.result_schema import validate_result_payload


def test_metrics_payload_serialization_schema() -> None:
    payload = {
        "schema_version": "metrics.result.v1",
        "generated_at": "2026-03-19T10:00:00Z",
        "rows": [
            {
                "case_id": "case-1",
                "run_family": "baseline_qlip",
                "feasible": True,
                "time_to_first_feasible_s": 2.5,
                "objective_value": -1.2,
                "retry_count": 0,
                "analogue_distance": 0.14,
                "space_group_match": True,
                "evidence_completeness": 1.0,
                "reproducible": True,
                "notes": [],
            }
        ],
        "summary": {"total_cases": 1, "feasibility_rate": 1.0, "guided_win_rate": None},
    }
    validate_result_payload(payload)
