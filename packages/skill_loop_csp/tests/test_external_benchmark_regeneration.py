from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.bench.external import compare_external_benchmark_reports, regenerate_external_benchmark_report


def test_external_benchmark_regeneration(workdir: Path) -> None:  # type: ignore[no-untyped-def]
    results = {
        "schema_version": "benchmark.external.matrix.v1",
        "matrix_id": "ext-regen",
        "mode": "stub",
        "datasets": ["mp_20"],
        "splits": ["test"],
        "regimes": ["qlip_baseline"],
        "budget": {"max_iterations": 1},
        "rows": [
            {
                "dataset": "mp_20",
                "split": "test",
                "regime": "qlip_baseline",
                "budget": {"max_iterations": 1},
                "solved_valid": True,
                "best_objective_within_budget": 0.3,
                "structure_diversity_within_budget": 1,
                "rediscovery_match": False,
            }
        ],
    }
    path = workdir / "external_matrix_results.json"
    path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = regenerate_external_benchmark_report(path)
    assert report["schema_version"] == "benchmark.external.matrix.report.v1"
    assert report["matrix_id"] == "ext-regen"

    compare = compare_external_benchmark_reports(report, report)
    assert compare["schema_version"] == "benchmark.external.matrix.compare.v1"
    assert len(compare["group_deltas"]) == 1
    assert compare["group_deltas"][0]["delta_solved_valid_rate"] == 0.0
