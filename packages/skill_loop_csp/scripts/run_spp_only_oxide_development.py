"""Run the stratified 5+5 pair-aware engineering development gate."""

from __future__ import annotations

import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sok_llm_orchestrator.workflow.spp_only_benchmark import (  # noqa: E402
    SPPOnlyBenchmarkPolicy,
    _run_target,
    _write_csv,
    _write_json,
)
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages  # noqa: E402


QUOTAS = {
    "layered": {"PARTIAL_REQUIRED_PAIR_COVERAGE": 2, "SPP_ARTIFACT_INVALID": 2, "CASE_NORMALIZATION_FALSE_FAILURE": 1},
    "spinel": {"PARTIAL_REQUIRED_PAIR_COVERAGE": 3, "SPP_ARTIFACT_INVALID": 2},
}


def main() -> int:
    crystal_root = REPO_ROOT.parent / "Crystal-DB"
    benchmark_root = crystal_root / "artifacts" / "spp_only_oxide_benchmark_v1"
    frozen = json.loads((benchmark_root / "frozen_benchmark.json").read_text(encoding="utf-8"))
    with (benchmark_root / "SPP_ONLY_100_ENGINEERING_FAILURE_AUDIT.csv").open(newline="", encoding="utf-8") as handle:
        audit = list(csv.DictReader(handle))
    by_id = {str(row["benchmark_id"]): row for row in frozen["targets"]}
    pools = {str(row["benchmark_id"]): row for row in frozen["evidence_pools"]}
    selected_ids: list[str] = []
    for family, quotas in QUOTAS.items():
        for blocker, count in quotas.items():
            eligible = sorted(
                (row for row in audit if row["family"] == family and row["first_blocker"] == blocker),
                key=lambda row: row["experiment_id"],
            )
            selected_ids.extend(str(row["experiment_id"]) for row in eligible[:count])
    if len(selected_ids) != 10 or Counter(by_id[value]["family"] for value in selected_ids) != Counter({"layered": 5, "spinel": 5}):
        raise RuntimeError("development selection did not produce exactly 5 layered and 5 spinel targets")
    output_root = benchmark_root / "development_pair_aware_v1"
    policy = SPPOnlyBenchmarkPolicy()
    _write_json(output_root / "development_manifest.json", {
        "schema_version": "spp_only_pair_aware_development.v1",
        "selection_rule": "lowest benchmark IDs within fixed family/engineering-blocker quotas",
        "quotas": QUOTAS, "benchmark_ids": selected_ids, "policy": {
            "candidate_retrieval_depth": policy.candidate_retrieval_depth,
            "semantic_corpus_size": policy.spp_corpus_size,
            "maximum_corpus_size": policy.maximum_corpus_size,
            "quality_augmentation_batch_size": policy.quality_augmentation_batch_size,
            "native_grid_density": policy.native_grid_density,
            "cutoff": policy.cutoff,
        },
        "future_final_target_exclusion": "all 100 SPP-only oxide benchmark v1 engineering targets",
    })
    stages = ProductionWorkflowStages()
    rows = []
    for benchmark_id in selected_ids:
        target = by_id[benchmark_id]
        summary_path = output_root / "runs" / target["family"] / benchmark_id / "run_summary.json"
        if summary_path.is_file():
            existing = json.loads(summary_path.read_text(encoding="utf-8"))
            message = str(existing.get("failure_message", ""))
            retry_software_failure = (
                "out_root already exists" in message
                or (existing.get("SPP_ARTIFACT_VALID") is True and "generated.cif" in message)
            )
            if not retry_software_failure:
                rows.append(existing)
                continue
            history = summary_path.parent / "retry_history"
            history.mkdir(parents=True, exist_ok=True)
            index = 1
            while (history / f"run_summary_before_retry_{index:03d}.json").exists():
                index += 1
            shutil.copy2(summary_path, history / f"run_summary_before_retry_{index:03d}.json")
        rows.append(_run_target(
            target=target, pool=pools[benchmark_id], crystal_root=crystal_root,
            output_root=output_root, policy=policy, stages=stages,
        ))
        _write_csv(output_root / "DEVELOPMENT_RESULTS.csv", rows[0].keys(), rows)
    _write_csv(output_root / "DEVELOPMENT_RESULTS.csv", rows[0].keys(), rows)
    counts = Counter(str(row["final_classification"]) for row in rows)
    _write_json(output_root / "DEVELOPMENT_SUMMARY.json", {
        "row_count": len(rows), "families": Counter(str(row["family"]) for row in rows),
        "terminal_classifications": counts,
        "pair_coverage_complete": sum(bool(row["PAIR_COVERAGE_COMPLETE"]) for row in rows),
        "spp_artifact_valid": sum(bool(row["SPP_ARTIFACT_VALID"]) for row in rows),
        "qlip_solves": sum(str(row["qlip_status"]) not in {"", "NOT_RUN"} for row in rows),
        "cifs_generated": sum(bool(row["candidate_generated"]) for row in rows),
        "sca_completed": sum(str(row["sca_status"]) not in {"", "NOT_RUN"} for row in rows),
    })
    print(json.dumps({"row_count": len(rows), "terminal_classifications": counts, "output_root": str(output_root)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
