import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .bench_retrieval import load_benchmark_cases, validate_case_schema
from .db import connect, init_db


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _detect_prototype(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    for token in ("perovskite", "spinel", "laves", "wurtzite", "rocksalt", "layered"):
        if token in lowered:
            return token
    return None


DEFAULT_QUERY_KEYWORDS = [
    "perovskite",
    "spinel",
    "laves",
    "wurtzite",
    "rocksalt",
    "layered",
    "van der waals",
    "2d",
    "corner-sharing",
    "edge-sharing",
    "face-sharing",
    "octahedra",
    "tetrahedra",
    "framework",
]


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _split_sentences(text: str) -> List[str]:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return []
    return [part for part in re.split(r"(?<=[.!?])\s+", cleaned) if part]


def _contains_keyword(sentence: str, keyword_list: List[str]) -> bool:
    lowered = sentence.lower()
    return any(keyword.lower() in lowered for keyword in keyword_list)


def _build_query_from_sentences(
    sentences: List[str],
    *,
    max_chars: int,
    min_sentences: int,
    max_sentences: int,
    keyword_list: List[str],
    semantic: bool,
) -> Tuple[str, int, int]:
    if not sentences:
        return "", 0, 0
    safe_max_chars = max(1, int(max_chars))
    safe_min_sentences = max(1, int(min_sentences))
    safe_max_sentences = max(safe_min_sentences, int(max_sentences))
    selected: List[str] = [sentences[0]]
    selected_indices = {0}
    keyword_hits = 1 if _contains_keyword(sentences[0], keyword_list) else 0

    if semantic:
        keyword_indices = [
            idx
            for idx in range(1, len(sentences))
            if _contains_keyword(sentences[idx], keyword_list)
        ]
        candidate_indices = keyword_indices if keyword_indices else list(range(1, len(sentences)))
    else:
        candidate_indices = list(range(1, len(sentences)))

    for idx in candidate_indices:
        if idx in selected_indices:
            continue
        if len(selected) >= safe_max_sentences:
            break
        candidate = sentences[idx]
        candidate_joined = " ".join(selected + [candidate])
        if len(candidate_joined) > safe_max_chars:
            break
        selected.append(candidate)
        selected_indices.add(idx)
        if _contains_keyword(candidate, keyword_list):
            keyword_hits += 1
        if len(selected) >= safe_min_sentences:
            break

    if semantic and len(selected) < safe_min_sentences:
        for idx in range(1, len(sentences)):
            if idx in selected_indices or len(selected) >= safe_max_sentences:
                break
            candidate = sentences[idx]
            candidate_joined = " ".join(selected + [candidate])
            if len(candidate_joined) > safe_max_chars:
                break
            selected.append(candidate)
            selected_indices.add(idx)
            if _contains_keyword(candidate, keyword_list):
                keyword_hits += 1
            if len(selected) >= safe_min_sentences:
                break

    query = " ".join(selected).strip()
    return _normalize_whitespace(query), len(selected), keyword_hits


def build_semantic_query(
    text: str,
    *,
    max_chars: int,
    min_sentences: int,
    max_sentences: int,
    keyword_list: List[str],
) -> str:
    sentences = _split_sentences(text)
    query, _, _ = _build_query_from_sentences(
        sentences,
        max_chars=max_chars,
        min_sentences=min_sentences,
        max_sentences=max_sentences,
        keyword_list=keyword_list,
        semantic=True,
    )
    return query


def _normalize_case(case: Dict[str, Any]) -> Dict[str, Any]:
    expected = dict(case.get("expected") or {})
    normalized = {
        "case_id": str(case["case_id"]),
        "query": str(case["query"]),
        "expected": {
            "must_contain_any": [str(item) for item in expected.get("must_contain_any", [])],
            "family": expected.get("family"),
            "elements_any": [str(item) for item in expected.get("elements_any", [])],
            "structure_ids_any": [str(item) for item in expected.get("structure_ids_any", [])],
        },
        "expected_structure_ids": [str(item) for item in case.get("expected_structure_ids", [])],
        "expected_keywords": [str(item) for item in case.get("expected_keywords", [])],
        "expected_formula": case.get("expected_formula"),
        "expected_prototype": case.get("expected_prototype"),
        "tags": [str(item) for item in case.get("tags", [])],
        "notes": case.get("notes") if case.get("notes") is not None else "",
    }
    if normalized["expected"]["family"] is not None:
        normalized["expected"]["family"] = str(normalized["expected"]["family"])
    if normalized["expected_formula"] is not None:
        normalized["expected_formula"] = str(normalized["expected_formula"])
    if normalized["expected_prototype"] is not None:
        normalized["expected_prototype"] = str(normalized["expected_prototype"])
    return normalized


def normalize_cases(*, in_path: str, out_path: str) -> Dict[str, Any]:
    cases, error = load_benchmark_cases(in_path)
    if error:
        return {"errors": error, "selected": 0, "written": 0}

    best_by_id: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for case in cases or []:
        normalized = _normalize_case(case)
        blob = _canonical_json(normalized)
        existing = best_by_id.get(normalized["case_id"])
        if existing is None or blob < existing[0]:
            best_by_id[normalized["case_id"]] = (blob, normalized)

    ordered = [best_by_id[key][1] for key in sorted(best_by_id.keys())]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        for item in ordered:
            handle.write(_canonical_json(item) + "\n")

    return {
        "errors": None,
        "in_path": in_path,
        "out_path": out_path,
        "selected": len(cases or []),
        "written": len(ordered),
    }


def _sample_query(
    text: str,
    formula: Optional[str],
    space_group: Optional[str],
    *,
    query_mode: str,
    query_max_chars: int,
    query_min_sentences: int,
    query_max_sentences: int,
    keyword_list: List[str],
) -> Tuple[str, int, int]:
    sentences = _split_sentences(text)
    if sentences:
        semantic = query_mode == "semantic"
        return _build_query_from_sentences(
            sentences,
            max_chars=query_max_chars,
            min_sentences=query_min_sentences,
            max_sentences=query_max_sentences,
            keyword_list=keyword_list,
            semantic=semantic,
        )
    formula_value = (formula or "").strip()
    if formula_value:
        if space_group:
            return f"{formula_value} {space_group} crystal", 1, 0
        return f"{formula_value} crystal", 1, 0
    return "crystal structure", 1, 0


def sample_cases(
    *,
    db_path: Optional[str],
    out_path: str,
    n: int,
    text_view: str = "caption",
    text_engine: str = "caption",
    selection_mode: str = "hash",
    query_max_chars: int = 700,
    query_min_sentences: int = 2,
    query_max_sentences: int = 5,
    query_mode: str = "semantic",
    label_mode: str = "none",
) -> Dict[str, Any]:
    if n <= 0:
        n = 1
    if selection_mode != "hash":
        return {
            "errors": {"code": "invalid_selection_mode", "message": "selection_mode must be 'hash'"},
            "written": 0,
        }
    if query_mode not in ("semantic", "first_sentences"):
        return {
            "errors": {"code": "invalid_query_mode", "message": "query_mode must be 'semantic' or 'first_sentences'"},
            "written": 0,
        }
    if label_mode not in ("none", "self"):
        return {
            "errors": {"code": "invalid_label_mode", "message": "label_mode must be 'none' or 'self'"},
            "written": 0,
        }
    query_min_sentences = max(1, int(query_min_sentences))
    query_max_sentences = max(query_min_sentences, int(query_max_sentences))
    query_max_chars = max(1, int(query_max_chars))

    conn = connect(db_path)
    init_db(conn)
    rows = conn.execute(
        "SELECT td.structure_id, td.text, m.formula, m.space_group "
        "FROM text_docs td "
        "LEFT JOIN metadata m ON m.structure_id = td.structure_id "
        "WHERE td.status = 'OK' AND td.engine = ? AND td.text_view = ? "
        "ORDER BY td.structure_id ASC",
        (text_engine, text_view),
    ).fetchall()
    conn.close()

    ranked = sorted(
        rows,
        key=lambda row: (
            hashlib.sha256(str(row["structure_id"]).encode("utf-8")).hexdigest(),
            str(row["structure_id"]),
        ),
    )
    chosen = ranked[:n]
    cases: List[Dict[str, Any]] = []
    for row in chosen:
        sid = str(row["structure_id"])
        text = str(row["text"] or "")
        if not text.strip():
            continue
        formula = row["formula"]
        query, sentences_used, keyword_hits = _sample_query(
            text,
            formula,
            row["space_group"],
            query_mode=query_mode,
            query_max_chars=query_max_chars,
            query_min_sentences=query_min_sentences,
            query_max_sentences=query_max_sentences,
            keyword_list=DEFAULT_QUERY_KEYWORDS,
        )
        case = {
            "case_id": f"sample_{sid}",
            "query": query,
            "query_mode": query_mode,
            "query_max_chars": query_max_chars,
            "query_sentences_used": int(sentences_used),
            "query_keywords_hit_count": int(keyword_hits),
            "provenance": {
                "structure_id": sid,
                "formula": formula,
                "space_group": row["space_group"],
            },
            "tags": ["sampled", text_engine, text_view],
            "notes": "deterministic_hash_sample_unlabelled" if label_mode == "none" else "deterministic_hash_sample_self_labeled",
        }
        if label_mode == "self":
            case["expected_structure_ids"] = [sid]
            if formula:
                case["expected_formula"] = str(formula)
        issue = validate_case_schema(case, 1)
        if issue:
            return {"errors": {"code": "cases_invalid_schema", "message": issue}, "written": 0}
        cases.append(case)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        for item in sorted(cases, key=lambda entry: entry["case_id"]):
            handle.write(_canonical_json(item) + "\n")

    return {
        "errors": None,
        "out_path": out_path,
        "written": len(cases),
        "selection_mode": selection_mode,
        "text_engine": text_engine,
        "text_view": text_view,
        "label_mode": label_mode,
    }
