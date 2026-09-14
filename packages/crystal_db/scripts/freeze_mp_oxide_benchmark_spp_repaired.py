"""Freeze the SPP-repaired methodology and maximally novel 50+50 target roster."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crystal_db.benchmark_freeze import (  # noqa: E402
    build_target_evidence_pools,
    canonical_hash,
    equivalence_map,
    select_diverse_targets,
)
from crystal_db.family_dataset import write_json_atomic  # noqa: E402


DATA_ROOT = REPO_ROOT / "artifacts" / "mp_oxide_families_v1"
ENGINEERING_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_benchmark_v1"
PRIOR_FINAL_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_benchmark_v2_final"
CORRECTNESS_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_benchmark_v2_spp_correctness_audit_v2"
PACKAGE_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_benchmark_v2_spp_package_audit_v2"
SMOKE_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_spp_repair_smoke_v2"
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_benchmark_v3_spp_repaired"
FAMILIES = (("layered", "MP_LAYERED_BATTERY_OXIDES_V1"), ("spinel", "MP_SPINEL_OXIDES_V1"))


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _expanded(keys: set[str], equivalents: dict[str, set[str]]) -> set[str]:
    result = set(keys)
    for key in tuple(keys):
        result.update(equivalents.get(key, {key}))
    return result


def _maximum_diverse_selection(rows, *, limit: int, groups, excluded: set[str]):
    for count in range(limit, -1, -1):
        try:
            return select_diverse_targets(
                rows, count=count, equivalent_groups=groups,
                excluded_candidate_keys=excluded,
            )
        except ValueError:
            continue
    return []


def main() -> int:
    engineering = _read(ENGINEERING_ROOT / "frozen_benchmark.json")
    prior = _read(PRIOR_FINAL_ROOT / "frozen_benchmark.json")
    previous_methodology = _read(
        ENGINEERING_ROOT / "development_pair_aware_v1" / "FROZEN_METHODOLOGY.json"
    )
    correctness = _read(CORRECTNESS_ROOT / "SPP_CORRECTNESS_AUDIT_SUMMARY.json")
    package = _read(PACKAGE_ROOT / "SPP_PACKAGE_AUDIT_SUMMARY.json")
    smoke = _read(SMOKE_ROOT / "SMOKE_SUMMARY.json")
    if not (
        correctness["targets_fully_coverable_after_global"] == 100
        and correctness["targets_with_genuinely_unsupported_pair"] == 0
        and package["spp_ready"] == package["processed_targets"] == 100
        and package["qlip_runs"] == 0
        and smoke["spp_ready"] == smoke["qlip_entered"] == smoke["candidate_cifs"] == smoke["sca_completed"] == 6
        and smoke["scaffold_used"] == smoke["reference_used_before_generation"] == 0
    ):
        raise SystemExit("SPP repair audit/smoke acceptance gate is not satisfied")

    methodology = {
        "schema_version": "spp_only_oxide_methodology.freeze.v2.spp_repaired",
        "supersedes_methodology_sha256": previous_methodology["methodology_sha256"],
        "policy": {
            **previous_methodology["policy"],
            "pair_resolution_hierarchy": [
                "REQUEST_PLUS_GLOBAL",
                "GLOBAL",
                "UNSUPPORTED",
            ],
            "global_regulator": correctness["regulator"],
            "synthetic_fallback_allowed": False,
            "strict_final_package_audit_required": True,
            "family_database_provenance_assertion_required": True,
            "selected_to_spp_input_hash_chain_required": True,
            "output_root_scoped_run_ids_required": True,
        },
        "validation": {
            "correctness_audit_sha256": canonical_hash(correctness),
            "package_audit_sha256": canonical_hash(package),
            "qlip_smoke_sha256": canonical_hash(smoke),
            "targets_fully_coverable_from_selected_local_alone": correctness["targets_fully_coverable_from_selected_local_alone"],
            "targets_requiring_global_support": correctness["targets_requiring_global_support"],
            "targets_fully_coverable_after_global": correctness["targets_fully_coverable_after_global"],
            "targets_with_genuinely_unsupported_pair": correctness["targets_with_genuinely_unsupported_pair"],
            "spp_package_targets_ready": package["spp_ready"],
            "qlip_smoke_targets": smoke["row_count"],
            "qlip_smoke_candidates": smoke["candidate_cifs"],
            "qlip_smoke_sca_completed": smoke["sca_completed"],
        },
    }
    methodology["methodology_sha256"] = canonical_hash(methodology)

    targets = []
    evidence_pools = []
    availability = {}
    overlap = {}
    sources = {}
    engineering_keys_all = {str(row["candidate_key"]) for row in engineering["targets"]}
    prior_keys_all = {str(row["candidate_key"]) for row in prior["targets"]}
    for family, dataset_id in FAMILIES:
        root = DATA_ROOT / dataset_id
        accepted = _read(root / "accepted.json")["rows"]
        audit = _read(root / "dataset_audit.json")
        manifest = _read(root / "dataset_manifest.json")
        groups = audit["structure_matcher_equivalent_groups"]
        equivalents = equivalence_map(groups)
        engineering_keys = {
            str(row["candidate_key"]) for row in engineering["targets"] if row["family"] == family
        }
        prior_keys = {
            str(row["candidate_key"]) for row in prior["targets"] if row["family"] == family
        }
        engineering_excluded = _expanded(engineering_keys, equivalents)
        fresh_excluded = engineering_excluded | _expanded(prior_keys, equivalents)
        fresh = _maximum_diverse_selection(
            accepted, limit=50, groups=groups, excluded=fresh_excluded,
        )
        deficit = 50 - len(fresh)
        selected_keys = {str(row["candidate_key"]) for row in fresh}
        prior_rows = [row for row in accepted if str(row["candidate_key"]) in prior_keys]
        reused = select_diverse_targets(
            prior_rows, count=deficit, equivalent_groups=groups,
            excluded_candidate_keys=engineering_excluded | _expanded(selected_keys, equivalents),
        ) if deficit else []
        representatives = fresh + reused
        if len(representatives) != 50:
            raise SystemExit(f"failed to freeze 50 {family} targets")
        overlap[family] = {
            "fresh_target_count": len(fresh),
            "prior_final_overlap_count": len(reused),
            "prior_final_overlap_candidate_keys": [str(row["candidate_key"]) for row in reused],
            "fully_novel_50_target_roster_possible": deficit == 0,
        }
        availability[family] = {
            "accepted_count": len(accepted),
            "engineering_and_equivalent_excluded_count": len(engineering_excluded),
            "fresh_non_equivalent_target_capacity": len(fresh),
        }
        family_targets = []
        for index, row in enumerate(representatives, start=1):
            family_targets.append({
                "benchmark_id": f"{family}-repaired-{index:03d}",
                "family": family,
                "dataset_id": dataset_id,
                "candidate_key": row["candidate_key"],
                "material_id": row["material_id"],
                "working_ion": row.get("working_ion"),
                "formula": row["formula"],
                "structure_id": row["structure_id"],
                "target_cif_path": row["structure_bundle"]["paths"]["primitive"],
                "target_cif_sha256": row["structure_bundle"]["sha256"]["primitive"],
                "target_roster_source": "FRESH" if row in fresh else "PRIOR_FINAL_OVERLAP_REQUIRED_BY_CAPACITY",
            })
        targets.extend(family_targets)
        pools = build_target_evidence_pools(representatives, accepted, groups)
        by_key = {row["candidate_key"]: row["benchmark_id"] for row in family_targets}
        evidence_pools.extend(
            {**pool, "benchmark_id": by_key[pool["target_key"]], "family": family}
            for pool in pools
        )
        sources[dataset_id] = {
            "manifest_hash": canonical_hash(manifest),
            "accepted_count": audit["accepted_count"],
        }

    final_keys = {str(row["candidate_key"]) for row in targets}
    assertions = {
        "EXACTLY_100_TARGETS": len(targets) == 100,
        "EXACTLY_50_LAYERED": sum(row["family"] == "layered" for row in targets) == 50,
        "EXACTLY_50_SPINEL": sum(row["family"] == "spinel" for row in targets) == 50,
        "NO_ENGINEERING_TARGET_OVERLAP": not bool(final_keys & engineering_keys_all),
        "NO_TARGET_LEAKAGE": all(pool["no_target_leakage"] for pool in evidence_pools),
        "METHODOLOGY_FROZEN": bool(methodology["methodology_sha256"]),
        "NO_PRIOR_FINAL_TARGET_OVERLAP": not bool(final_keys & prior_keys_all),
        "PRIOR_FINAL_OVERLAP_EXPLICIT": sum(
            row["prior_final_overlap_count"] for row in overlap.values()
        ) == len(final_keys & prior_keys_all),
        "SCAFFOLD_USED": False,
        "REFERENCE_STRUCTURE_USED_BEFORE_GENERATION": False,
        "PAIR_COVERAGE_COMPLETE": "NOT_EVALUATED_ON_NEW_ROSTER",
        "SPP_ARTIFACT_VALID": "NOT_EVALUATED_ON_NEW_ROSTER",
    }
    required_true = {
        "EXACTLY_100_TARGETS", "EXACTLY_50_LAYERED", "EXACTLY_50_SPINEL",
        "NO_ENGINEERING_TARGET_OVERLAP", "NO_TARGET_LEAKAGE", "METHODOLOGY_FROZEN",
        "PRIOR_FINAL_OVERLAP_EXPLICIT",
    }
    if not all(assertions[key] is True for key in required_true):
        raise SystemExit(f"repaired freeze assertions failed: {assertions}")

    payload = {
        "freeze_version": "spp_only_oxide_benchmark.freeze.v3.spp_repaired",
        "selection_rule": "maximize deterministic non-equivalent novelty after engineering and v2 exclusions, then fill unavoidable family-capacity deficit from v2 targets",
        "methodology_sha256": methodology["methodology_sha256"],
        "source_manifests": sources,
        "availability": availability,
        "prior_final_overlap": overlap,
        "targets": targets,
        "evidence_pools": evidence_pools,
        "assertions": assertions,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_json_atomic(OUTPUT_ROOT / "FROZEN_METHODOLOGY.json", methodology)
    write_json_atomic(OUTPUT_ROOT / "frozen_benchmark.json", payload)
    write_json_atomic(OUTPUT_ROOT / "benchmark_targets_final.json", targets)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_ROOT / "benchmark_targets_final.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(targets[0]))
        writer.writeheader()
        writer.writerows(targets)
    print(json.dumps({
        "artifact": str(OUTPUT_ROOT / "frozen_benchmark.json"),
        "freeze_sha256": payload["freeze_sha256"],
        "methodology_sha256": methodology["methodology_sha256"],
        "prior_final_overlap": overlap,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
