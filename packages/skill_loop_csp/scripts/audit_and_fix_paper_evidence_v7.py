from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sok_llm_orchestrator.experiments.paper_workflow import (  # noqa: E402
    _run_row,
    _target_anions,
)


AUDIT_COLUMNS = [
    "experiment_id",
    "row_id",
    "target_formula",
    "target_family",
    "input_text",
    "retrieval_method",
    "retrieval_result_count",
    "spp_exported_count",
    "displayed_count_v6",
    "evidence_formulas",
    "evidence_elements",
    "target_elements",
    "target_anion_family",
    "chemical_system_match_count",
    "shares_target_anion_count",
    "shares_target_cation_count",
    "prototype_family_match_count",
    "obvious_mismatch_count",
    "evidence_quality_label",
    "evidence_quality_reason",
    "needs_rerun",
    "suggested_retrieval_fix",
]


ROW_FILES_TO_ARCHIVE = [
    "input_text.txt",
    "workflow_trace.json",
    "crystaldb_query.json",
    "crystaldb_retrieval_results.json",
    "retrieved_evidence_manifest.jsonl",
    "retrieved_evidence_summary.md",
    "spp_summary.json",
    "spp_pairs.csv",
    "qlip_request.json",
    "qlip_solution.json",
    "validation_summary.json",
    "generated.cif",
]


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    fields = columns or []
    if not fields:
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def formula_elements(formula: str) -> set[str]:
    return set(re.findall(r"[A-Z][a-z]?", formula or ""))


def neighbor_elements(item: dict[str, Any]) -> set[str]:
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    elements_csv = str(meta.get("elements_csv") or "")
    elements = {part.strip() for part in elements_csv.split(",") if part.strip()}
    formula = str(meta.get("formula") or item.get("formula") or meta.get("reduced_formula") or "")
    return elements or formula_elements(formula)


def neighbor_formula(item: dict[str, Any]) -> str:
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(meta.get("formula") or item.get("formula") or meta.get("reduced_formula") or item.get("structure_id") or "")


def target_anion_family(row: dict[str, str]) -> str:
    anions = sorted(_target_anions(row))
    return ",".join(anions)


def displayed_counts_v6(package_root: Path) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    manifest = package_root / "PACKAGE_MANIFEST.csv"
    if not manifest.is_file():
        return out
    for row in read_csv(manifest):
        key = (row.get("experiment_id", ""), row.get("row_id", ""))
        try:
            out[key] = int(float(row.get("semantic_neighbour_selected_count") or 0))
        except ValueError:
            out[key] = 0
    return out


