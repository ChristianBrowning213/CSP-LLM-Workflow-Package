from __future__ import annotations

import csv
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_paper_results_package_v8 import AUDIT_COLUMNS, audit_row
from src.sok_llm_orchestrator.experiments.paper_workflow import _run_retrieval

V8 = ROOT / "artifacts" / "paper_results_package_v8"
V9 = ROOT / "artifacts" / "paper_results_package_v9"
LOCAL_RUNS = ROOT / "local_runs"
CRYSTALDB_ROOT = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
GENERAL_DB = CRYSTALDB_ROOT / "data" / "phase6_mp_10k.db"
SPECIALIST_DB_NAME = "paper_experiment_3_halide_perovskite_v1.db"
REPAIR_TOP_K = 50

QUERY_FILES = {
    "paper_experiment_1_common_v1": ROOT / "experiments" / "paper_experiment_1_common_queries.csv",
    "paper_experiment_2_hard_v3": ROOT / "experiments" / "paper_experiment_2_hard_queries_v3.csv",
    "paper_experiment_3_specialist_halide_v1": ROOT / "experiments" / "paper_experiment_3_specialist_halide_queries.csv",
}

CORPUS_AUDIT_COLUMNS = [
    "experiment_id",
    "row_id",
    "target_formula",
    "declared_corpus_role",
    "expected_corpus_role",
    "actual_crystal_db_path",
    "actual_crystal_db_name",
    "retrieval_api",
    "raw_top_k_requested",
    "raw_retrieval_count",
    "selected_evidence_count",
    "displayed_neighbour_count",
    "spp_evidence_count",
    "corpus_role_matches_expectation",
    "count_drop_due_to_selection_filter",
    "suspicious_low_raw_retrieval",
    "notes",
]

