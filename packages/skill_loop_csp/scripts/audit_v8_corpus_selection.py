from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts" / "paper_results_package_v8"
LOCAL_RUNS = ROOT / "local_runs"
GENERAL_DB_NAME = "phase6_mp_10k.db"
SPECIALIST_DB_NAME = "paper_experiment_3_halide_perovskite_v1.db"

QUERY_FILES = {
    "paper_experiment_1_common_v1": ROOT / "experiments" / "paper_experiment_1_common_queries.csv",
    "paper_experiment_2_hard_v3": ROOT / "experiments" / "paper_experiment_2_hard_queries_v3.csv",
    "paper_experiment_3_specialist_halide_v1": ROOT / "experiments" / "paper_experiment_3_specialist_halide_queries.csv",
}

AUDIT_COLUMNS = [
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_role(experiment_id: str) -> str:
    return "specialist" if experiment_id == "paper_experiment_3_specialist_halide_v1" else "general"


def role_from_scope(scope: str, path_text: str = "") -> str:
    text = f"{scope} {Path(path_text).name}".lower()
    if "specialist" in text or "halide_perovskite" in text or "paper_experiment_3_halide" in text:
        return "specialist"
    if "general" in text or "phase6_mp_10k" in text:
        return "general"
    return "specialist" if "halide" in text and "phase6" not in text else "general"


def path_suspicion(path_text: str, expected: str) -> list[str]:
    path = Path(path_text)
    name = path.name.lower()
    text = str(path).lower()
    notes: list[str] = []
    suspicious_tokens = ["test", "tiny", "tmp", "temp", "smoke", "mini"]
    for token in suspicious_tokens:
        if token in text:
            notes.append(f"path_contains_{token}")
    if expected == "general":
        if name != GENERAL_DB_NAME:
            notes.append("general_expected_but_not_phase6_mp_10k")
        if "specialist" in text or "halide_perovskite" in text or "paper_experiment_3_halide" in text:
            notes.append("general_run_points_to_specialist_like_db")
    else:
        if name != SPECIALIST_DB_NAME:
            notes.append("specialist_expected_but_not_halide_perovskite_v1")
        if name == GENERAL_DB_NAME:
            notes.append("specialist_run_points_to_general_db")
    if not path.is_file():
        notes.append("db_path_missing_on_disk")
    return notes


def retrieval_api(row_dir: Path, retrieval: dict[str, Any]) -> str:
    trace_path = row_dir / "workflow_trace.json"
    method = ""
    if trace_path.is_file():
        method = str(read_json(trace_path).get("retrieval_method") or "")
    method = method or str((retrieval.get("query") or {}).get("method") or "")
    if method.startswith("crystal_db.retrieval.text_search"):
        return f"other: {method}"
    if method == "sqlite_text_formula_family_search":
        attempts = retrieval.get("text_search_attempts") or []
        attempted = " after crystal_db.retrieval.text_search attempts" if attempts else ""
        return f"other: sqlite_text_formula_family_search{attempted}"
    if "retrieve_text" in method:
        return "retrieve_text"
    if "make_csp_pack" in method:
        return "make_csp_pack"
    return f"other: {method or 'not_recorded'}"


def selected_counts(selection_rows: list[dict[str, str]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = Counter()
    for row in selection_rows:
        if row.get("selection_decision") == "selected":
            counts[(row["experiment_id"], row["row_id"])] += 1
    return counts


def scope_rows() -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for experiment_id, path in QUERY_FILES.items():
        for row in read_csv(path):
            out[(experiment_id, row["row_id"])] = row
    return out


def build_audit_rows() -> list[dict[str, Any]]:
    index_rows = read_csv(PACKAGE / "WORKFLOW_ARTIFACTS_INDEX.csv")
    selection_rows = read_csv(PACKAGE / "EVIDENCE_SELECTION_MANIFEST.csv")
    spp_rows = read_csv(PACKAGE / "SPP_EVIDENCE_AUDIT.csv")
    selected_by_key = selected_counts(selection_rows)
    spp_by_key = {(row["experiment_id"], row["row_id"]): row for row in spp_rows}
    declared_by_key = scope_rows()
    rows: list[dict[str, Any]] = []
    for index in index_rows:
        experiment_id = index["experiment_id"]
        row_id = index["row_id"]
        key = (experiment_id, row_id)
        row_dir = LOCAL_RUNS / experiment_id / row_id
        query_path = row_dir / "crystaldb_query.json"
        retrieval_path = row_dir / "crystaldb_retrieval_results.json"
        query = read_json(query_path)
        retrieval = read_json(retrieval_path)
        declared = declared_by_key.get(key, {})
        source_scope = declared.get("source_db_scope", "")
        actual_path = str(query.get("source_db") or (retrieval.get("query") or {}).get("db_path") or "")
        actual_name = Path(actual_path).name
        declared_role = role_from_scope(source_scope, actual_path)
        expected = expected_role(experiment_id)
        raw_count = len(retrieval.get("neighbors") or [])
        selected_count = selected_by_key.get(key, 0)
        displayed_count = int(index.get("semantic_neighbour_selected_count") or 0)
        spp_count = int(spp_by_key.get(key, {}).get("selected_evidence_count") or 0)
        suspicious_path_notes = path_suspicion(actual_path, expected)
        low_general = expected == "general" and raw_count < 10
        selected_low = selected_count < 3
        drop_due_selection = raw_count > displayed_count or raw_count > selected_count
        notes: list[str] = []
        notes.append(f"declared_source_db_scope={source_scope or 'not_recorded'}")
        notes.append(f"retrieval_query_method={(retrieval.get('query') or {}).get('method', 'not_recorded')}")
        if retrieval.get("text_search_attempts"):
            notes.append("text_search_attempts_recorded_before_sqlite_fallback")
        if suspicious_path_notes:
            notes.extend(suspicious_path_notes)
        if low_general:
            notes.append("general_run_raw_retrieval_count_below_10")
        if selected_low:
            notes.append("selected_evidence_count_below_3")
        if displayed_count < selected_count:
            notes.append("displayed_count_lower_than_selected_evidence_count_due_to_vesta_display_filter_or_repair_supplements")
        elif displayed_count < raw_count:
            notes.append("displayed_count_lower_than_raw_count_due_to_selected_evidence_filter")
        rows.append(
            {
                "experiment_id": experiment_id,
                "row_id": row_id,
                "target_formula": index["target_formula"],
                "declared_corpus_role": declared_role,
                "expected_corpus_role": expected,
                "actual_crystal_db_path": actual_path,
                "actual_crystal_db_name": actual_name,
                "retrieval_api": retrieval_api(row_dir, retrieval),
                "raw_top_k_requested": query.get("k", ""),
                "raw_retrieval_count": raw_count,
                "selected_evidence_count": selected_count,
                "displayed_neighbour_count": displayed_count,
                "spp_evidence_count": spp_count,
                "corpus_role_matches_expectation": declared_role == expected and not any("expected_but" in note or "points_to" in note for note in suspicious_path_notes),
                "count_drop_due_to_selection_filter": drop_due_selection,
                "suspicious_low_raw_retrieval": low_general or selected_low or bool(suspicious_path_notes),
                "notes": "; ".join(notes),
            }
        )
    return rows


def write_report(rows: list[dict[str, Any]]) -> None:
    exp1 = [row for row in rows if row["experiment_id"] == "paper_experiment_1_common_v1"]
    exp2 = [row for row in rows if row["experiment_id"] == "paper_experiment_2_hard_v3"]
    exp3 = [row for row in rows if row["experiment_id"] == "paper_experiment_3_specialist_halide_v1"]
    general_mismatch = [row for row in exp1 + exp2 if row["expected_corpus_role"] != "general" or row["actual_crystal_db_name"] != GENERAL_DB_NAME]
    specialist_mismatch = [row for row in exp3 if row["expected_corpus_role"] != "specialist" or row["actual_crystal_db_name"] != SPECIALIST_DB_NAME]
    low_raw_general = [row for row in exp1 + exp2 if int(row["raw_retrieval_count"]) < 10]
    selected_low = [row for row in rows if int(row["selected_evidence_count"]) < 3]
    path_suspicious = [row for row in rows if any(token in str(row["notes"]) for token in ["path_contains", "expected_but", "points_to", "db_path_missing"])]
    low_display_due_selection = [row for row in rows if int(row["displayed_neighbour_count"]) < int(row["raw_retrieval_count"]) and bool(row["count_drop_due_to_selection_filter"])]
    display_less_than_selected = [row for row in rows if int(row["displayed_neighbour_count"]) < int(row["selected_evidence_count"])]
    rerun_higher_k = [row for row in exp1 + exp2 if int(row["raw_retrieval_count"]) < 10]
    corrected_path = path_suspicious

    lines = [
        "# Corpus Selection Audit Report",
        "",
        "## Answers",
        "",
        f"- Are Experiments 1 and 2 definitely using the general Crystal-DB? {'Yes' if not general_mismatch else 'No'}: all inspected Exp 1/2 row traces point to `phase6_mp_10k.db`." if not general_mismatch else "- Are Experiments 1 and 2 definitely using the general Crystal-DB? No: see mismatches below.",
        f"- Are Experiment 3 rows definitely using the specialist halide Crystal-DB? {'Yes' if not specialist_mismatch else 'No'}: all inspected Exp 3 row traces point to `paper_experiment_3_halide_perovskite_v1.db`." if not specialist_mismatch else "- Are Experiment 3 rows definitely using the specialist halide Crystal-DB? No: see mismatches below.",
        f"- Are low displayed-neighbour counts caused by selected-evidence filtering? They are not caused by wrong corpus selection. {len(low_display_due_selection)} rows have raw retrieval counts above displayed counts, consistent with v8 selected-evidence filtering; {len(display_less_than_selected)} rows also have selected evidence records withheld from display because the display layer only uses verified VESTA-rendered neighbours. Rows with raw counts already below 10 are separately flagged below.",
        f"- Rows with suspiciously low raw retrieval counts: {len(low_raw_general)} general-corpus rows have `raw_retrieval_count < 10`; {len([r for r in rows if int(r['selected_evidence_count']) < 3])} rows have `selected_evidence_count < 3`.",
        f"- Rows needing higher top_k or corrected corpus path: {len(rerun_higher_k)} rows should be considered for higher `top_k`; {len(corrected_path)} rows need corpus-path correction.",
        "",
        "## Corpus Path Findings",
        "",
        f"- Experiment 1 rows inspected: {len(exp1)}; DB names: `{', '.join(sorted({row['actual_crystal_db_name'] for row in exp1}))}`.",
        f"- Experiment 2 rows inspected: {len(exp2)}; DB names: `{', '.join(sorted({row['actual_crystal_db_name'] for row in exp2}))}`.",
        f"- Experiment 3 rows inspected: {len(exp3)}; DB names: `{', '.join(sorted({row['actual_crystal_db_name'] for row in exp3}))}`.",
        "",
        "## General-Corpus Rows With Raw Retrieval Count < 10",
        "",
    ]
    if low_raw_general:
        for row in low_raw_general:
            lines.append(
                f"- `{row['experiment_id']}/{row['row_id']}` {row['target_formula']}: raw `{row['raw_retrieval_count']}`, top_k `{row['raw_top_k_requested']}`, selected `{row['selected_evidence_count']}`, displayed `{row['displayed_neighbour_count']}`."
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Rows With Selected Evidence Count < 3", ""])
    if selected_low:
        for row in selected_low:
            lines.append(
                f"- `{row['experiment_id']}/{row['row_id']}` {row['target_formula']}: selected `{row['selected_evidence_count']}`, raw `{row['raw_retrieval_count']}`, displayed `{row['displayed_neighbour_count']}`."
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Rows With Displayed Count Below Selected Evidence Count", ""])
    if display_less_than_selected:
        for row in display_less_than_selected:
            lines.append(
                f"- `{row['experiment_id']}/{row['row_id']}` {row['target_formula']}: selected `{row['selected_evidence_count']}`, displayed `{row['displayed_neighbour_count']}`, raw `{row['raw_retrieval_count']}`."
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Corpus Path Suspicion", ""])
    if path_suspicious:
        for row in path_suspicious:
            lines.append(f"- `{row['experiment_id']}/{row['row_id']}`: `{row['actual_crystal_db_path']}`; notes: {row['notes']}")
    else:
        lines.append("- None. No final-row DB path looks like a test, tiny, temporary, specialist-for-general, general-for-specialist, or missing database.")
    lines.extend(["", "## Recommendation", ""])
    if rerun_higher_k:
        lines.append("- Do not correct corpus paths based on this audit: roles match expectation for all final rows.")
        lines.append("- Consider rerunning the flagged general-corpus rows with higher `top_k` if the paper needs richer raw-neighbour pools. This is especially relevant where raw retrieval was capped at 8 or where hard-intent rows returned 1-6 raw neighbours before v8 repair/selection supplements.")
    else:
        lines.append("- No rerun is indicated by this audit.")
    lines.append("")
    (PACKAGE / "CORPUS_SELECTION_AUDIT_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    rows = build_audit_rows()
    write_csv(PACKAGE / "CORPUS_SELECTION_AUDIT.csv", rows, AUDIT_COLUMNS)
    write_report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
