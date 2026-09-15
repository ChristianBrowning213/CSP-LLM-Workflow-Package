from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
V9 = ROOT / "artifacts" / "paper_results_package_v9"
OLD_V7 = ROOT / "artifacts" / "paper_results_package_v7"
OLD_SMOKE = ROOT / "local_runs" / "symmetry_wiring_prototype_scaffold_smoke_20260704_v2"
OLD_V3B = Path(
    r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs\paper_result_section_smoke_v3b_20260720"
)

OUT_CSV = V9 / "OLD_VS_V9_NEIGHBOUR_COMPARISON.csv"
OUT_MD = V9 / "OLD_VS_V9_NEIGHBOUR_COMPARISON.md"

TARGETS = {
    "BaTiO3",
    "SrTiO3",
    "CaTiO3",
    "MgO",
    "TiN",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def result_payload(data: dict[str, Any]) -> dict[str, Any]:
    result = data.get("result")
    return result if isinstance(result, dict) else data


def formula_of_neighbor(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    return (
        item.get("formula")
        or item.get("reduced_formula")
        or metadata.get("formula")
        or metadata.get("reduced_formula")
        or item.get("structure_id")
        or item.get("source_id")
        or ""
    )


def formulas_from_neighbors(items: list[dict[str, Any]]) -> list[str]:
    return [formula_of_neighbor(item) for item in items if formula_of_neighbor(item)]


def pipe(values: list[str]) -> str:
    return " | ".join(values)


def load_v9_indexes() -> tuple[dict[tuple[str, str], dict[str, str]], dict[tuple[str, str], list[str]], dict[tuple[str, str], list[str]]]:
    corpus = {
        (r["experiment_id"], r["row_id"]): r
        for r in read_csv(V9 / "CORPUS_SELECTION_AUDIT.csv")
    }
    selected: dict[tuple[str, str], list[str]] = {}
    displayed: dict[tuple[str, str], list[str]] = {}
    for r in read_csv(V9 / "EVIDENCE_SELECTION_MANIFEST.csv"):
        key = (r["experiment_id"], r["row_id"])
        if r["selection_decision"].lower() == "selected":
            selected.setdefault(key, []).append(r["neighbour_formula"])
        if r["selected_for_display"].lower() == "true":
            displayed.setdefault(key, []).append(r["neighbour_formula"])
    return corpus, selected, displayed


def v9_query_and_raw(exp_id: str, row_id: str) -> tuple[str, list[str], str]:
    repair_dir = V9 / "RAW_RETRIEVAL_REPAIR" / exp_id / row_id
    query_path = repair_dir / "crystaldb_query_top50.json"
    raw_path = repair_dir / "crystaldb_retrieval_results_top50.json"
    if not query_path.exists():
        query_path = ROOT / "local_runs" / exp_id / row_id / "crystaldb_query.json"
    if not raw_path.exists():
        raw_path = ROOT / "local_runs" / exp_id / row_id / "crystaldb_retrieval_results.json"

    query = ""
    if query_path.exists():
        q = read_json(query_path)
        query = q.get("retrieval_query") or q.get("query") or q.get("input_text") or ""

    raw_formulas: list[str] = []
    retrieval_api = ""
    if raw_path.exists():
        raw = result_payload(read_json(raw_path))
        raw_formulas = formulas_from_neighbors(raw.get("neighbors") or [])
        q = raw.get("query") or {}
        retrieval_api = q.get("method") or ""
        if not query:
            query = q.get("text") or ""
    return query, raw_formulas, retrieval_api


def v7_display(exp_id: str, row_id: str) -> tuple[Path, list[str], str, str, str, str, int]:
    path = OLD_V7 / "_render_bundles" / exp_id / row_id / "raw" / "crystal_csp_pack.json"
    if not path.exists():
        return path, [], "", "", "", "", 0
    payload = result_payload(read_json(path))
    export_items = (payload.get("export") or {}).get("items") or []
    formulas = [item.get("formula") or item.get("structure_id") or "" for item in export_items]
    query = payload.get("query") or {}
    query_text = query.get("text") or query.get("value") or ""
    db_path = query.get("db_path") or ""
    api = query.get("method") or "package_render_bundle_raw_export"
    local_query = ROOT / "local_runs" / exp_id / row_id / "crystaldb_query.json"
    local_raw = ROOT / "local_runs" / exp_id / row_id / "crystaldb_retrieval_results.json"
    raw_count = len(formulas)
    if local_query.exists():
        q = read_json(local_query)
        query_text = query_text or q.get("retrieval_query") or q.get("query") or q.get("input_text") or ""
        db_path = db_path or q.get("source_db") or ""
    if local_raw.exists():
        raw = result_payload(read_json(local_raw))
        raw_count = len(raw.get("neighbors") or []) or raw_count
        raw_query = raw.get("query") or {}
        query_text = query_text or raw_query.get("text") or ""
        db_path = db_path or raw_query.get("db_path") or ""
        api = raw_query.get("method") or api
    return path, [f for f in formulas if f], query_text, db_path, Path(db_path).name if db_path else "", api, raw_count


def smoke_stub_row(formula: str) -> dict[str, Any] | None:
    case = {
        "BaTiO3": "BaTiO3_perovskite",
        "NiO": "NiO_rocksalt",
        "CeO2": "CeO2_fluorite",
    }.get(formula)
    if not case:
        return None
    runs = list((OLD_SMOKE / case / "runs").glob("*"))
    if not runs:
        return None
    run = runs[0]
    req = read_json(run / "calls" / "000_crystal_csp_pack_request.json")
    resp = read_json(run / "calls" / "000_crystal_csp_pack_response.json")
    backend = resp.get("backend_status") or {}
    formulas = formulas_from_neighbors(resp.get("neighbors") or [])
    return {
        "old_source_label": "20260704_stub_smoke",
        "old_package_path": str(run),
        "old_row_id": case,
        "old_crystal_db_path": backend.get("db_path", "stub://crystal.db"),
        "old_crystal_db_name": backend.get("db_path", "stub://crystal.db"),
        "old_retrieval_api": "crystal_csp_pack stub backend",
        "old_query_text": req.get("query", ""),
        "old_raw_retrieval_count": str(len(resp.get("neighbors") or [])),
        "old_displayed_neighbour_formulas": pipe(formulas),
        "old_display_source": "manually curated/stub probe evidence displayed by crystal_csp_pack smoke response",
        "old_used_task_specific_or_mini_corpus": "yes: stub/probe corpus, not phase6_mp_10k.db",
        "embeddings_index_text_field_changed": "yes: stub://embeddings.index probe records vs phase6_mp_10k SQLite text_doc search",
        "likely_reason_old_neighbours_looked_better": (
            "The old BaTiO3 smoke used a tiny stub backend whose structure_ids were BaTiO3 probe records; "
            "it was not evidence from the broad Materials Project phase6 corpus."
        ),
    }


def v3b_mini_row(formula: str) -> dict[str, Any] | None:
    task_dir = OLD_V3B / f"result_1_common_families__common_families__{formula}"
    trace = task_dir / "retrieval_trace.json"
    task = task_dir / "task_spec.json"
    if not trace.exists() or not task.exists():
        return None
    t = read_json(task)
    r = read_json(trace)
    direct = r.get("direct_formula_matches") or []
    neighbours = r.get("structural_neighbors") or []
    formulas = formulas_from_neighbors(direct + neighbours)
    methods = r.get("retrieval_methods") or []
    return {
        "old_source_label": "v3b_result_common_families_mini_corpus",
        "old_package_path": str(task_dir),
        "old_row_id": t.get("task_id", task_dir.name),
        "old_crystal_db_path": t.get("db_path", ""),
        "old_crystal_db_name": Path(t.get("db_path", "")).name,
        "old_retrieval_api": pipe(methods),
        "old_query_text": (r.get("query") or t.get("prompt") or ""),
        "old_raw_retrieval_count": str(r.get("evidence_count") or len(formulas)),
        "old_displayed_neighbour_formulas": pipe(formulas),
        "old_display_source": "task-specific retrieval evidence/direct formula plus similarity neighbours",
        "old_used_task_specific_or_mini_corpus": "yes: result_common_families.db",
        "embeddings_index_text_field_changed": (
            "yes: mini corpus exact reduced-formula/similarity lookup vs v9 phase6 SQLite text_doc formula-family search"
        ),
        "likely_reason_old_neighbours_looked_better": (
            "The old task used a small common-family corpus seeded around benchmark families and exact reduced-formula hits, "
            "so the first evidence item is on-target and the corpus is less noisy."
        ),
    }


def v7_row(exp_id: str, row_id: str) -> dict[str, Any]:
    path, formulas, query, db_path, db_name, api, raw_count = v7_display(exp_id, row_id)
    return {
        "old_source_label": "paper_results_package_v7_raw_display",
        "old_package_path": str(path),
        "old_row_id": row_id,
        "old_crystal_db_path": db_path or "see local run raw retrieval; phase6_mp_10k.db",
        "old_crystal_db_name": db_name or "phase6_mp_10k.db",
        "old_retrieval_api": api,
        "old_query_text": query,
        "old_raw_retrieval_count": str(raw_count),
        "old_displayed_neighbour_formulas": pipe(formulas),
        "old_display_source": "raw retrieval export displayed directly in workflow figure",
        "old_used_task_specific_or_mini_corpus": "no: phase6_mp_10k.db raw retrieval display",
        "embeddings_index_text_field_changed": "no known DB/index change versus v9; display policy changed",
        "likely_reason_old_neighbours_looked_better": (
            "v7 displayed more raw retrieval exports. When those happened to be visually plausible, the figure looked fuller; "
            "v9 hides raw entries that fail the selected-evidence chemistry audit."
        ),
    }


def make_row(
    old: dict[str, Any],
    exp_id: str,
    row_id: str,
    formula: str,
    corpus: dict[tuple[str, str], dict[str, str]],
    selected: dict[tuple[str, str], list[str]],
    displayed: dict[tuple[str, str], list[str]],
) -> dict[str, str]:
    key = (exp_id, row_id)
    c = corpus[key]
    v9_query, v9_raw, raw_api = v9_query_and_raw(exp_id, row_id)
    v9_api = c.get("retrieval_api") or raw_api
    old_displayed = old["old_displayed_neighbour_formulas"].split(" | ") if old["old_displayed_neighbour_formulas"] else []
    selected_formulas = selected.get(key, [])
    if old["old_source_label"] == "20260704_stub_smoke":
        v9_worse = "not genuinely worse; old was a manually curated stub/probe display, v9 is stricter real-corpus evidence"
        fix = "Do not compare paper evidence to the stub. If desired, add a documented BaTiO3/SrTiO3/CaTiO3 mini-corpus or exact-formula-first reranker."
    elif old["old_source_label"] == "v3b_result_common_families_mini_corpus":
        v9_worse = "partly underperforming for common rows because broad phase6 text retrieval is noisier than exact-formula mini-corpus retrieval"
        fix = "Use exact reduced-formula/direct-formula retrieval first, then prototype/family similarity reranking; optionally build a documented common-family mini-corpus."
    else:
        v9_worse = "mostly stricter display, not worse generation evidence; v9 raw often still contains the same broad hits but selected display filters them"
        fix = "Keep selected-evidence display; improve phase6 ranking with exact-formula boost, element-overlap constraints, and prototype/family reranker."
    if formula == "BaTiO3":
        v9_worse = "not genuinely worse for paper evidence; old BaTiO3 looked better because the cleanest old source was a BaTiO3-labelled stub/probe run, while v9 shows only audited selected evidence from phase6"
        fix = "For BaTiO3, add an exact-formula/prototype-first retrieval path or documented titanate mini-corpus; never use the old stub probes as paper evidence."

    return {
        "old_source_label": old["old_source_label"],
        "old_package_path": old["old_package_path"],
        "v9_package_path": str(V9),
        "old_row_id": old["old_row_id"],
        "v9_row_id": row_id,
        "target_formula": formula,
        "old_crystal_db_path": old["old_crystal_db_path"],
        "old_crystal_db_name": old["old_crystal_db_name"],
        "v9_crystal_db_path": c["actual_crystal_db_path"],
        "v9_crystal_db_name": c["actual_crystal_db_name"],
        "old_retrieval_api_function_used": old["old_retrieval_api"],
        "v9_retrieval_api_function_used": v9_api,
        "old_query_text_sent_to_crystaldb": old["old_query_text"],
        "v9_query_text_sent_to_crystaldb": v9_query,
        "old_raw_retrieval_count": old["old_raw_retrieval_count"],
        "v9_raw_retrieval_count": c["raw_retrieval_count"],
        "old_displayed_neighbour_formulas": old["old_displayed_neighbour_formulas"],
        "v9_raw_neighbour_formulas": pipe(v9_raw),
        "v9_selected_evidence_formulas": pipe(selected_formulas),
        "v9_displayed_selected_formulas": pipe(displayed.get(key, [])),
        "old_displayed_neighbour_source": old["old_display_source"],
        "old_used_task_specific_or_mini_corpus_instead_of_phase6_mp_10k": old["old_used_task_specific_or_mini_corpus"],
        "embeddings_or_index_text_field_changed": old["embeddings_index_text_field_changed"],
        "likely_reason_old_neighbours_looked_better": old["likely_reason_old_neighbours_looked_better"],
        "is_v9_genuinely_worse_or_stricter": v9_worse,
        "recommended_exact_fix": fix,
    }


def write_markdown(rows: list[dict[str, str]]) -> None:
    lines = [
        "# Old vs v9 Neighbour Comparison",
        "",
        "## Summary",
        "",
        "- BaTiO3 old neighbours looked better because the cleanest older BaTiO3 source was a July 4 stub/probe run (`stub://crystal.db`) with BaTiO3-labelled probe IDs, not a real broad Crystal-DB retrieval from `phase6_mp_10k.db`.",
        "- v9 is usually stricter in what it displays: selected evidence is chemistry-audited, while v7 displayed raw retrieval exports directly.",
        "- For common rows covered by the v3b result-section smoke, the old `result_common_families.db` mini corpus was genuinely better targeted than `phase6_mp_10k.db`: it used exact reduced-formula hits plus similarity lookup on a small common-family dataset.",
        "- `phase6_mp_10k.db` is underperforming for several common rows as a first-rank display source because the SQLite text/formula-family fallback can return broad text matches with weak element/prototype relevance unless an exact-formula or chemistry-aware rerank is applied.",
        "",
        "## Recommended Fix",
        "",
        "Use a two-stage retrieval policy for common rows: exact reduced-formula/direct formula lookup first, then element-overlap plus prototype/family reranking over `phase6_mp_10k.db`; for paper figures, keep v9 selected-evidence display. If the paper wants the cleaner old common-family behavior, build a documented common-family/titanate mini corpus and label it explicitly rather than silently substituting it for the general corpus.",
        "",
        "## Row Comparisons",
        "",
        "| target | old source | old row | v9 row | old db | v9 raw | v9 selected | reason |",
        "|---|---|---|---|---|---:|---:|---|",
    ]
    for r in rows:
        reason = r["is_v9_genuinely_worse_or_stricter"].replace("|", "/")
        lines.append(
            f"| {r['target_formula']} | {r['old_source_label']} | `{r['old_row_id']}` | `{r['v9_row_id']}` | "
            f"`{r['old_crystal_db_name']}` | {r['v9_raw_retrieval_count']} | "
            f"{len([x for x in r['v9_selected_evidence_formulas'].split(' | ') if x])} | {reason} |"
        )
    lines.extend(
        [
            "",
            "## BaTiO3 Specific Explanation",
            "",
            "The old BaTiO3 run that looked clean was `local_runs/symmetry_wiring_prototype_scaffold_smoke_20260704_v2/BaTiO3_perovskite/...`, whose Crystal-DB backend reports `stub://crystal.db` and `stub://embeddings.index`. Its displayed neighbours are probe structure IDs (`mp-batio3-probe-1`, `mp-batio3-probe-2`, `mp-batio3-probe-3`) with no formula metadata and policy-blocked CIF export. That is effectively curated smoke-test evidence, not the real Materials Project general corpus.",
            "",
            "In v9, BaTiO3 uses `phase6_mp_10k.db` with query `barium titanate BaTiO3 perovskite oxide evidence`. The repaired raw retrieval returns 50 rows, but the selected-evidence layer keeps only the chemically defensible BaTiO3 evidence for display. So the apparent downgrade is mostly stricter, honest display; the raw corpus/ranker is still noisy and should be improved with exact-formula/prototype-first retrieval.",
            "",
            "## CSV",
            "",
            f"Full field-level comparison: `{OUT_CSV}`",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    corpus, selected, displayed = load_v9_indexes()
    v9_rows = [r for r in corpus.values() if r["declared_corpus_role"] == "general"]
    rows: list[dict[str, str]] = []
    for c in sorted(v9_rows, key=lambda r: (r["target_formula"], r["experiment_id"], r["row_id"])):
        exp_id = c["experiment_id"]
        row_id = c["row_id"]
        formula = c["target_formula"]
        old_sources: list[dict[str, Any]] = []
        stub = smoke_stub_row(formula)
        if stub:
            old_sources.append(stub)
        mini = v3b_mini_row(formula)
        if mini:
            old_sources.append(mini)
        if formula in TARGETS or not old_sources:
            old_sources.append(v7_row(exp_id, row_id))
        for old in old_sources:
            rows.append(make_row(old, exp_id, row_id, formula, corpus, selected, displayed))

    fieldnames = list(rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    write_markdown(rows)
    print(f"wrote {OUT_CSV} rows={len(rows)}")
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main()