def audit_row(row: dict[str, str], displayed_v6: dict[tuple[str, str], int]) -> dict[str, Any]:
    row_dir = ROOT / "local_runs" / row["experiment_id"] / row["row_id"]
    retrieval = read_json(row_dir / "crystaldb_retrieval_results.json")
    query = retrieval.get("query") if isinstance(retrieval.get("query"), dict) else {}
    neighbors = retrieval.get("neighbors") or []
    target_elements = formula_elements(row.get("target_formula", ""))
    target_anions = _target_anions(row)
    target_cations = target_elements - target_anions
    family = str(row.get("target_family") or "").lower()
    formulas = [neighbor_formula(item) for item in neighbors]
    element_sets = [neighbor_elements(item) for item in neighbors]
    all_evidence_elements = sorted(set().union(*element_sets) if element_sets else set())
    chemical_system_match = sum(1 for elements in element_sets if target_elements <= elements)
    shares_anion = sum(1 for elements in element_sets if not target_anions or bool(target_anions & elements))
    shares_cation = sum(1 for elements in element_sets if not target_cations or bool(target_cations & elements))
    prototype_match = 0
    for item in neighbors:
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        text_doc = item.get("text_doc") if isinstance(item.get("text_doc"), dict) else {}
        blob = " ".join(str(value or "") for value in [neighbor_formula(item), meta.get("space_group"), text_doc.get("text")]).lower()
        if family and family in blob:
            prototype_match += 1
    obvious = sum(
        1
        for elements in element_sets
        if (target_anions and not (target_anions & elements)) or (target_cations and not (target_cations & elements))
    )
    spp_exported = sum(1 for item in neighbors if isinstance(item.get("cif_export"), dict) and item["cif_export"].get("status") == "exported")
    total = len(neighbors)
    anion_ratio = shares_anion / total if total else 0.0
    cation_ratio = shares_cation / total if total else 0.0
    mismatch_ratio = obvious / total if total else 1.0
    if total == 0:
        label = "bad"
        reason = "no retrieved evidence records"
    elif anion_ratio < 0.5:
        label = "bad"
        reason = f"obvious mismatch ratio {mismatch_ratio:.2f}; anion share {anion_ratio:.2f}; cation share {cation_ratio:.2f}"
    elif cation_ratio == 0 and family in {"fluorite"}:
        label = "acceptable_broad"
        reason = "same anion/prototype family evidence but no target cation analogue available in retrieved set"
    elif cation_ratio == 0:
        label = "weak"
        reason = "same anion family evidence but no target cation analogue available in retrieved set"
    elif mismatch_ratio > 0.25 or anion_ratio < 0.75:
        label = "weak"
        reason = f"mixed evidence quality; mismatch ratio {mismatch_ratio:.2f}; anion share {anion_ratio:.2f}"
    elif chemical_system_match or prototype_match:
        label = "good"
        reason = f"target anion/cation represented; chemical-system matches={chemical_system_match}; prototype matches={prototype_match}"
    else:
        label = "acceptable_broad"
        reason = "shares target anion/cation family but lacks exact chemical-system/prototype hits"
    needs_rerun = label in {"bad", "weak"}
    return {
        "experiment_id": row["experiment_id"],
        "row_id": row["row_id"],
        "target_formula": row.get("target_formula", ""),
        "target_family": row.get("target_family", ""),
        "input_text": row.get("input_text", ""),
        "retrieval_method": retrieval.get("retrieval_method") or query.get("method") or "",
        "retrieval_result_count": total,
        "spp_exported_count": spp_exported,
        "displayed_count_v6": displayed_v6.get((row["experiment_id"], row["row_id"]), ""),
        "evidence_formulas": ";".join(formulas),
        "evidence_elements": ";".join(all_evidence_elements),
        "target_elements": ";".join(sorted(target_elements)),
        "target_anion_family": target_anion_family(row),
        "chemical_system_match_count": chemical_system_match,
        "shares_target_anion_count": shares_anion,
        "shares_target_cation_count": shares_cation,
        "prototype_family_match_count": prototype_match,
        "obvious_mismatch_count": obvious,
        "evidence_quality_label": label,
        "evidence_quality_reason": reason,
        "needs_rerun": str(needs_rerun).lower(),
        "suggested_retrieval_fix": "apply strict target-anion/cation evidence policy with recorded relax steps" if needs_rerun else "",
    }


