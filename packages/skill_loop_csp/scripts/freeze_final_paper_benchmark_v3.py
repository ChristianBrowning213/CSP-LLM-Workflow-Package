"""Freeze Benchmark V3 after the actual request-SPP quality preflight passes."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "artifacts" / "final_paper_benchmark_v2"
PREFLIGHT = ROOT / "artifacts" / "final_paper_benchmark_v3_quality_preflight"
OUT = ROOT / "artifacts" / "final_paper_benchmark_v3"
WORKFLOW_COMMIT = "698d82a37d94b1b64a6f2488a2e3b205dbf0f989"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to freeze an empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    freeze_path = OUT / "BENCHMARK_V3_FREEZE.json"
    if freeze_path.exists():
        raise RuntimeError(f"Benchmark V3 is already frozen; refusing to overwrite: {freeze_path}")
    status = json.loads((PREFLIGHT / "QUALITY_PREFLIGHT_STATUS.json").read_text(encoding="utf-8"))
    if status != {
        "generated_cifs": 0,
        "ready_to_freeze": True,
        "result_2_executable": 7,
        "result_2_targets": 7,
        "result_3_four_mode_api_executable": 7,
        "result_4_negative_ready": 3,
        "result_4_positive_ready": 3,
        "sca_invocations": 0,
        "solver_invocations": 0,
        "workflow_commit": WORKFLOW_COMMIT,
    }:
        raise RuntimeError(f"quality preflight is not in the exact ready state: {status}")

    provenance = json.loads((PREFLIGHT / "GUIDANCE_PREFLIGHT_PROVENANCE.json").read_text(encoding="utf-8"))
    if len(provenance["runs"]) != 10 or any(
        run["reference_exclusion"]["reference_equivalent_evidence_count"] != 0
        or run["solver_invoked"] or run["cif_generated"] or run["sca_invoked"]
        for run in provenance["runs"]
    ):
        raise RuntimeError("quality-preflight provenance boundary is not freeze-safe")

    summaries = read_csv(PREFLIGHT / "ACTUAL_REQUEST_SPP_TARGET_SUMMARY.csv")
    result3 = read_csv(PREFLIGHT / "RESULT_3_ACTUAL_INFORMATIVENESS.csv")
    result4_readiness = read_csv(PREFLIGHT / "RESULT_4_GUIDANCE_READINESS.csv")
    if len(summaries) != 7 or any(int(row["unsupported_pair_count"]) for row in summaries):
        raise RuntimeError("Result-2 guidance readiness failed")
    if len(result3) != 7 or any(row["actual_informativeness"] == "UNSUPPORTED" for row in result3):
        raise RuntimeError("Result-3 readiness failed")
    if len(result4_readiness) != 6 or any(row["ready"] != "YES" for row in result4_readiness):
        raise RuntimeError("Result-4 readiness failed")

    OUT.mkdir(parents=True, exist_ok=False)
    target_rows = [{
        "case_id": row["case_id"],
        "formula": row["formula"],
        "canonical_task_mapping": "YES",
        "scaffold_id": "cubic_perovskite_variable_cation_v1",
        "scaffold_independent": "YES",
        "corpus_id": row["corpus_id"],
        "required_pair_count": row["required_pair_count"],
        "request_usable_pair_count": row["request_usable_pair_count"],
        "regulator_fallback_pair_count": row["regulator_fallback_pair_count"],
        "unsupported_pair_count": row["unsupported_pair_count"],
        "request_usable_fraction": row["request_usable_fraction"],
        "overall_local_support_status": row["overall_local_support_status"],
        "RESULT_2_ELIGIBLE": "YES",
    } for row in summaries]
    write_csv(OUT / "BENCHMARK_V3_TARGETS.csv", target_rows)
    shutil.copy2(V2 / "BENCHMARK_V2_REFERENCES.csv", OUT / "BENCHMARK_V3_REFERENCES.csv")
    write_csv(OUT / "RESULT_3_INFORMATIVENESS.csv", result3)

    config = json.loads((V2 / "BENCHMARK_V2_CONFIG.json").read_text(encoding="utf-8"))
    config.update({
        "schema_version": "final_paper_benchmark_v3_config.v1",
        "workflow_commit": WORKFLOW_COMMIT,
        "execution_status": "FROZEN_NOT_STARTED",
        "actual_request_spp_support_characterised_before_solver": True,
        "quality_preflight_status_hash": sha256(PREFLIGHT / "QUALITY_PREFLIGHT_STATUS.json"),
        "quality_preflight_provenance_hash": sha256(PREFLIGHT / "GUIDANCE_PREFLIGHT_PROVENANCE.json"),
    })
    config["retrieval"]["nasicon_specialist_route_id"] = "nasicon_specialist_v3"
    config["retrieval"]["nasicon_specialist_dataset_id"] = "nasicon_specialist_all_targets_out_v3"
    write_json(OUT / "BENCHMARK_V3_CONFIG.json", config)

    leakage = json.loads((V2 / "LEAKAGE_EXCLUSION_CONFIG.json").read_text(encoding="utf-8"))
    leakage["schema_version"] = "benchmark_v3_leakage_exclusion.v1"
    leakage["validated_actual_reference_equivalent_evidence_count"] = 0
    write_json(OUT / "LEAKAGE_EXCLUSION_CONFIG.json", leakage)

    factorial = json.loads((V2 / "RESULT_3_FACTORIAL_CONFIG.json").read_text(encoding="utf-8"))
    factorial.update({
        "schema_version": "benchmark_v3_result3_factorial.v1",
        "informativeness_rule": "genuinely variable loose scaffold; HIGH >=2 usable request pairs, MEDIUM exactly 1, NOT_INFORMATIVE_FOR_REQUEST_SPP exactly 0, UNSUPPORTED if any required pair lacks request and regulator guidance",
        "zero_usable_pair_interpretation": "REGULATOR_PLUS_REQUEST is operationally regulator-only after explicit fallback; robustness evidence only and excluded from causal request-SPP denominator",
        "all_targets_receive_same_four_conditions": True,
    })
    write_json(OUT / "RESULT_3_FACTORIAL_CONFIG.json", factorial)

    result4 = json.loads((V2 / "RESULT_4_NASICON_CONFIG.json").read_text(encoding="utf-8"))
    result4.update({
        "schema_version": "benchmark_v3_result4_nasicon.v1",
        "specialist_corpus_route_id": "nasicon_specialist_v3",
        "guidance_readiness_hash": sha256(PREFLIGHT / "RESULT_4_GUIDANCE_READINESS.csv"),
        "positive_guidance_ready_count": 3,
        "negative_expected_terminal_ready_count": 3,
        "execution_status": "FROZEN_NOT_STARTED",
    })
    write_json(OUT / "RESULT_4_NASICON_CONFIG.json", result4)

    protocol = """# Final Paper Benchmark V3 Protocol

