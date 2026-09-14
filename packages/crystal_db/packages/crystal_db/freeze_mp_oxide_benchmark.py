"""Freeze 50 layered and 50 spinel held-out SPP-only benchmark targets."""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crystal_db.benchmark_freeze import (  # noqa: E402
    FREEZE_VERSION,
    build_target_evidence_pools,
    canonical_hash,
    select_diverse_targets,
)
from crystal_db.family_dataset import write_json_atomic  # noqa: E402


DATA_ROOT = REPO_ROOT / "artifacts" / "mp_oxide_families_v1"
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_benchmark_v1"
FAMILIES = (
    ("layered", "MP_LAYERED_BATTERY_OXIDES_V1"),
    ("spinel", "MP_SPINEL_OXIDES_V1"),
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    targets = []
    evidence_pools = []
    source_manifests = {}
    for family, dataset_id in FAMILIES:
        root = DATA_ROOT / dataset_id
        accepted = load_json(root / "accepted.json")["rows"]
        audit = load_json(root / "dataset_audit.json")
        manifest = load_json(root / "dataset_manifest.json")
        selected = select_diverse_targets(
            accepted,
            count=50,
            equivalent_groups=audit["structure_matcher_equivalent_groups"],
        )
        family_targets = []
        for index, row in enumerate(selected, start=1):
            family_targets.append(
                {
                    "benchmark_id": f"{family}-{index:03d}",
                    "family": family,
                    "dataset_id": dataset_id,
                    "candidate_key": row["candidate_key"],
                    "material_id": row["material_id"],
                    "working_ion": row.get("working_ion"),
                    "formula": row["formula"],
                    "structure_id": row["structure_id"],
                    "target_cif_path": row["structure_bundle"]["paths"]["primitive"],
                    "target_cif_sha256": row["structure_bundle"]["sha256"]["primitive"],
                }
            )
        targets.extend(family_targets)
        pools = build_target_evidence_pools(
            selected,
            accepted,
            audit["structure_matcher_equivalent_groups"],
        )
        by_key = {row["candidate_key"]: row["benchmark_id"] for row in family_targets}
        evidence_pools.extend(
            {**pool, "benchmark_id": by_key[pool["target_key"]], "family": family}
            for pool in pools
        )
        source_manifests[dataset_id] = {
            "manifest_hash": canonical_hash(manifest),
            "accepted_count": audit["accepted_count"],
        }
    assertions = {
        "EXACTLY_100_TARGETS": len(targets) == 100,
        "EXACTLY_50_LAYERED": sum(row["family"] == "layered" for row in targets) == 50,
        "EXACTLY_50_SPINEL": sum(row["family"] == "spinel" for row in targets) == 50,
        "NO_TARGET_LEAKAGE": all(pool["no_target_leakage"] for pool in evidence_pools),
        "SCAFFOLD_USED": False,
        "REFERENCE_STRUCTURE_USED_BEFORE_GENERATION": False,
        "PAIR_COVERAGE_COMPLETE": "NOT_EVALUATED",
        "SPP_ARTIFACT_VALID": "NOT_EVALUATED",
    }
    if not all(value is True for key, value in assertions.items() if key.startswith("EXACTLY_") or key == "NO_TARGET_LEAKAGE"):
        raise SystemExit(f"Freeze assertions failed: {assertions}")
    payload = {
        "freeze_version": FREEZE_VERSION,
        "source_manifests": source_manifests,
        "targets": targets,
        "evidence_pools": evidence_pools,
        "assertions": assertions,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_json_atomic(OUTPUT_ROOT / "frozen_benchmark.json", payload)
    print("targets", len(targets), "freeze_sha256", payload["freeze_sha256"])
    print("artifact", OUTPUT_ROOT / "frozen_benchmark.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
