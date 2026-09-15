"""Run the deterministic 3+3 scaffold-free post-repair QLIP smoke."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from sok_llm_orchestrator.workflow.spp_only_benchmark import (
    SPPOnlyBenchmarkPolicy,
    _run_target,
    _write_csv,
    _write_json,
)
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages


SMOKE_IDS = (
    "layered-final-001", "layered-final-002", "layered-final-009",
    "spinel-final-008", "spinel-final-001", "spinel-final-002",
)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    crystal_root = repo_root.parent / "Crystal-DB"
    frozen_path = crystal_root / "artifacts" / "spp_only_oxide_benchmark_v2_final" / "frozen_benchmark.json"
    stopped_results = frozen_path.parent / "results" / "PAPER_SPP_ONLY_100_RESULTS.csv"
    output_root = crystal_root / "artifacts" / "spp_only_oxide_spp_repair_smoke_v2"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    targets = {str(row["benchmark_id"]): row for row in frozen["targets"]}
    pools = {str(row["benchmark_id"]): row for row in frozen["evidence_pools"]}
    with stopped_results.open(encoding="utf-8", newline="") as handle:
        stopped = {row["experiment_id"]: row for row in csv.DictReader(handle)}
    policy = SPPOnlyBenchmarkPolicy()
    _write_json(output_root / "SMOKE_MANIFEST.json", {
        "schema_version": "spp_correctness_qlip_smoke.v2",
        "selection_rule": "first layered old success/build/coverage plus first spinel old build and first two old coverage failures",
        "benchmark_ids": list(SMOKE_IDS),
        "old_classifications": {value: stopped[value]["final_classification"] for value in SMOKE_IDS},
        "policy": {
            "candidate_retrieval_depth": policy.candidate_retrieval_depth,
            "spp_corpus_size": policy.spp_corpus_size,
            "maximum_corpus_size": policy.maximum_corpus_size,
            "quality_augmentation_batch_size": policy.quality_augmentation_batch_size,
            "native_grid_density": policy.native_grid_density,
            "cutoff": policy.cutoff,
            "scaffold": "none",
            "target_reference_before_generation": False,
        },
    })
    stages = ProductionWorkflowStages()
    rows = []
    for experiment_id in SMOKE_IDS:
        target = targets[experiment_id]
        summary_path = output_root / "runs" / str(target["family"]) / experiment_id / "run_summary.json"
        if summary_path.is_file():
            rows.append(json.loads(summary_path.read_text(encoding="utf-8")))
        else:
            rows.append(_run_target(
                target=target, pool=pools[experiment_id], crystal_root=crystal_root,
                output_root=output_root, policy=policy, stages=stages,
            ))
        _write_csv(output_root / "SMOKE_RESULTS.csv", rows[0].keys(), rows)
    summary = {
        "row_count": len(rows),
        "families": dict(Counter(str(row["family"]) for row in rows)),
        "terminal_classifications": dict(Counter(str(row["final_classification"]) for row in rows)),
        "spp_ready": sum(bool(row["SPP_ARTIFACT_VALID"]) for row in rows),
        "qlip_entered": sum(str(row["qlip_status"]) not in {"", "NOT_RUN"} for row in rows),
        "optimal_or_feasible": sum(str(row["qlip_status"]) in {"OPTIMAL", "FEASIBLE", "FEASIBLE_TIME_LIMIT"} for row in rows),
        "candidate_cifs": sum(bool(row["candidate_generated"]) for row in rows),
        "sca_completed": sum(str(row["sca_status"]) == "COMPLETED" for row in rows),
        "scaffold_used": sum(bool(row["SCAFFOLD_USED"]) for row in rows),
        "reference_used_before_generation": sum(bool(row["REFERENCE_STRUCTURE_USED_BEFORE_GENERATION"]) for row in rows),
    }
    _write_json(output_root / "SMOKE_SUMMARY.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
