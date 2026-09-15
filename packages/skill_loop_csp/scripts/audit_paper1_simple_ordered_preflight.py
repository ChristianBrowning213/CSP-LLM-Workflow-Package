"""Audit the frozen Paper 1 preflight without changing workflow artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


NO_POT_PATTERN = re.compile(
    r"Required pair lacks both a valid local common-contract POT and global fallback: (?P<pair>\S+)"
)
FIELDS = (
    "row_id", "family", "target_reference_id", "retrieval_status",
    "raw_retrieval_count", "target_in_raw_retrieval", "spp_evidence_count",
    "target_in_spp_evidence", "target_disposition_recorded", "target_disposition",
    "holdout_exclusion_recorded", "preflight_status",
    "classification", "unsupported_pair", "usable_cell", "spp_contract_status",
    "candidate_cif_count", "error",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in FIELDS} for row in rows)


def _candidate_cifs(row_root: Path) -> list[Path]:
    """Return generated CIFs, excluding retrieval and SPP evidence inputs."""
    excluded_parts = {"retrieval", "spp", "spp_evidence"}
    return [
        path for path in row_root.rglob("*.cif")
        if not excluded_parts.intersection(part.lower() for part in path.relative_to(row_root).parts)
    ]


def audit_row(row_root: Path, frozen_row: Mapping[str, Any]) -> dict[str, Any]:
    row_id = str(frozen_row["row_id"])
    target_id = str(frozen_row.get("target_reference_id") or frozen_row["record_id"])
    manifest_path = row_root / "retrieval" / "retrieval_manifest.json"
    status_path = row_root / "status" / "generation_status.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    status = read_json(status_path) if status_path.is_file() else {}
    raw_selected = manifest.get("selected", [])
    evidence = manifest.get("spp_evidence", {})
    evidence_selected = evidence.get("selected", [])
    raw_ids = {str(item.get("structure_id", "")) for item in raw_selected}
    evidence_ids = {str(item.get("structure_id", "")) for item in evidence_selected}
    exclusion_audit = evidence.get("exclusion_audit", [])
    target_dispositions = [
        str(item.get("reason", "")) for item in exclusion_audit
        if str(item.get("structure_id")) == target_id
    ]
    exclusion_recorded = any(
        str(item.get("structure_id")) == target_id
        and item.get("decision") == "excluded"
        and item.get("reason") == "structure_holdout_id"
        for item in exclusion_audit
    )
    error = str(status.get("error", ""))
    no_pot_match = NO_POT_PATTERN.search(error)
    cache_path = row_root / "spp" / "request_spp_cache.json"
    cache = read_json(cache_path) if cache_path.is_file() else {}
    quality = cache.get("quality", {})
    preflight_status = str(status.get("preflight_status", ""))
    if preflight_status == "PASS":
        classification = "EXECUTABLE"
    elif no_pot_match:
        classification = "SCIENTIFIC_SPP_PAIR_COVERAGE_FAILURE"
    else:
        classification = "UNCLASSIFIED_PREFLIGHT_FAILURE"
    family = str(frozen_row.get("family") or row_id.rsplit("_", 3)[0])
    return {
        "row_id": row_id,
        "family": family,
        "target_reference_id": target_id,
        "retrieval_status": "PASS" if manifest_path.is_file() and raw_selected else "FAIL",
        "raw_retrieval_count": len(raw_selected),
        "target_in_raw_retrieval": target_id in raw_ids,
        "spp_evidence_count": len(evidence_selected),
        "target_in_spp_evidence": target_id in evidence_ids,
        "target_disposition_recorded": target_id not in raw_ids or bool(target_dispositions),
        "target_disposition": ";".join(target_dispositions) if target_dispositions else "not_in_raw_retrieval",
        "holdout_exclusion_recorded": exclusion_recorded,
        "preflight_status": preflight_status or "FAIL",
        "classification": classification,
        "unsupported_pair": no_pot_match.group("pair") if no_pot_match else "",
        "usable_cell": (row_root / "cell" / "dynamic_cell.json").is_file(),
        "spp_contract_status": str(quality.get("status", "NOT_BUILT")),
        "candidate_cif_count": len(_candidate_cifs(row_root)),
        "error": error,
    }


def audit(
    *, benchmark_csv: Path, freeze_manifest: Path, run_root: Path, output_root: Path
) -> dict[str, Any]:
    freeze = read_json(freeze_manifest)
    with benchmark_csv.open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    targets_by_row = {str(item["row_id"]): item for item in freeze["targets"]}
    rows = [
        audit_row(run_root / str(row["row_id"]), targets_by_row[str(row["row_id"])])
        for row in csv_rows
    ]
    run_config = read_json(run_root / "run_config.json")
    current_csv_hash = sha256_file(benchmark_csv)
    assertions = {
        "frozen_row_count_matches": len(rows) == int(freeze["target_count"]),
        "benchmark_csv_unchanged_from_freeze": current_csv_hash == freeze["benchmark_csv_sha256"],
        "benchmark_csv_unchanged_during_preflight": current_csv_hash == run_config["input_csv_sha256"],
        "retrieval_manifest_present_for_every_row": all(row["retrieval_status"] == "PASS" for row in rows),
        "target_absent_from_every_spp_evidence_cohort": all(not row["target_in_spp_evidence"] for row in rows),
        "target_disposition_recorded_for_every_raw_hit": all(
            row["target_disposition_recorded"] for row in rows
        ),
        "every_executable_row_has_usable_cell": all(
            row["usable_cell"] for row in rows if row["classification"] == "EXECUTABLE"
        ),
        "every_executable_row_has_common_contract_spp": all(
            row["spp_contract_status"] == "PASS_COMMON_CONTRACT"
            for row in rows if row["classification"] == "EXECUTABLE"
        ),
        "all_failures_are_classified_pair_coverage_failures": all(
            row["classification"] != "UNCLASSIFIED_PREFLIGHT_FAILURE" for row in rows
        ),
        "zero_candidate_cifs_generated": all(row["candidate_cif_count"] == 0 for row in rows),
    }
    counts = Counter(str(row["classification"]) for row in rows)
    family_counts: dict[str, dict[str, int]] = {}
    for row in rows:
        family_counts.setdefault(str(row["family"]), {})
        family = family_counts[str(row["family"])]
        key = str(row["classification"])
        family[key] = family.get(key, 0) + 1
    result = {
        "schema_version": "paper1_simple_ordered_preflight_audit.v1",
        "benchmark_csv": str(benchmark_csv.resolve()),
        "benchmark_csv_sha256": current_csv_hash,
        "freeze_manifest": str(freeze_manifest.resolve()),
        "run_root": str(run_root.resolve()),
        "counts": dict(counts),
        "family_counts": family_counts,
        "raw_retrieval_semantics": (
            "The raw ranked search log may contain the target. The leakage boundary is the "
            "SPP evidence cohort, where the exact structure_id must be excluded before fitting."
        ),
        "assertions": assertions,
        "rows": rows,
    }
    write_json(output_root / "PREFLIGHT_AUDIT.json", result)
    write_csv(output_root / "PREFLIGHT_AUDIT.csv", rows)
    lines = [
        "# Paper 1 frozen preflight audit", "",
        f"Frozen targets: {len(rows)}. Executable: {counts['EXECUTABLE']}. "
        f"SPP pair-coverage failures: {counts['SCIENTIFIC_SPP_PAIR_COVERAGE_FAILURE']}.", "",
        "The raw ranked retrieval log may contain a held-out target for auditability. "
        "For every row, the exact target is absent from the SPP fitting cohort. Every raw target "
        "hit has an explicit disposition: `structure_holdout_id` when it reaches the fixed cohort, "
        "or `fixed_ranked_cohort_limit` when it lies beyond that cohort.", "",
        "No candidate CIF was generated during preflight. The benchmark CSV hash matches both "
        "the freeze manifest and run configuration.", "", "## Assertions", "",
    ]
    lines.extend(f"- {'PASS' if value else 'FAIL'}: `{name}`" for name, value in assertions.items())
    lines.extend(["", "## Classified SPP coverage failures", ""])
    lines.extend(
        f"- `{row['row_id']}`: unsupported pair `{row['unsupported_pair']}`"
        for row in rows if row["classification"] == "SCIENTIFIC_SPP_PAIR_COVERAGE_FAILURE"
    )
    (output_root / "PREFLIGHT_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not all(assertions.values()):
        failed = [name for name, value in assertions.items() if not value]
        raise RuntimeError(f"preflight audit failed: {', '.join(failed)}")
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--benchmark-csv", type=Path, default=root / "benchmark_paper1_simple_ordered_v1.csv")
    parser.add_argument(
        "--freeze-manifest", type=Path,
        default=root / "artifacts" / "paper1_spp_positive_domain" / "freeze_v1" / "FROZEN_BENCHMARK_MANIFEST.json",
    )
    parser.add_argument("--run-root", type=Path, default=root / "outputs" / "paper1_simple_ordered_v1")
    parser.add_argument(
        "--output-root", type=Path,
        default=root / "artifacts" / "paper1_spp_positive_domain" / "preflight",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = audit(
        benchmark_csv=args.benchmark_csv.resolve(),
        freeze_manifest=args.freeze_manifest.resolve(), run_root=args.run_root.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps({"status": "PASS", "counts": result["counts"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