def write_audit(out_root: Path, rows: list[dict[str, Any]]) -> None:
    write_csv(out_root / "EVIDENCE_QUALITY_AUDIT.csv", rows, AUDIT_COLUMNS)
    write_json(out_root / "EVIDENCE_QUALITY_AUDIT.json", rows)
    counts = Counter(str(row["evidence_quality_label"]) for row in rows)
    lines = [
        "# Evidence Quality Audit",
        "",
        f"- Rows audited: {len(rows)}",
        f"- Good: {counts.get('good', 0)}",
        f"- Acceptable broad: {counts.get('acceptable_broad', 0)}",
        f"- Weak: {counts.get('weak', 0)}",
        f"- Bad: {counts.get('bad', 0)}",
        "",
        "## Rows Needing Review",
    ]
    review = [row for row in rows if row["evidence_quality_label"] in {"weak", "bad"}]
    if review:
        lines.extend(f"- {row['experiment_id']}/{row['row_id']}: {row['evidence_quality_label']} - {row['evidence_quality_reason']}" for row in review)
    else:
        lines.append("- None")
    (out_root / "EVIDENCE_QUALITY_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def archive_row(row: dict[str, str], stamp: str) -> Path:
    row_dir = ROOT / "local_runs" / row["experiment_id"] / row["row_id"]
    archive = row_dir / f"evidence_archive_v6_{stamp}"
    archive.mkdir(parents=True, exist_ok=True)
    for name in ROW_FILES_TO_ARCHIVE:
        source = row_dir / name
        if source.is_file():
            shutil.copy2(source, archive / name)
        elif source.is_dir():
            shutil.copytree(source, archive / name, dirs_exist_ok=True)
    return archive


def rerun_rows(rows: list[dict[str, str]], audit_rows: list[dict[str, Any]], crystaldb_root: Path, retrieval_k: int) -> list[dict[str, Any]]:
    row_by_key = {(row["experiment_id"], row["row_id"]): row for row in rows}
    decisions: list[dict[str, Any]] = []
    for audit in audit_rows:
        if str(audit.get("needs_rerun")).lower() != "true":
            continue
        key = (audit["experiment_id"], audit["row_id"])
        manifest_row = dict(row_by_key[key])
        row_dir = ROOT / "local_runs" / manifest_row["experiment_id"] / manifest_row["row_id"]
        row = read_json(row_dir / "input.json")
        row.setdefault("experiment_id", manifest_row["experiment_id"])
        row.setdefault("row_id", manifest_row["row_id"])
        archive = archive_row(row, now_stamp())
        source_db = Path(manifest_row.get("source_db_path") or ROOT.parent / "Crystal-DB" / "data" / "phase6_mp_10k.db")
        result = _run_row(
            row=row,
            source_db=source_db,
            out_root=ROOT / "local_runs" / row["experiment_id"],
            crystaldb_root=crystaldb_root,
            retrieval_k=retrieval_k,
            make_diagrams=True,
        )
        decisions.append(
            {
                "experiment_id": row["experiment_id"],
                "row_id": row["row_id"],
                "initial_label": audit["evidence_quality_label"],
                "initial_reason": audit["evidence_quality_reason"],
                "rerun_action": "rerun_with_strict_retrieval_policy",
                "archive_path": str(archive),
                "post_outcome": result.get("outcome", ""),
                "generated_cif_path": result.get("generated_cif_path", ""),
            }
        )
    return decisions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "artifacts" / "PAPER_EXPERIMENTS_FULL_SCA_MANIFEST.csv")
    parser.add_argument("--v6-package-root", type=Path, default=ROOT / "artifacts" / "paper_results_package_v6")
    parser.add_argument("--out-root", type=Path, default=ROOT / "artifacts" / "paper_results_package_v7_evidence_audit")
    parser.add_argument("--crystaldb-root", type=Path, default=ROOT.parent / "Crystal-DB")
    parser.add_argument("--retrieval-k", type=int, default=10)
    parser.add_argument("--rerun-weak-bad", action="store_true")
    args = parser.parse_args()

    rows = read_csv(args.manifest)
    displayed_v6 = displayed_counts_v6(args.v6_package_root)
    initial = [audit_row(row, displayed_v6) for row in rows]
    decisions = rerun_rows(rows, initial, args.crystaldb_root, args.retrieval_k) if args.rerun_weak_bad else []
    final = [audit_row(row, displayed_v6) for row in rows]
    write_audit(args.out_root, final)
    write_csv(args.out_root / "RERUN_DECISIONS.csv", decisions)
    write_json(args.out_root / "RERUN_DECISIONS.json", decisions)
    counts = Counter(row["evidence_quality_label"] for row in final)
    summary = [
        "# Rerun Summary",
        "",
        f"- Rerun rows: {len(decisions)}",
        f"- Final labels: good={counts.get('good', 0)}, acceptable_broad={counts.get('acceptable_broad', 0)}, weak={counts.get('weak', 0)}, bad={counts.get('bad', 0)}",
    ]
    for decision in decisions:
        summary.append(f"- {decision['experiment_id']}/{decision['row_id']}: {decision['initial_label']} -> rerun; archive `{decision['archive_path']}`")
    (args.out_root / "RERUN_SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(json.dumps({"audit_root": str(args.out_root), "rerun_count": len(decisions), "final_counts": dict(counts)}, indent=2))


if __name__ == "__main__":
    main()