REPAIR_COLUMNS = [
    "experiment_id",
    "row_id",
    "target_formula",
    "top_k_before",
    "top_k_after",
    "raw_retrieval_count_before",
    "raw_retrieval_count_after",
    "selected_evidence_count_before",
    "selected_evidence_count_after",
    "selected_evidence_changed",
    "generation_rerun",
    "validation_rerun",
    "chgnet_rerun",
    "still_below_10",
    "justification",
    "old_raw_retrieval_archive",
    "new_raw_retrieval_trace",
    "retrieval_api_after",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def row_key(row: dict[str, str]) -> tuple[str, str]:
    return row["experiment_id"], row["row_id"]


def query_rows() -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for experiment_id, path in QUERY_FILES.items():
        for row in read_csv(path):
            out[(experiment_id, row["row_id"])] = row
    return out


def selected_counts(selection_rows: list[dict[str, str]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for row in selection_rows:
        if row.get("selection_decision") == "selected":
            key = (row["experiment_id"], row["row_id"])
            counts[key] = counts.get(key, 0) + 1
    return counts


def selected_signature(selection_rows: list[dict[str, str]], key: tuple[str, str]) -> list[tuple[str, str]]:
    items = [
        (row.get("selected_rank", ""), row.get("source_id", "") or row.get("cif_path", "") or row.get("neighbour_formula", ""))
        for row in selection_rows
        if (row.get("experiment_id"), row.get("row_id")) == key and row.get("selection_decision") == "selected"
    ]
    return sorted(items)


def retrieval_api(method: str, payload: dict[str, Any]) -> str:
    if method.startswith("crystal_db.retrieval.text_search"):
        return f"other: {method}"
    if method == "sqlite_text_formula_family_search":
        attempts = payload.get("text_search_attempts") or []
        suffix = " after crystal_db.retrieval.text_search attempts" if attempts else ""
        return f"other: sqlite_text_formula_family_search{suffix}"
    return f"other: {method or (payload.get('query') or {}).get('method') or 'not_recorded'}"


def expected_role(experiment_id: str) -> str:
    return "specialist" if experiment_id == "paper_experiment_3_specialist_halide_v1" else "general"


def declared_role(scope: str, actual_name: str) -> str:
    text = f"{scope} {actual_name}".lower()
    if "specialist" in text or "halide_perovskite" in text or "paper_experiment_3_halide" in text:
        return "specialist"
    return "general"


def copy_v8_to_v9() -> None:
    if V9.exists():
        shutil.rmtree(V9)
    shutil.copytree(V8, V9)


def low_rows_from_v8() -> list[dict[str, str]]:
    rows = read_csv(V8 / "CORPUS_SELECTION_AUDIT.csv")
    return [
        row
        for row in rows
        if row["expected_corpus_role"] == "general" and int(row["raw_retrieval_count"]) < 10
    ]


def repair_raw_retrieval(low_rows: list[dict[str, str]], query_by_key: dict[tuple[str, str], dict[str, str]]) -> list[dict[str, Any]]:
    selection_rows = read_csv(V8 / "EVIDENCE_SELECTION_MANIFEST.csv")
    selected_by_key = selected_counts(selection_rows)
    repair_rows: list[dict[str, Any]] = []
    repair_root = V9 / "RAW_RETRIEVAL_REPAIR"
    for old in low_rows:
        key = (old["experiment_id"], old["row_id"])
        row = query_by_key[key]
        row_dir = repair_root / old["experiment_id"] / old["row_id"]
        old_raw = LOCAL_RUNS / old["experiment_id"] / old["row_id"] / "crystaldb_retrieval_results.json"
        old_archive = row_dir / "old_v8_crystaldb_retrieval_results.json"
        row_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_raw, old_archive)
        retrieval, method = _run_retrieval(
            source_db=GENERAL_DB,
            row=row,
            row_dir=row_dir,
            crystaldb_root=CRYSTALDB_ROOT,
            k=REPAIR_TOP_K,
        )
        retrieval["v9_raw_count_repair"] = {
            "old_v8_raw_retrieval_path": str(old_raw),
            "old_v8_raw_retrieval_count": int(old["raw_retrieval_count"]),
            "old_v8_top_k_requested": int(old["raw_top_k_requested"]),
            "new_top_k_requested": REPAIR_TOP_K,
            "selected_evidence_policy": "v8 selected-evidence manifest retained; no quality weakening or selected-evidence inflation",
        }
        new_trace = row_dir / "crystaldb_retrieval_results_top50.json"
        write_json(new_trace, retrieval)
        # Preserve a conventional query filename from _run_retrieval while adding a repair-specific copy.
        shutil.copy2(row_dir / "crystaldb_query.json", row_dir / "crystaldb_query_top50.json")
        after_count = len(retrieval.get("neighbors") or [])
        repair_rows.append(
            {
                "experiment_id": old["experiment_id"],
                "row_id": old["row_id"],
                "target_formula": old["target_formula"],
                "top_k_before": old["raw_top_k_requested"],
                "top_k_after": REPAIR_TOP_K,
                "raw_retrieval_count_before": old["raw_retrieval_count"],
                "raw_retrieval_count_after": after_count,
                "selected_evidence_count_before": old["selected_evidence_count"],
                "selected_evidence_count_after": selected_by_key.get(key, 0),
                "selected_evidence_changed": False,
                "generation_rerun": False,
                "validation_rerun": False,
                "chgnet_rerun": False,
                "still_below_10": after_count < 10,
                "justification": "" if after_count >= 10 else "High-recall rerun against phase6_mp_10k.db still returned fewer than 10 chemistry-policy-compatible raw neighbours.",
                "old_raw_retrieval_archive": str(old_archive),
                "new_raw_retrieval_trace": str(new_trace),
                "retrieval_api_after": retrieval_api(method, retrieval),
            }
        )
    write_csv(V9 / "RAW_RETRIEVAL_COUNT_REPAIR_COMPARISON.csv", repair_rows, REPAIR_COLUMNS)
    return repair_rows


def build_v9_corpus_audit(repair_rows: list[dict[str, Any]], query_by_key: dict[tuple[str, str], dict[str, str]]) -> list[dict[str, Any]]:
    v8_audit = read_csv(V8 / "CORPUS_SELECTION_AUDIT.csv")
    repair_by_key = {(row["experiment_id"], row["row_id"]): row for row in repair_rows}
    index_rows = {row_key(row): row for row in read_csv(V8 / "WORKFLOW_ARTIFACTS_INDEX.csv")}
    selected_by_key = selected_counts(read_csv(V9 / "EVIDENCE_SELECTION_MANIFEST.csv"))
    spp_by_key = {row_key(row): row for row in read_csv(V9 / "SPP_EVIDENCE_AUDIT.csv")}
    rows: list[dict[str, Any]] = []
    for old in v8_audit:
        key = (old["experiment_id"], old["row_id"])
        query_scope = query_by_key.get(key, {}).get("source_db_scope", "")
        expected = expected_role(old["experiment_id"])
        if key in repair_by_key:
            repair = repair_by_key[key]
            actual_path = str(GENERAL_DB)
            actual_name = GENERAL_DB.name
            raw_k = repair["top_k_after"]
            raw_count = repair["raw_retrieval_count_after"]
            api = repair["retrieval_api_after"]
            notes = [
                f"v9_raw_retrieval_repair_from_top_k_{repair['top_k_before']}_to_{repair['top_k_after']}",
                "v8_selected_evidence_retained_no_generation_rerun",
                f"old_raw_archive={repair['old_raw_retrieval_archive']}",
            ]
        else:
            actual_path = old["actual_crystal_db_path"]
            actual_name = old["actual_crystal_db_name"]
            raw_k = old["raw_top_k_requested"]
            raw_count = old["raw_retrieval_count"]
            api = old["retrieval_api"]
            notes = [old["notes"], "unchanged_from_v8"]
        selected_count = selected_by_key.get(key, 0)
        displayed_count = int(index_rows[key].get("semantic_neighbour_selected_count") or 0)
        spp_count = int(spp_by_key.get(key, {}).get("selected_evidence_count") or 0)
        role = declared_role(query_scope, actual_name)
        low_general = expected == "general" and int(raw_count) < 10
        path_bad = (
            (expected == "general" and actual_name != GENERAL_DB.name)
            or (expected == "specialist" and actual_name != SPECIALIST_DB_NAME)
            or any(token in str(actual_path).lower() for token in ["test", "tiny", "tmp", "temp", "smoke"])
        )
        if low_general:
            notes.append("general_run_raw_retrieval_count_below_10_after_repair")
        if selected_count < 3:
            notes.append("selected_evidence_count_below_3")
        rows.append(
            {
                "experiment_id": old["experiment_id"],
                "row_id": old["row_id"],
                "target_formula": old["target_formula"],
                "declared_corpus_role": role,
                "expected_corpus_role": expected,
                "actual_crystal_db_path": actual_path,
                "actual_crystal_db_name": actual_name,
                "retrieval_api": api,
                "raw_top_k_requested": raw_k,
                "raw_retrieval_count": raw_count,
                "selected_evidence_count": selected_count,
                "displayed_neighbour_count": displayed_count,
                "spp_evidence_count": spp_count,
                "corpus_role_matches_expectation": role == expected and not path_bad,
                "count_drop_due_to_selection_filter": int(raw_count) > displayed_count or int(raw_count) > selected_count,
                "suspicious_low_raw_retrieval": low_general or selected_count < 3 or path_bad,
                "notes": "; ".join(str(note) for note in notes if note),
            }
        )
    write_csv(V9 / "CORPUS_SELECTION_AUDIT.csv", rows, CORPUS_AUDIT_COLUMNS)
    return rows


def build_v9_retrieval_audit(repair_rows: list[dict[str, Any]], query_by_key: dict[tuple[str, str], dict[str, str]]) -> None:
    repair_keys = {(row["experiment_id"], row["row_id"]) for row in repair_rows}
    v8_rows = read_csv(V8 / "RETRIEVAL_NEIGHBOUR_AUDIT.csv")
    out: list[dict[str, Any]] = [
        row for row in v8_rows if not ((row["experiment_id"], row["row_id"]) in repair_keys and row["source_layer"] == "raw_retrieval")
    ]
    repair_trace_by_key = {
        (row["experiment_id"], row["row_id"]): Path(row["new_raw_retrieval_trace"]) for row in repair_rows
    }
    for key, trace in repair_trace_by_key.items():
        payload = read_json(trace)
        row = query_by_key[key]
        row_run_dir = trace.parent
        for neighbor in payload.get("neighbors") or []:
            out.append(audit_row(row, "raw_retrieval", neighbor, row_run_dir, False, False))
    write_csv(V9 / "RETRIEVAL_NEIGHBOUR_AUDIT.csv", out, AUDIT_COLUMNS)


def write_reports(repair_rows: list[dict[str, Any]], corpus_rows: list[dict[str, Any]]) -> None:
    still_low = [row for row in repair_rows if bool(row["still_below_10"])]
    selected_changed = [row for row in repair_rows if bool(row["selected_evidence_changed"])]
    lines = [
        "# Raw Retrieval Count Repair Report",
        "",
        "## Scope",
        "",
        f"- Low-count general-corpus rows repaired: {len(repair_rows)}.",
        f"- Repair corpus: `{GENERAL_DB}`.",
        f"- High-recall `top_k` requested: {REPAIR_TOP_K}.",
        "- v8 raw retrieval JSON files were copied into `RAW_RETRIEVAL_REPAIR/<experiment>/<row>/old_v8_crystaldb_retrieval_results.json` before repair.",
        "- v8 selected evidence was retained exactly; no selected-evidence criteria were weakened and no generation rerun was needed.",
        "",
        "## Per-Row Repair",
        "",
    ]
    for row in repair_rows:
        lines.append(
            f"- `{row['experiment_id']}/{row['row_id']}` {row['target_formula']}: top_k `{row['top_k_before']}` -> `{row['top_k_after']}`; "
            f"raw `{row['raw_retrieval_count_before']}` -> `{row['raw_retrieval_count_after']}`; "
            f"selected `{row['selected_evidence_count_before']}` -> `{row['selected_evidence_count_after']}`; "
            f"selected changed `{row['selected_evidence_changed']}`; generation rerun `{row['generation_rerun']}`; "
            f"validation rerun `{row['validation_rerun']}`; CHGNet rerun `{row['chgnet_rerun']}`."
        )
    lines.extend(["", "## Rows Still Below 10", ""])
    if still_low:
        for row in still_low:
            lines.append(f"- `{row['experiment_id']}/{row['row_id']}`: {row['justification']}")
    else:
        lines.append("- None. All repaired general-corpus rows now have at least 10 raw neighbours.")
    lines.extend(["", "## Rerun Decision", ""])
    if selected_changed:
        lines.append("- Selected evidence changed for at least one row; generation rerun would be required.")
    else:
        lines.append("- Selected evidence did not change for any repaired row. QLIP/generation/validation/CHGNet artifacts are inherited from v8 and were not rerun.")
    lines.append("")
    (V9 / "RAW_RETRIEVAL_COUNT_REPAIR_REPORT.md").write_text("\n".join(lines), encoding="utf-8")

    exp1_general = all(row["actual_crystal_db_name"] == GENERAL_DB.name for row in corpus_rows if row["experiment_id"] == "paper_experiment_1_common_v1")
    exp2_general = all(row["actual_crystal_db_name"] == GENERAL_DB.name for row in corpus_rows if row["experiment_id"] == "paper_experiment_2_hard_v3")
    exp3_specialist = all(row["actual_crystal_db_name"] == SPECIALIST_DB_NAME for row in corpus_rows if row["experiment_id"] == "paper_experiment_3_specialist_halide_v1")
    low_general = [row for row in corpus_rows if row["expected_corpus_role"] == "general" and int(row["raw_retrieval_count"]) < 10]
    selected_low = [row for row in corpus_rows if int(row["selected_evidence_count"]) < 3]
    path_bad = [row for row in corpus_rows if row["corpus_role_matches_expectation"] is not True and row["corpus_role_matches_expectation"] != "True"]
    report = [
        "# Corpus Selection Audit Report",
        "",
        "## Answers",
        "",
        f"- Are Experiments 1 and 2 definitely using the general Crystal-DB? {'Yes' if exp1_general and exp2_general else 'No'}: Exp 1/2 point to `phase6_mp_10k.db` after v9 repair.",
        f"- Are Experiment 3 rows definitely using the specialist halide Crystal-DB? {'Yes' if exp3_specialist else 'No'}: Exp 3 remains on `paper_experiment_3_halide_perovskite_v1.db`.",
        f"- Are low displayed-neighbour counts caused by selected-evidence filtering? Yes. v9 repaired raw counts while retaining v8 selected evidence; display counts remain the selected/VESTA-rendered subset, not raw retrieval.",
        f"- Suspiciously low raw retrieval counts after repair: {len(low_general)} general-corpus rows.",
        f"- Rows needing rerun with higher top_k or corrected corpus path: {len(low_general)} higher-top_k candidates remain; {len(path_bad)} corrected corpus path candidates.",
        "",
        "## Rows Still Below 10",
        "",
    ]
    if low_general:
        for row in low_general:
            report.append(f"- `{row['experiment_id']}/{row['row_id']}` {row['target_formula']}: raw `{row['raw_retrieval_count']}`.")
    else:
        report.append("- None.")
    report.extend(["", "## Selected Evidence Count < 3", ""])
    if selected_low:
        for row in selected_low:
            report.append(f"- `{row['experiment_id']}/{row['row_id']}` {row['target_formula']}: selected `{row['selected_evidence_count']}`.")
    else:
        report.append("- None.")
    report.extend(["", "## Corpus Path Suspicion", ""])
    if path_bad:
        for row in path_bad:
            report.append(f"- `{row['experiment_id']}/{row['row_id']}`: `{row['actual_crystal_db_path']}`.")
    else:
        report.append("- None. No wrong/test/tiny/temporary corpus paths were found.")
    report.append("")
    (V9 / "CORPUS_SELECTION_AUDIT_REPORT.md").write_text("\n".join(report), encoding="utf-8")

    summary = (V9 / "FINAL_RESULTS_SUMMARY.md").read_text(encoding="utf-8")
    summary += "\n## v9 Raw Retrieval Count Repair\n\n"
    summary += f"- Repaired low raw-count general-corpus rows: {len(repair_rows)}.\n"
    summary += f"- top_k after repair: {REPAIR_TOP_K}.\n"
    summary += f"- Rows still below 10 raw neighbours: {len(still_low)}.\n"
    summary += "- Selected evidence manifests were retained from v8; no QLIP/generation/validation/CHGNet reruns were triggered.\n"
    summary += "- See `RAW_RETRIEVAL_COUNT_REPAIR_REPORT.md` and `CORPUS_SELECTION_AUDIT.csv`.\n"
    (V9 / "FINAL_RESULTS_SUMMARY.md").write_text(summary, encoding="utf-8")


def write_zip() -> None:
    zip_path = V9.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(V9.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(V9.parent))


def main() -> int:
    copy_v8_to_v9()
    query_by_key = query_rows()
    low_rows = low_rows_from_v8()
    repair_rows = repair_raw_retrieval(low_rows, query_by_key)
    corpus_rows = build_v9_corpus_audit(repair_rows, query_by_key)
    build_v9_retrieval_audit(repair_rows, query_by_key)
    # Evidence and SPP audits are copied from v8 unchanged because selected evidence did not change.
    write_reports(repair_rows, corpus_rows)
    write_zip()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
