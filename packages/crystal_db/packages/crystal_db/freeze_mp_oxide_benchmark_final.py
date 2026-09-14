"""Freeze a clean 50+50 final target set disjoint from engineering v1."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crystal_db.benchmark_freeze import (  # noqa: E402
    build_target_evidence_pools, canonical_hash, equivalence_map, select_diverse_targets,
)
from crystal_db.family_dataset import write_json_atomic  # noqa: E402


DATA_ROOT = REPO_ROOT / "artifacts" / "mp_oxide_families_v1"
ENGINEERING_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_benchmark_v1"
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_benchmark_v2_final"
METHODOLOGY_PATH = ENGINEERING_ROOT / "development_pair_aware_v1" / "FROZEN_METHODOLOGY.json"
FAMILIES = (("layered", "MP_LAYERED_BATTERY_OXIDES_V1"), ("spinel", "MP_SPINEL_OXIDES_V1"))


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    engineering = _read(ENGINEERING_ROOT / "frozen_benchmark.json")
    engineering_by_family = {
        family: {str(row["candidate_key"]) for row in engineering["targets"] if row["family"] == family}
        for family, _ in FAMILIES
    }
    methodology = _read(METHODOLOGY_PATH)
    targets = []
    evidence_pools = []
    availability = {}
    sources = {}
    for family, dataset_id in FAMILIES:
        root = DATA_ROOT / dataset_id
        accepted = _read(root / "accepted.json")["rows"]
        audit = _read(root / "dataset_audit.json")
        manifest = _read(root / "dataset_manifest.json")
        equivalents = equivalence_map(audit["structure_matcher_equivalent_groups"])
        excluded = set(engineering_by_family[family])
        for key in tuple(excluded):
            excluded.update(equivalents.get(key, {key}))
        representatives = select_diverse_targets(
            accepted, count=50, equivalent_groups=audit["structure_matcher_equivalent_groups"],
            excluded_candidate_keys=excluded,
        )
        eligible_count = sum(
            str(row["candidate_key"]) not in excluded
            for row in accepted
        )
        availability[family] = {
            "accepted_count": len(accepted), "engineering_and_equivalent_excluded_count": len(excluded),
            "eligible_row_count_before_non_equivalent_representative_filter": eligible_count,
        }
        family_targets = []
        for index, row in enumerate(representatives, start=1):
            family_targets.append({
                "benchmark_id": f"{family}-final-{index:03d}", "family": family,
                "dataset_id": dataset_id, "candidate_key": row["candidate_key"],
                "material_id": row["material_id"], "working_ion": row.get("working_ion"),
                "formula": row["formula"], "structure_id": row["structure_id"],
                "target_cif_path": row["structure_bundle"]["paths"]["primitive"],
                "target_cif_sha256": row["structure_bundle"]["sha256"]["primitive"],
            })
        targets.extend(family_targets)
        pools = build_target_evidence_pools(representatives, accepted, audit["structure_matcher_equivalent_groups"])
        by_key = {row["candidate_key"]: row["benchmark_id"] for row in family_targets}
        evidence_pools.extend({**pool, "benchmark_id": by_key[pool["target_key"]], "family": family} for pool in pools)
        sources[dataset_id] = {"manifest_hash": canonical_hash(manifest), "accepted_count": audit["accepted_count"]}
    final_keys = {str(row["candidate_key"]) for row in targets}
    engineering_keys = {str(row["candidate_key"]) for row in engineering["targets"]}
    assertions = {
        "EXACTLY_100_TARGETS": len(targets) == 100,
        "EXACTLY_50_LAYERED": sum(row["family"] == "layered" for row in targets) == 50,
        "EXACTLY_50_SPINEL": sum(row["family"] == "spinel" for row in targets) == 50,
        "NO_ENGINEERING_TARGET_OVERLAP": not bool(final_keys & engineering_keys),
        "NO_TARGET_LEAKAGE": all(pool["no_target_leakage"] for pool in evidence_pools),
        "METHODOLOGY_FROZEN": bool(methodology.get("methodology_sha256")),
        "SCAFFOLD_USED": False, "REFERENCE_STRUCTURE_USED_BEFORE_GENERATION": False,
        "PAIR_COVERAGE_COMPLETE": "NOT_EVALUATED", "SPP_ARTIFACT_VALID": "NOT_EVALUATED",
    }
    if not all(value is True for key, value in assertions.items() if key.startswith("EXACTLY_") or key in {"NO_ENGINEERING_TARGET_OVERLAP", "NO_TARGET_LEAKAGE", "METHODOLOGY_FROZEN"}):
        raise SystemExit(f"final freeze assertions failed: {assertions}")
    payload = {
        "freeze_version": "spp_only_oxide_benchmark.freeze.v2.final",
        "selection_rule": "diverse deterministic formula round-robin after excluding all engineering v1 targets and known equivalents",
        "engineering_freeze_sha256": engineering["freeze_sha256"],
        "methodology_sha256": methodology["methodology_sha256"],
        "source_manifests": sources, "availability": availability,
        "targets": targets, "evidence_pools": evidence_pools, "assertions": assertions,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_json_atomic(OUTPUT_ROOT / "frozen_benchmark.json", payload)
    write_json_atomic(OUTPUT_ROOT / "benchmark_targets_final.json", targets)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_ROOT / "benchmark_targets_final.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(targets[0]))
        writer.writeheader()
        writer.writerows(targets)
    print("targets", len(targets), "freeze_sha256", payload["freeze_sha256"])
    print("artifact", OUTPUT_ROOT / "frozen_benchmark.json")
    print("availability", json.dumps(availability, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
