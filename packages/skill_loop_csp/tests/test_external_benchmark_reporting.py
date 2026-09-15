from __future__ import annotations

from sok_llm_orchestrator.bench.external import build_external_benchmark_report


def test_external_benchmark_reporting() -> None:
    raw = {
        "matrix_id": "ext-1",
        "mode": "stub",
        "datasets": ["mp_20"],
        "splits": ["test"],
        "regimes": ["qlip_baseline", "qlip_full_orchestrator"],
        "budget": {"max_iterations": 3},
        "rows": [
            {
                "dataset": "mp_20",
                "split": "test",
                "regime": "qlip_baseline",
                "budget": {"max_iterations": 1},
                "solved_valid": True,
                "best_objective_within_budget": 0.2,
                "structure_diversity_within_budget": 1,
                "rediscovery_match": False,
            },
            {
                "dataset": "mp_20",
                "split": "test",
                "regime": "qlip_full_orchestrator",
                "budget": {"max_iterations": 3},
                "solved_valid": False,
                "best_objective_within_budget": 0.4,
                "structure_diversity_within_budget": 2,
                "rediscovery_match": True,
                "orchestrator_diagnostics": {
                    "branch_switch_count": 2,
                    "spp_unique_corpus_strategy_count": 2,
                    "spp_unique_package_variant_count": 2,
                    "spp_unique_payload_signature_count": 3,
                    "richer_exploration_detected": True,
                },
            },
        ],
    }
    report = build_external_benchmark_report(raw)
    assert report["schema_version"] == "benchmark.external.matrix.report.v1"
    assert report["matrix_id"] == "ext-1"
    assert len(report["grouped_summary"]) == 2
    baseline = [row for row in report["grouped_summary"] if row["regime"] == "qlip_baseline"][0]
    assert baseline["solved_valid_rate"] == 1.0
    orchestrator = [row for row in report["grouped_summary"] if row["regime"] == "qlip_full_orchestrator"][0]
    assert orchestrator["full_orchestrator_diagnostics"]["mean_branch_switch_count"] == 2.0
