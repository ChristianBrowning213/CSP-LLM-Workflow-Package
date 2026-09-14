import csv
import hashlib
import json
import math
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from .csp_pack import derive_hints_for_neighbors
from .db import connect, init_db
from .embeddings import DEFAULT_MODEL_NAME, resolve_embed_engine, resolve_model_version
from .query_cache import get_cached_query_vector
from .retrieval import count_candidate_embeddings, text_search
from .runlog import RunLogger
from .utils import parse_formula


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fatal_error(code: str, message: str, diagnostics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    details = diagnostics or {}
    return {
        "run_id": None,
        "config": None,
        "summary": None,
        "per_case": [],
        "errors": {
            "code": code,
            "message": message,
            "diagnostics": details,
            "details": details,
            "remediation": {
                "steps": [
                    "Verify --cases points to a valid JSONL file.",
                    "Verify the DB exists and contains text_docs/text_embeddings/provenance tables.",
                ]
            },
        },
    }


def _validate_case_schema(case: Dict[str, Any], line_no: int) -> Optional[str]:
    if not isinstance(case, dict):
        return f"line {line_no}: case must be an object"
    if not case.get("case_id") or not isinstance(case.get("case_id"), str):
        return f"line {line_no}: missing string case_id"
    if not case.get("query") or not isinstance(case.get("query"), str):
        return f"line {line_no}: missing string query"
    expected = case.get("expected")
    if expected is not None:
        if not isinstance(expected, dict):
            return f"line {line_no}: expected must be an object"
        if "must_contain_any" in expected and not isinstance(expected["must_contain_any"], list):
            return f"line {line_no}: expected.must_contain_any must be a list"
        if "elements_any" in expected and not isinstance(expected["elements_any"], list):
            return f"line {line_no}: expected.elements_any must be a list"
        if "structure_ids_any" in expected and not isinstance(expected["structure_ids_any"], list):
            return f"line {line_no}: expected.structure_ids_any must be a list"
        if "family" in expected and expected["family"] is not None and not isinstance(expected["family"], str):
            return f"line {line_no}: expected.family must be a string"
    if "expected_structure_ids" in case and not isinstance(case["expected_structure_ids"], list):
        return f"line {line_no}: expected_structure_ids must be a list"
    if "expected_structure_ids" in case and isinstance(case["expected_structure_ids"], list):
        if any(not isinstance(item, str) for item in case["expected_structure_ids"]):
            return f"line {line_no}: expected_structure_ids must be a list of strings"
    if "expected_keywords" in case and not isinstance(case["expected_keywords"], list):
        return f"line {line_no}: expected_keywords must be a list"
    if "expected_formula" in case and case["expected_formula"] is not None and not isinstance(case["expected_formula"], str):
        return f"line {line_no}: expected_formula must be a string"
    if "expected_prototype" in case and case["expected_prototype"] is not None and not isinstance(case["expected_prototype"], str):
        return f"line {line_no}: expected_prototype must be a string"
    if "tags" in case and not isinstance(case["tags"], list):
        return f"line {line_no}: tags must be a list"
    if "notes" in case and case["notes"] is not None and not isinstance(case["notes"], str):
        return f"line {line_no}: notes must be a string"
    if "query_mode" in case and not isinstance(case["query_mode"], str):
        return f"line {line_no}: query_mode must be a string"
    if "query_max_chars" in case and not isinstance(case["query_max_chars"], int):
        return f"line {line_no}: query_max_chars must be an integer"
    if "query_sentences_used" in case and not isinstance(case["query_sentences_used"], int):
        return f"line {line_no}: query_sentences_used must be an integer"
    if "query_keywords_hit_count" in case and not isinstance(case["query_keywords_hit_count"], int):
        return f"line {line_no}: query_keywords_hit_count must be an integer"
    return None


def validate_case_schema(case: Dict[str, Any], line_no: int) -> Optional[str]:
    return _validate_case_schema(case, line_no)


def load_benchmark_cases(cases_path: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
    if not os.path.exists(cases_path):
        return None, {"code": "cases_unreadable", "message": f"cases file not found: {cases_path}"}
    cases: List[Dict[str, Any]] = []
    try:
        with open(cases_path, "r", encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    case = json.loads(line)
                except json.JSONDecodeError as exc:
                    return None, {"code": "cases_invalid_schema", "message": f"line {line_no}: {exc}"}
                issue = _validate_case_schema(case, line_no)
                if issue:
                    return None, {"code": "cases_invalid_schema", "message": issue}
                cases.append(case)
    except Exception as exc:  # pylint: disable=broad-except
        return None, {"code": "cases_unreadable", "message": str(exc)}
    if not cases:
        return None, {"code": "cases_invalid_schema", "message": "no valid cases in file"}
    return cases, None


def _check_required_tables(db_path: Optional[str]) -> Optional[Dict[str, Any]]:
    conn = connect(db_path)
    init_db(conn)
    required = {"text_docs", "text_embeddings", "provenance", "metadata"}
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    conn.close()
    existing = {row["name"] for row in rows}
    missing = sorted(required - existing)
    if missing:
        return {"code": "db_schema_missing", "message": "required tables missing", "diagnostics": {"missing": missing}}
    return None


def _formula_elements(formula: Optional[str]) -> List[str]:
    if not formula:
        return []
    return sorted(parse_formula(str(formula)).keys())


def _load_case_metadata(db_path: Optional[str], structure_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not structure_ids:
        return {}
    conn = connect(db_path)
    init_db(conn)
    placeholders = ", ".join(["?"] * len(structure_ids))
    rows = conn.execute(
        "SELECT structure_id, formula, space_group FROM metadata "
        f"WHERE structure_id IN ({placeholders})",
        tuple(structure_ids),
    ).fetchall()
    conn.close()
    return {
        row["structure_id"]: {
            "formula": row["formula"],
            "elements": _formula_elements(row["formula"]),
            "space_group": row["space_group"],
        }
        for row in rows
    }


def _compute_expected_dimensions(expected: Dict[str, Any]) -> int:
    dims = 0
    if expected.get("must_contain_any"):
        dims += 1
    if expected.get("family"):
        dims += 1
    if expected.get("elements_any"):
        dims += 1
    if expected.get("structure_ids_any"):
        dims += 1
    if expected.get("expected_formula"):
        dims += 1
    return dims


def _effective_expected(case: Dict[str, Any]) -> Dict[str, Any]:
    expected = dict(case.get("expected") or {})
    keywords = [str(item) for item in case.get("expected_keywords", [])]
    if keywords:
        expected["must_contain_any"] = sorted(
            set([str(item) for item in expected.get("must_contain_any", [])] + keywords)
        )
    structure_ids = [str(item) for item in case.get("expected_structure_ids", [])]
    if structure_ids:
        expected["structure_ids_any"] = sorted(
            set([str(item) for item in expected.get("structure_ids_any", [])] + structure_ids)
        )
    expected_formula = case.get("expected_formula")
    if expected_formula and not expected.get("expected_formula"):
        expected["expected_formula"] = str(expected_formula)
    expected_prototype = case.get("expected_prototype")
    if expected_prototype and not expected.get("family"):
        expected["family"] = str(expected_prototype)
    return expected


def _neighbor_relevance(
    *,
    expected: Dict[str, Any],
    neighbor: Dict[str, Any],
    metadata: Dict[str, Any],
    text_sim_threshold: Optional[float],
    fp_sim_threshold: Optional[float],
) -> int:
    if not _passes_similarity_thresholds(
        neighbor=neighbor,
        text_sim_threshold=text_sim_threshold,
        fp_sim_threshold=fp_sim_threshold,
    ):
        return 0

    relevance = 0
    sid = str(neighbor.get("structure_id") or "")
    text_doc = neighbor.get("text_doc") or {}
    text_value = str(text_doc.get("text") or "")
    text_available = bool(text_value) and text_doc.get("error") != "redacted_by_policy"
    text_lower = text_value.lower()

    must_tokens = [str(item).lower() for item in expected.get("must_contain_any", [])]
    if must_tokens and text_available and any(token in text_lower for token in must_tokens):
        relevance += 1

    family = str(expected.get("family") or "").strip().lower()
    if family and text_available and family in text_lower:
        relevance += 1

    elements_any = [str(item) for item in expected.get("elements_any", [])]
    if elements_any and text_available:
        formula_elements = set(metadata.get("elements") or [])
        if any(element in formula_elements for element in elements_any):
            relevance += 1
        elif any(element.lower() in text_lower for element in elements_any):
            relevance += 1

    structure_ids_any = [str(item) for item in expected.get("structure_ids_any", [])]
    if structure_ids_any and sid in structure_ids_any:
        relevance += 1

    expected_formula = str(expected.get("expected_formula") or "").strip()
    if expected_formula and str(metadata.get("formula") or "").strip() == expected_formula:
        relevance += 1

    return relevance


def _passes_similarity_thresholds(
    *,
    neighbor: Dict[str, Any],
    text_sim_threshold: Optional[float],
    fp_sim_threshold: Optional[float],
) -> bool:
    if text_sim_threshold is not None:
        raw_text_score = neighbor.get("text_score", neighbor.get("score"))
        try:
            if float(raw_text_score) < float(text_sim_threshold):
                return False
        except (TypeError, ValueError):
            return False
    if fp_sim_threshold is not None and neighbor.get("fp_score") is not None:
        try:
            if float(neighbor.get("fp_score")) < float(fp_sim_threshold):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _hint_relevance(expected: Dict[str, Any], hints: Dict[str, Any]) -> int:
    relevance = 0
    must_tokens = [str(item).lower() for item in expected.get("must_contain_any", [])]
    hint_text = " ".join(
        [
            " ".join(str(item.get("name")) for item in (hints.get("family_candidates") or [])),
            " ".join(str(item.get("name")) for item in (hints.get("connectivity_keywords") or [])),
            " ".join(str(item) for item in (hints.get("symmetry_tokens") or [])),
        ]
    ).lower()
    if must_tokens and any(token in hint_text for token in must_tokens):
        relevance += 1

    family = str(expected.get("family") or "").strip().lower()
    if family and family in hint_text:
        relevance += 1

    elements_any = [str(item) for item in expected.get("elements_any", [])]
    hint_elements = set(str(item) for item in (hints.get("chemistry_tokens") or []))
    if elements_any and any(element in hint_elements for element in elements_any):
        relevance += 1

    if expected.get("structure_ids_any"):
        # Hints do not carry IDs directly; keep deterministic 0 for this component.
        pass
    return relevance


def _dcg(relevances: List[int], k: int) -> float:
    value = 0.0
    for idx, rel in enumerate(relevances[:k], start=1):
        if rel <= 0:
            continue
        value += float(rel) / math.log2(idx + 1.0)
    return value


def _score_case(
    *,
    case: Dict[str, Any],
    retrieval: Dict[str, Any],
    hints: Optional[Dict[str, Any]],
    metadata_map: Dict[str, Dict[str, Any]],
    k: int,
    text_sim_threshold: Optional[float],
    fp_sim_threshold: Optional[float],
) -> Dict[str, Any]:
    expected_ids = [str(item) for item in case.get("expected_structure_ids", []) if str(item)]
    neighbors = retrieval.get("neighbors", [])
    if expected_ids:
        expected_set = set(expected_ids)
        relevances: List[int] = []
        for neighbor in neighbors[:k]:
            sid = str(neighbor.get("structure_id") or "")
            passes = _passes_similarity_thresholds(
                neighbor=neighbor,
                text_sim_threshold=text_sim_threshold,
                fp_sim_threshold=fp_sim_threshold,
            )
            relevances.append(1 if (passes and sid in expected_set) else 0)

        hit = 1 if any(relevances) else 0
        rr = 0.0
        for idx, rel in enumerate(relevances, start=1):
            if rel > 0:
                rr = 1.0 / float(idx)
                break

        dcg = _dcg(relevances, k)
        ideal_count = min(len(expected_set), k)
        idcg = _dcg([1] * ideal_count, k)
        ndcg = (dcg / idcg) if idcg > 0 else 0.0
        top_hits = [
            {
                "rank": item.get("rank"),
                "structure_id": item.get("structure_id"),
                "score": item.get("score"),
            }
            for item in neighbors[: min(3, len(neighbors))]
        ]
        return {
            "hit": hit,
            "rr": round(rr, 8),
            "ndcg": round(ndcg, 8),
            "max_relevance": 1 if hit else 0,
            "normalized_relevance": 1.0 if hit else 0.0,
            "hint_fallback_used": False,
            "top_hits": top_hits,
        }

    expected = _effective_expected(case)
    relevances: List[int] = []
    for neighbor in neighbors[:k]:
        sid = str(neighbor.get("structure_id") or "")
        rel = _neighbor_relevance(
            expected=expected,
            neighbor=neighbor,
            metadata=metadata_map.get(sid, {}),
            text_sim_threshold=text_sim_threshold,
            fp_sim_threshold=fp_sim_threshold,
        )
        relevances.append(rel)

    fallback_used = False
    if (not any(rel > 0 for rel in relevances)) and hints and neighbors:
        hint_rel = _hint_relevance(expected, hints)
        if hint_rel > 0:
            fallback_used = True
            if relevances:
                relevances[0] = max(relevances[0], hint_rel)
            else:
                relevances = [hint_rel]

    hit = 1 if any(rel > 0 for rel in relevances) else 0
    rr = 0.0
    for idx, rel in enumerate(relevances, start=1):
        if rel > 0:
            rr = 1.0 / float(idx)
            break

    ideal = sorted(relevances, reverse=True)
    dcg = _dcg(relevances, k)
    idcg = _dcg(ideal, k)
    ndcg = (dcg / idcg) if idcg > 0 else 0.0

    max_rel = max(relevances) if relevances else 0
    dim_count = _compute_expected_dimensions(expected)
    rel_cap = max(1, dim_count)
    normalized_rel = min(max_rel, rel_cap) / float(rel_cap)
    top_hits = [
        {
            "rank": item.get("rank"),
            "structure_id": item.get("structure_id"),
            "score": item.get("score"),
        }
        for item in neighbors[: min(3, len(neighbors))]
    ]

    return {
        "hit": hit,
        "rr": round(rr, 8),
        "ndcg": round(ndcg, 8),
        "max_relevance": int(max_rel),
        "normalized_relevance": round(normalized_rel, 8),
        "hint_fallback_used": fallback_used,
        "top_hits": top_hits,
    }


def _write_exports(
    *,
    out_dir: Optional[str],
    summary: Dict[str, Any],
    per_case: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not out_dir:
        return None
    abs_out = os.path.abspath(out_dir)
    os.makedirs(abs_out, exist_ok=True)
    summary_path = os.path.join(abs_out, "summary.json")
    cases_jsonl_path = os.path.join(abs_out, "cases_scored.jsonl")
    summary_csv_path = os.path.join(abs_out, "summary.csv")
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    with open(cases_jsonl_path, "w", encoding="utf-8") as handle:
        for item in per_case:
            handle.write(_canonical_json(item) + "\n")
    with open(summary_csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "hit", "rr", "ndcg", "status"])
        for item in per_case:
            metrics = item.get("metrics") or {}
            writer.writerow([item.get("case_id"), metrics.get("hit", 0), metrics.get("rr", 0.0), metrics.get("ndcg", 0.0), item.get("status")])
    return {
        "out_dir": abs_out,
        "summary_json": summary_path,
        "cases_scored_jsonl": cases_jsonl_path,
        "summary_csv": summary_csv_path,
    }


def run_bench_retrieval(
    *,
    db_path: Optional[str],
    cases_path: str,
    k: int = 10,
    embed_engine: str = "auto",
    model_name: Optional[str] = None,
    model_version: Optional[str] = None,
    text_engine: str = "caption",
    text_view: str = "caption",
    hybrid: bool = True,
    w_text: float = 0.7,
    w_fp: float = 0.3,
    text_sim_threshold: Optional[float] = None,
    fp_sim_threshold: Optional[float] = None,
    redacted: bool = True,
    out_dir: Optional[str] = None,
    run_name: Optional[str] = None,
    query_vectors: Optional[Dict[str, List[float]]] = None,
    max_cases: int = 0,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    schema_error = _check_required_tables(db_path)
    if schema_error:
        return _fatal_error(schema_error["code"], schema_error["message"], schema_error.get("diagnostics"))

    cases, cases_error = load_benchmark_cases(cases_path)
    if cases_error:
        return _fatal_error(cases_error["code"], cases_error["message"])
    if max_cases > 0:
        cases = list(cases[:max_cases])

    if k <= 0:
        k = 1
    resolved_model_name = model_name or DEFAULT_MODEL_NAME
    resolved_embed_engine = resolve_embed_engine(embed_engine, resolved_model_name)
    resolved_model_version = resolve_model_version(
        resolved_model_name,
        model_version,
        embed_engine=resolved_embed_engine,
    )
    candidate_count = count_candidate_embeddings(
        db_path=db_path,
        text_engine=text_engine,
        text_view=text_view,
        embed_engine=resolved_embed_engine,
        model_name=resolved_model_name,
        model_version=resolved_model_version,
    )
    if candidate_count <= 0:
        return _fatal_error(
            "candidate_set_empty",
            "No candidate embeddings found for this embedding space.",
            {
                "candidate_count": 0,
                "searched_tables": ["text_docs", "text_embeddings"],
                "filter_key": {
                    "embed_engine": resolved_embed_engine,
                    "model_name": resolved_model_name,
                    "model_version": resolved_model_version,
                    "text_engine": text_engine,
                    "text_view": text_view,
                },
            },
        )

    logger = RunLogger(db_path)
    config = {
        "db_path": db_path,
        "cases": cases_path,
        "k": k,
        "engine": embed_engine,
        "model": resolved_model_name,
        "model_version": resolved_model_version,
        "text_engine": text_engine,
        "text_view": text_view,
        "hybrid": hybrid,
        "w_text": w_text,
        "w_fp": w_fp,
        "text_sim_threshold": text_sim_threshold,
        "fp_sim_threshold": fp_sim_threshold,
        "redacted": redacted,
        "out": out_dir,
        "run_name": run_name,
        "max_cases": max_cases,
    }
    run_id = logger.start_run("bench-retrieval", config)

    cases_payload = {"count": len(cases), "cases_hash": _sha256_text("\n".join(_canonical_json(item) for item in cases))}
    logger.log_step("load_cases", {"cases_path": cases_path}, cases_payload, "ok")
    logger.add_evidence("cases_loaded", cases_payload)

    per_case: List[Dict[str, Any]] = []
    failure_breakdown: Dict[str, int] = {}
    retrieval_compact: List[Dict[str, Any]] = []

    total_case_count = len(cases)
    for case_index, case in enumerate(cases, start=1):
        case_id = case["case_id"]
        if progress_callback is not None:
            progress_callback(case_index, total_case_count, str(case_id))
        case_query_vector = None
        if query_vectors is not None:
            case_query_vector = query_vectors.get(case_id)
        if case_query_vector is None:
            case_query_vector = get_cached_query_vector(
                query_text=case["query"],
                embed_engine=resolved_embed_engine,
                model_name=resolved_model_name,
                model_version=resolved_model_version,
                db_path=db_path,
            )
        retrieval = text_search(
            query_text=case["query"],
            db_path=db_path,
            k=k,
            embed_engine=resolved_embed_engine,
            model_name=resolved_model_name,
            model_version=resolved_model_version,
            text_engine=text_engine,
            text_view=text_view,
            hybrid=hybrid,
            w_text=w_text,
            w_fp=w_fp,
            show_text_top=k,
            export_dir=None,
            export_top=0,
            redacted=redacted,
            demo_export=False,
            query_vector=case_query_vector,
        )
        case_errors = retrieval.get("errors")
        if case_errors is not None:
            code = case_errors.get("code") or "unknown_error"
            failure_breakdown[code] = failure_breakdown.get(code, 0) + 1
            case_output = {
                "case_id": case_id,
                "status": "error",
                "metrics": {"hit": 0, "rr": 0.0, "ndcg": 0.0, "max_relevance": 0, "normalized_relevance": 0.0, "hint_fallback_used": False},
                "top_hits": [],
                "errors": case_errors,
            }
            per_case.append(case_output)
            logger.log_step(
                "retrieval_case",
                {"case_id": case_id, "query": case["query"]},
                {"error": case_errors},
                "error",
                error_text=case_errors.get("message"),
            )
            retrieval_compact.append({"case_id": case_id, "status": "error", "code": code, "neighbor_count": 0})
            continue

        neighbors = retrieval.get("neighbors", [])
        metadata_map = _load_case_metadata(
            db_path,
            [str(item.get("structure_id")) for item in neighbors if item.get("structure_id")],
        )
        hints, hint_error = derive_hints_for_neighbors(db_path=db_path, neighbors=neighbors)
        if hint_error:
            hints = None
        metrics = _score_case(
            case=case,
            retrieval=retrieval,
            hints=hints,
            metadata_map=metadata_map,
            k=k,
            text_sim_threshold=text_sim_threshold,
            fp_sim_threshold=fp_sim_threshold,
        )
        status = "ok" if neighbors else "empty"
        case_output = {
            "case_id": case_id,
            "status": status,
            "metrics": {
                "hit": metrics["hit"],
                "rr": metrics["rr"],
                "ndcg": metrics["ndcg"],
                "max_relevance": metrics["max_relevance"],
                "normalized_relevance": metrics["normalized_relevance"],
                "hint_fallback_used": metrics["hint_fallback_used"],
            },
            "top_hits": metrics["top_hits"],
            "errors": hint_error if hint_error else None,
        }
        per_case.append(case_output)
        logger.log_step(
            "retrieval_case",
            {"case_id": case_id, "query": case["query"]},
            {"status": status, "neighbor_count": len(neighbors), "hint_error": hint_error},
            "ok" if status != "error" else "error",
        )
        retrieval_compact.append(
            {
                "case_id": case_id,
                "status": status,
                "neighbor_count": len(neighbors),
                "hint_fallback_used": metrics["hint_fallback_used"],
            }
        )

    logger.add_evidence("retrieval_results", {"cases": retrieval_compact})

    total_cases = len(per_case)
    covered_cases = len([item for item in per_case if item["status"] == "ok" and item["top_hits"]])
    hit_at_k = sum(int(item["metrics"]["hit"]) for item in per_case) / float(total_cases)
    mrr = sum(float(item["metrics"]["rr"]) for item in per_case) / float(total_cases)
    ndcg = sum(float(item["metrics"]["ndcg"]) for item in per_case) / float(total_cases)
    avg_score_values = [
        float(item["top_hits"][0]["score"])
        for item in per_case
        if item["top_hits"] and item["top_hits"][0].get("score") is not None
    ]
    avg_score = (sum(avg_score_values) / float(len(avg_score_values))) if avg_score_values else 0.0
    summary = {
        "hit_at_k": round(hit_at_k, 8),
        "mrr": round(mrr, 8),
        "ndcg_at_k": round(ndcg, 8),
        "coverage": round(covered_cases / float(total_cases), 8),
        "avg_score": round(avg_score, 8),
        "failure_breakdown": failure_breakdown,
        "total_cases": total_cases,
    }

    logger.log_step("scoring", {"case_count": total_cases}, {"summary": summary}, "ok")
    logger.add_evidence("scoring_table", {"per_case": per_case})
    logger.add_evidence("summary", summary)

    exports = _write_exports(out_dir=out_dir, summary={"run_id": run_id, "config": config, "summary": summary, "per_case": per_case, "errors": None}, per_case=per_case)
    logger.log_step("export", {"out_dir": out_dir}, {"exports": exports}, "ok")

    logger.finalize_run(status="ok")
    return {
        "run_id": run_id,
        "config": config,
        "summary": summary,
        "per_case": per_case,
        "exports": exports,
        "errors": None,
    }
