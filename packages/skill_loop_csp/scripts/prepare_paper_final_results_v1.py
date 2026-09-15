"""Prepare the frozen final paper-results manifest and protected-input gate."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT.parent
SCA_CAMPAIGN = GITHUB / "Structured_Crystal_Analyser" / "artifacts" / "paper_full_sca_v1"
DEMO = ROOT / "artifacts" / "paper_diversity_v2" / "nasicon_demo"
OUT = ROOT / "artifacts" / "paper_final_results_v1"
MANIFESTS = OUT / "01_manifests"
RUNS = ROOT / "runs" / "paper_final_results_v1"
FIGURES = ROOT / "figures" / "paper_final_results_v1"
POLICY_MAP = {
    "rocksalt": "ROCKSALT", "nitride": "ROCKSALT", "fluorite": "FLUORITE",
    "perovskite": "PEROVSKITE_3D", "spinel": "SPINEL",
    "olivine phosphate": "OLIVINE", "layered oxide": "LAYERED_OXIDE",
    "argyrodite": "ARGYRODITE_ORDERED", "halide perovskite": "HALIDE_PEROVSKITE_3D",
    "nasicon": "NASICON_ORDERED",
}
ROW_FIELDS = [
    "final_row_id", "source_campaign", "source_task_id", "experiment_group",
    "natural_language_request", "structured_intent_hash", "target_formula",
    "target_family", "target_topology", "requested_space_group", "scaffold_id",
    "scaffold_version", "retrieval_corpus", "spp_status", "solver_mode",
    "solver_status", "solver_certificate_available", "generated_cif_path",
    "expected_cif_sha256", "trace_bundle_path", "source_result_path",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if not rows and fields is None:
        raise RuntimeError(f"Cannot infer columns for empty CSV: {path}")
    columns = fields or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "pass", "optimal"}


def build_rows() -> list[dict[str, Any]]:
    legacy = read_csv(SCA_CAMPAIGN / "final" / "PAPER_FULL_RESULTS.csv")
    if len(legacy) != 31:
        raise RuntimeError(f"Corrupt source campaign: expected 31 rows, found {len(legacy)}")
    rows: list[dict[str, Any]] = []
    for index, source in enumerate(legacy, start=1):
        family = source["target_structure_family"]
        spp = source.get("spp_final_verdict") or source.get("spp_conversion_status") or "NOT_AVAILABLE"
        solver_status = source.get("solver_solver_status") or "NOT_AVAILABLE"
        rows.append({
            "final_row_id": f"PFRV1-{index:03d}",
            "source_campaign": "paper_full_sca_v1",
            "source_task_id": source["candidate_id"],
            "experiment_group": source["experiment"],
            "natural_language_request": source["prompt"],
            "structured_intent_hash": "NOT_AVAILABLE_LEGACY",
            "target_formula": source["target_formula"],
            "target_family": family,
            "target_topology": source.get("topology_topology_policy") or POLICY_MAP.get(family.lower(), "GENERIC_SCAFFOLD_ONLY"),
            "requested_space_group": source["target_space_group"],
            "scaffold_id": source.get("scaffold_id") or "NOT_AVAILABLE",
            "scaffold_version": "NOT_AVAILABLE_LEGACY",
            "retrieval_corpus": source.get("retrieval_corpus") or "NOT_AVAILABLE",
            "spp_status": spp,
            "solver_mode": source.get("solver_mode") or "NOT_AVAILABLE",
            "solver_status": solver_status,
            "solver_certificate_available": solver_status == "OPTIMAL" and truth(source.get("solver_optimal")) and truth(source.get("solver_objective_parity")),
            "generated_cif_path": source["cif_path"],
            "expected_cif_sha256": source["cif_sha256"],
            "trace_bundle_path": source["traceable_bundle_dir"],
            "source_result_path": str(SCA_CAMPAIGN / "final" / "PAPER_FULL_RESULTS.jsonl"),
        })
    demo_rows = read_csv(DEMO / "NASICON_DEMO_RESULTS.csv")
    demo_tasks = {row["task_id"]: row for row in read_csv(DEMO / "NASICON_DEMO_TASKS.csv")}
    if {row["task_id"] for row in demo_rows} != {"E4_A2", "E4_C2", "E4_F1"}:
        raise RuntimeError("Corrupt NASICON demo results: expected E4_A2, E4_C2, E4_F1")
    for source in sorted(demo_rows, key=lambda row: row["task_id"]):
        task = demo_tasks[source["task_id"]]
        index = len(rows) + 1
        rows.append({
            "final_row_id": f"PFRV1-{index:03d}",
            "source_campaign": "nasicon_demo",
            "source_task_id": source["task_id"],
            "experiment_group": "Experiment 4 NASICON specialist demonstration",
            "natural_language_request": task["natural_language_request"],
            "structured_intent_hash": task["structured_intent_hash"],
            "target_formula": source["target_formula"],
            "target_family": "nasicon",
            "target_topology": task["topology_policy"],
            "requested_space_group": source["requested_symmetry"],
            "scaffold_id": source["scaffold_id"],
            "scaffold_version": source["scaffold_version"],
            "retrieval_corpus": source["retrieval_database"],
            "spp_status": "NO_SPP",
            "solver_mode": "gurobi_feasibility_milp",
            "solver_status": source["solver_status"],
            "solver_certificate_available": truth(source["certificate_complete"]),
            "generated_cif_path": source["generated_cif_path"],
            "expected_cif_sha256": source["raw_cif_sha256"],
            "trace_bundle_path": str(DEMO / "tasks" / source["task_id"]),
            "source_result_path": str(DEMO / "NASICON_DEMO_RESULTS.jsonl"),
        })
    if len(rows) != 34 or len({row["final_row_id"] for row in rows}) != 34:
        raise RuntimeError(f"Final workflow manifest is not one-to-one: {len(rows)} rows")
    return rows


def verify_manifest(base: Path, manifest_path: Path, label: str) -> list[dict[str, Any]]:
    checks = []
    for row in read_csv(manifest_path):
        rel = row.get("relative_path") or row.get("path")
        expected = row["sha256"]
        path = Path(rel)
        if not path.is_absolute():
            path = base / path
        actual = sha256(path) if path.is_file() else ""
        checks.append({
            "category": label, "identifier": rel, "path": str(path),
            "expected_sha256": expected, "actual_sha256": actual,
            "status": "PASS" if actual == expected else "FAIL",
        })
    return checks


def protected_gate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.extend(verify_manifest(SCA_CAMPAIGN, SCA_CAMPAIGN / "final" / "OUTPUT_HASH_MANIFEST.csv", "frozen_full_sca_artifact"))
    checks.extend(verify_manifest(DEMO, DEMO / "NASICON_DEMO_OUTPUT_HASH_MANIFEST.csv", "frozen_nasicon_demo_artifact"))
    for row in read_csv(DEMO / "PRE_GENERATION_HASH_CHECK.csv"):
        raw_path = row["path"].strip()
        path = Path(raw_path) if raw_path else None
        # CIFs and other file-backed records are recomputed here. Database- and
        # archive-member content hashes have no standalone filesystem path; the
        # protected demo output manifest above freezes the UTF-8 verifier CSV,
        # whose expected/actual equality is the recorded content verification.
        if path is not None and path.is_file():
            actual = sha256(path)
            verification = "RECOMPUTED_FILE_SHA256"
        elif row["status"] == "PASS" and row["actual_sha256"] == row["expected_sha256"]:
            actual = row["actual_sha256"]
            verification = "PROTECTED_CONTENT_GATE_RECORD"
        else:
            actual = ""
            verification = "UNRESOLVED"
        checks.append({
            "category": f"nasicon_protected_{row['category']}", "identifier": row["identifier"],
            "path": raw_path, "verification_method": verification,
            "expected_sha256": row["expected_sha256"], "actual_sha256": actual,
            "status": "PASS" if actual == row["expected_sha256"] else "FAIL",
        })
    for row in rows:
        path = Path(row["generated_cif_path"])
        actual = sha256(path) if path.is_file() else ""
        checks.append({
            "category": "workflow_candidate_cif", "identifier": row["final_row_id"], "path": str(path),
            "expected_sha256": row["expected_cif_sha256"], "actual_sha256": actual,
            "status": "PASS" if actual == row["expected_cif_sha256"] else "FAIL",
        })
        trace = Path(row["trace_bundle_path"])
        checks.append({
            "category": "workflow_trace_bundle", "identifier": row["final_row_id"], "path": str(trace),
            "expected_sha256": "DIRECTORY_PRESENT", "actual_sha256": "DIRECTORY_PRESENT" if trace.is_dir() else "",
            "status": "PASS" if trace.is_dir() else "FAIL",
        })
    failures = [row for row in checks if row["status"] != "PASS"]
    if failures:
        first = failures[0]
        raise RuntimeError(f"PROTECTED_INPUT_HASH_MISMATCH: {first['identifier']}: {first['path']}")
    return checks


def main() -> int:
    for destination in (OUT, RUNS, FIGURES):
        if destination.exists() and any(path.is_file() for path in destination.rglob("*")):
            raise RuntimeError(f"OUTPUT_PATH_COLLISION: destination contains files: {destination}")
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    rows = build_rows()
    checks = protected_gate(rows)
    write_csv(MANIFESTS / "FINAL_WORKFLOW_ROW_MANIFEST.csv", rows, ROW_FIELDS)
    write_jsonl(MANIFESTS / "FINAL_WORKFLOW_ROW_MANIFEST.jsonl", rows)
    abstention = [{
        "abstention_id": "E4_A1", "source_campaign": "nasicon_demo",
        "status": "UNSUPPORTED_ORDERED_MODEL_REQUIRES_DISORDER",
        "generated": False,
        "reason": "Ordered Si/P composition is incompatible with the scaffold's symmetry-closed orbit multiplicities.",
        "source_path": str(DEMO / "NASICON_DEMO_ABSTENTION_CASE.md"),
    }]
    write_csv(MANIFESTS / "FINAL_ABSTENTION_MANIFEST.csv", abstention)
    source_map = [
        {"source_campaign": "paper_full_sca_v1", "row_count": 31, "source_result": str(SCA_CAMPAIGN / "final" / "PAPER_FULL_RESULTS.jsonl"), "protected_manifest": str(SCA_CAMPAIGN / "final" / "OUTPUT_HASH_MANIFEST.csv")},
        {"source_campaign": "nasicon_demo", "row_count": 3, "source_result": str(DEMO / "NASICON_DEMO_RESULTS.jsonl"), "protected_manifest": str(DEMO / "NASICON_DEMO_OUTPUT_HASH_MANIFEST.csv")},
    ]
    write_csv(MANIFESTS / "FINAL_SOURCE_CAMPAIGN_MAP.csv", source_map)
    write_csv(MANIFESTS / "FINAL_PRE_RUN_HASH_CHECK.csv", checks)
    categories = Counter(row["category"] for row in checks)
    (MANIFESTS / "FINAL_PRE_RUN_HASH_CHECK.md").write_text(
        "# Final pre-run protected-input gate\n\n"
        f"Status: **PASS**. Verified {len(checks)}/{len(checks)} protected records.\n\n"
        + "\n".join(f"- `{name}`: {count}/{count} PASS" for name, count in sorted(categories.items()))
        + "\n\nNo scientific input was rewritten or normalized before verification.\n",
        encoding="utf-8",
    )
    print(json.dumps({"workflow_rows": len(rows), "generated_rows": len(rows), "abstentions": 1, "protected_checks": len(checks), "failures": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