This protocol was frozen before generation at canonical workflow commit `698d82a37d94b1b64a6f2488a2e3b205dbf0f989`. Benchmark V2 remains preserved as `INVALID_NOT_LAUNCHED`; this V3 freeze does not overwrite it. Result 2 retains the same seven targets. SrTiO3 remains excluded for `NO_INDEPENDENT_REFERENCE`, with no replacement.

## Result 2

Each independently sourced Materials Project reference is excluded after retrieval and before request-SPP evidence acceptance by source ID, raw hash, canonical hash, and StructureMatcher equivalence, including pair-support expansion. Each execution fits a fresh request SPP, applies the unchanged production POT quality gate (`max_cap_fraction = 0.5`), and uses frozen `icsd_broad_regulator_v1` Option-1 fallback. A target is executable when every compiled pair has final guidance; local request-POT usability is not an eligibility requirement. The canonical scaffold, QLIP, objective parity, CIF, SCA, and post-generation reference comparison have not run at freeze time.

## Result 3

All seven targets receive the same four factorial conditions: tight/loose scaffold crossed with request-specific SPP off/on. References, exclusions, retrieval, regulator, solver, SCA, and scaffold definitions are fixed.

Causal request-SPP interpretation is separated using actual pre-solve production POT quality. HIGH requires at least two usable request pairs, MEDIUM exactly one, NOT_INFORMATIVE_FOR_REQUEST_SPP zero, and UNSUPPORTED any required pair lacking both request and regulator guidance. For a zero-usable-pair target, `REGULATOR_PLUS_REQUEST` is operationally equivalent to regulator-only after explicit per-pair fallback. It may demonstrate robustness/fallback behavior, but it supplies no causal information about useful request-specific SPP guidance and is excluded from the denominator for claims that request SPP helped or worsened selection. With at least one usable request pair, the paired loose-scaffold comparison is informative about request-specific guidance.

## Result 4

Three positive NASICON cases route to the target-excluded specialist corpus, fit fresh specialist request SPP, and use the same frozen regulator and fallback semantics. Three negative cases retain their controlled representability terminal stages. No QLIP solve was run during guidance readiness.

## Freeze boundary

References and the target set were frozen before generation. Actual request-SPP support was characterised before any solver outcome. CSP benchmark solves before this freeze: **0**.
"""
    (OUT / "BENCHMARK_V3_PROTOCOL.md").write_text(protocol, encoding="utf-8")

    frozen_inputs = [
        "BENCHMARK_V3_PROTOCOL.md",
        "BENCHMARK_V3_TARGETS.csv",
        "BENCHMARK_V3_REFERENCES.csv",
        "BENCHMARK_V3_CONFIG.json",
        "LEAKAGE_EXCLUSION_CONFIG.json",
        "RESULT_3_FACTORIAL_CONFIG.json",
        "RESULT_3_INFORMATIVENESS.csv",
        "RESULT_4_NASICON_CONFIG.json",
    ]
    file_hashes = {name: sha256(OUT / name) for name in frozen_inputs}
    v2_manifest = {row["path"]: row["sha256"] for row in read_csv(V2 / "OUTPUT_HASH_MANIFEST.csv")}
    freeze = {
        "schema_version": "final_paper_benchmark_v3_freeze.v1",
        "canonical_workflow_commit": WORKFLOW_COMMIT,
        "benchmark_v2_preserved_invalid_not_launched": True,
        "benchmark_v2_hash_manifest_sha256": sha256(V2 / "OUTPUT_HASH_MANIFEST.csv"),
        "benchmark_v2_protected_hashes": v2_manifest,
        "benchmark_v3_file_hashes": file_hashes,
        "references_frozen_before_generation": True,
        "target_set_frozen_before_generation": True,
        "actual_request_spp_support_characterised_before_solver_outcomes": True,
        "scientific_workflow_commit_fixed": True,
        "CSP_benchmark_solves_executed_before_freeze": 0,
        "selected_target_count": 7,
        "result_2_executable_count": 7,
        "result_3_four_mode_target_count": 7,
        "result_4_positive_guidance_ready_count": 3,
        "result_4_negative_terminal_ready_count": 3,
        "spp_quality_threshold": {"max_cap_fraction": 0.5, "pot_quality_required_for_local": "usable"},
        "regulator": {
            "id": provenance["runs"][0]["regulator_id"],
            "tree_sha256": provenance["runs"][0]["regulator_hash"],
        },
        "paper_benchmark_execution_status": "FROZEN_NOT_STARTED",
    }
    write_json(freeze_path, freeze)
    manifest_rows = [{"path": name, "sha256": sha256(OUT / name)} for name in frozen_inputs + ["BENCHMARK_V3_FREEZE.json"]]
    write_csv(OUT / "OUTPUT_HASH_MANIFEST.csv", manifest_rows)
    print(json.dumps({"freeze_dir": str(OUT), "file_hashes": {row['path']: row['sha256'] for row in manifest_rows}}, indent=2))


if __name__ == "__main__":
    main()
