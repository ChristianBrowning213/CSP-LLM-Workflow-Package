import json
import os
import random
import sys
import time
import hashlib
import math
from typing import Any, Dict, List, Optional

from .bench_retrieval import load_benchmark_cases
from .db import connect, init_db
from .embeddings import DEFAULT_MODEL_NAME, resolve_embed_engine, resolve_model_version
from .fingerprint import fingerprint_structure
from .novelty import preload_fingerprint_index
from .query_cache import get_cached_query_vector, preembed_case_queries
from .retrieval import count_candidate_embeddings, text_search
from .runlog import RunLogger
from .utils import now_iso_utc


def _distance(vec_a, vec_b) -> float:
    total = 0.0
    for a, b in zip(vec_a, vec_b):
        delta = a - b
        total += delta * delta
    return total ** 0.5


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (pct / 100.0) * (len(sorted_vals) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(sorted_vals) - 1)
    if lower == upper:
        return sorted_vals[lower]
    weight = pos - lower
    return sorted_vals[lower] * (1 - weight) + sorted_vals[upper] * weight


def _summarize(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": sum(values) / len(values),
        "p10": _percentile(values, 10),
        "p50": _percentile(values, 50),
        "p90": _percentile(values, 90),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
    }


def _group_by_elements(entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        elements_csv = entry.get("metadata", {}).get("elements_csv") or ""
        groups.setdefault(elements_csv, []).append(entry)
    return groups


def calibrate_novelty(
    *,
    db_path: Optional[str],
    k: int = 10,
    out_dir: Optional[str] = None,
    max_pairs: int = 200,
) -> Dict[str, Any]:
    conn = connect(db_path)
    init_db(conn)

    structure_rows = conn.execute("SELECT structure_id FROM structures ORDER BY structure_id").fetchall()
    if not structure_rows:
        conn.close()
        return {"error": "no_structures"}

    structure_ids = [row["structure_id"] for row in structure_rows]
    for sid in structure_ids:
        fingerprint_structure(structure_id=sid, db_path=db_path, store=True)

    index = preload_fingerprint_index(db_path, force_reload=True)
    entries = index.get("entries", [])

    self_distances = [0.0 for _ in entries]

    near_distances: List[float] = []
    groups = _group_by_elements(entries)
    for group_entries in groups.values():
        if len(group_entries) < 2:
            continue
        a = group_entries[0]
        b = group_entries[1]
        near_distances.append(_distance(a["vector"], b["vector"]))
        if len(near_distances) >= max_pairs:
            break

    rng = random.Random(7)
    random_distances: List[float] = []
    if len(entries) > 1:
        for _ in range(min(max_pairs, len(entries) * 2)):
            a, b = rng.sample(entries, 2)
            random_distances.append(_distance(a["vector"], b["vector"]))

    near_summary = _summarize(near_distances)
    random_summary = _summarize(random_distances)

    recommended = None
    rationale = ""
    if near_summary.get("count", 0) > 0:
        recommended = near_summary.get("p95")
        rationale = "threshold set to p95 of near-duplicate distances (same chemsys)"
    elif random_summary.get("count", 0) > 0:
        recommended = random_summary.get("p10") or random_summary.get("p50")
        rationale = "near-duplicate sample missing; fallback to random distribution"

    report = {
        "created_at": now_iso_utc(),
        "k": k,
        "summary": {
            "self": _summarize(self_distances),
            "near_duplicates": near_summary,
            "random": random_summary,
        },
        "recommended_threshold": recommended,
        "rationale": rationale,
    }

    conn.close()

    if out_dir is None:
        out_dir = os.path.join("reports", f"calibration_{report['created_at'].replace(':', '').replace('-', '')}")
    os.makedirs(out_dir, exist_ok=True)

    json_path = os.path.join(out_dir, "calibration.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    md_lines = []
    md_lines.append("# Novelty Threshold Calibration")
    md_lines.append("")
    md_lines.append(f"Created At: {report['created_at']}")
    md_lines.append(f"Recommended Threshold: {report['recommended_threshold']}")
    md_lines.append(f"Rationale: {report['rationale']}")
    md_lines.append("")
    md_lines.append("## Summary")
    for key in ("self", "near_duplicates", "random"):
        summary = report["summary"].get(key, {})
        md_lines.append(f"{key}: {summary}")
    md_lines.append("")

    md_path = os.path.join(out_dir, "calibration.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    return {"out_dir": out_dir, "json_path": json_path, "md_path": md_path}


def _frange(start: float, stop: float, step: float) -> List[float]:
    if step <= 0:
        step = 0.01
    values: List[float] = []
    current = start
    while current <= (stop + 1e-12):
        values.append(round(current, 8))
        current += step
    return values


def _best_config_key(entry: Dict[str, Any]) -> tuple:
    summary = entry.get("summary") or {}
    return (
        -float(summary.get("ndcg_at_k", 0.0)),
        -float(summary.get("mrr", 0.0)),
        -float(summary.get("coverage", 0.0)),
        float(entry.get("text_sim_threshold", 999.0)),
        float(entry.get("fp_sim_threshold", 999.0)),
        float(entry.get("w_text", 999.0)),
        str(entry.get("config_id") or ""),
    )


def _dcg(relevances: List[int], k: int) -> float:
    value = 0.0
    for idx, rel in enumerate(relevances[:k], start=1):
        if rel <= 0:
            continue
        value += float(rel) / (math.log2(idx + 1.0))
    return value


def _calibration_error(*, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    diagnostics = details or {}
    return {
        "schema_version": "calibration.v1",
        "run_id": None,
        "best": None,
        "results": [],
        "errors": {
            "code": code,
            "message": message,
            "diagnostics": diagnostics,
            "details": diagnostics,
        },
    }


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _case_expected_ids(case: Dict[str, Any]) -> List[str]:
    primary = [str(item) for item in (case.get("expected_structure_ids") or []) if str(item)]
    if primary:
        return sorted(set(primary))
    nested = [str(item) for item in ((case.get("expected") or {}).get("structure_ids_any") or []) if str(item)]
    return sorted(set(nested))


def _cases_hash(cases: List[Dict[str, Any]]) -> str:
    rows = [
        {
            "case_id": str(case.get("case_id") or ""),
            "query": str(case.get("query") or ""),
            "expected_structure_ids": _case_expected_ids(case),
        }
        for case in cases
    ]
    blob = "\n".join(_canonical_json(item) for item in rows)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_meta_config(
    *,
    embed_engine: str,
    model_name: str,
    model_version: str,
    text_engine: str,
    text_view: str,
    k: int,
    redacted: bool,
    hybrid: bool,
) -> Dict[str, Any]:
    return {
        "embed_engine": embed_engine,
        "model_name": model_name,
        "model_version": model_version,
        "text_engine": text_engine,
        "text_view": text_view,
        "k": int(k),
        "redacted": bool(redacted),
        "hybrid": bool(hybrid),
    }


def _load_candidate_cache(
    *,
    cache_path: str,
    expected_config: Dict[str, Any],
    expected_cases_hash: str,
    expected_case_ids: List[str],
) -> Optional[List[Dict[str, Any]]]:
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
    except Exception:  # pylint: disable=broad-except
        return None
    if not lines:
        return None

    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError:
        return None
    if not isinstance(first, dict):
        return None
    if first.get("record_type") != "meta":
        return None
    if first.get("schema_version") != "calibrate_candidates_cache.v1":
        return None
    if first.get("cases_hash") != expected_cases_hash:
        return None
    if first.get("config") != expected_config:
        return None

    records: Dict[str, Dict[str, Any]] = {}
    for raw in lines[1:]:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(row, dict):
            return None
        if row.get("record_type") != "case":
            continue
        case_id = str(row.get("case_id") or "")
        if not case_id:
            return None
        records[case_id] = {
            "case_id": case_id,
            "expected_structure_ids": [str(item) for item in row.get("expected_structure_ids", [])],
            "candidates": [
                {
                    "structure_id": str(item.get("structure_id") or ""),
                    "text_score": float(item.get("text_score", 0.0)),
                    "fp_score": (None if item.get("fp_score") is None else float(item.get("fp_score"))),
                }
                for item in (row.get("candidates") or [])
                if str(item.get("structure_id") or "")
            ],
            "error": row.get("error"),
        }
    if any(case_id not in records for case_id in expected_case_ids):
        return None
    return [records[case_id] for case_id in expected_case_ids]


def _write_candidate_cache(
    *,
    cache_path: str,
    config: Dict[str, Any],
    cases_hash: str,
    records: List[Dict[str, Any]],
) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as handle:
        handle.write(
            _canonical_json(
                {
                    "record_type": "meta",
                    "schema_version": "calibrate_candidates_cache.v1",
                    "created_at": now_iso_utc(),
                    "cases_hash": cases_hash,
                    "config": config,
                }
            )
            + "\n"
        )
        for record in records:
            handle.write(
                _canonical_json(
                    {
                        "record_type": "case",
                        "case_id": record["case_id"],
                        "expected_structure_ids": record.get("expected_structure_ids", []),
                        "candidates": record.get("candidates", []),
                        "error": record.get("error"),
                    }
                )
                + "\n"
            )


def _build_candidate_cache_records(
    *,
    cases: List[Dict[str, Any]],
    db_path: Optional[str],
    k: int,
    embed_engine: str,
    model_name: str,
    model_version: str,
    text_engine: str,
    text_view: str,
    hybrid: bool,
    redacted: bool,
    query_vectors: Optional[Dict[str, List[float]]],
    progress_every: int,
) -> List[Dict[str, Any]]:
    total = len(cases)
    started = time.perf_counter()
    records: List[Dict[str, Any]] = []
    for idx, case in enumerate(cases, start=1):
        case_id = str(case.get("case_id") or "")
        query_text = str(case.get("query") or "")
        case_query_vector = None
        if query_vectors is not None:
            case_query_vector = query_vectors.get(case_id)
        if case_query_vector is None:
            case_query_vector = get_cached_query_vector(
                query_text=query_text,
                embed_engine=embed_engine,
                model_name=model_name,
                model_version=model_version,
                db_path=db_path,
            )
        retrieval = text_search(
            query_text=query_text,
            db_path=db_path,
            k=k,
            embed_engine=embed_engine,
            model_name=model_name,
            model_version=model_version,
            text_engine=text_engine,
            text_view=text_view,
            hybrid=hybrid,
            w_text=1.0,
            w_fp=0.0,
            show_text_top=0,
            export_dir=None,
            export_top=0,
            redacted=redacted,
            demo_export=False,
            query_vector=case_query_vector,
        )
        error = retrieval.get("errors")
        candidates: List[Dict[str, Any]] = []
        if error is None:
            for item in retrieval.get("neighbors", []):
                sid = str(item.get("structure_id") or "")
                if not sid:
                    continue
                raw_text_score = item.get("text_score", item.get("score"))
                try:
                    text_score = float(raw_text_score)
                except (TypeError, ValueError):
                    text_score = 0.0
                raw_fp_score = item.get("fp_score") if hybrid else None
                fp_score = None
                if raw_fp_score is not None:
                    try:
                        fp_score = float(raw_fp_score)
                    except (TypeError, ValueError):
                        fp_score = 0.0
                candidates.append(
                    {
                        "structure_id": sid,
                        "text_score": text_score,
                        "fp_score": fp_score,
                    }
                )
        records.append(
            {
                "case_id": case_id,
                "expected_structure_ids": _case_expected_ids(case),
                "candidates": candidates,
                "error": error,
            }
        )
        if idx % progress_every == 0 or idx == total:
            elapsed = max(1e-9, time.perf_counter() - started)
            rate = idx / elapsed
            print(f"[calibrate] cached {idx}/{total} cases ... rate {rate:.2f} case/s", file=sys.stderr)
    return records


def _score_cached_case(
    *,
    record: Dict[str, Any],
    k: int,
    w_text: float,
    hybrid: bool,
    text_sim_threshold: Optional[float],
    fp_sim_threshold: Optional[float],
) -> Dict[str, Any]:
    case_error = record.get("error")
    if case_error is not None:
        return {
            "status": "error",
            "errors": case_error,
            "metrics": {"hit": 0, "rr": 0.0, "ndcg": 0.0, "max_relevance": 0, "normalized_relevance": 0.0, "hint_fallback_used": False},
            "top_hits": [],
        }

    scored: List[Dict[str, Any]] = []
    for item in record.get("candidates", []):
        sid = str(item.get("structure_id") or "")
        if not sid:
            continue
        try:
            text_score = float(item.get("text_score", 0.0))
        except (TypeError, ValueError):
            text_score = 0.0
        raw_fp = item.get("fp_score")
        fp_score = None
        if raw_fp is not None:
            try:
                fp_score = float(raw_fp)
            except (TypeError, ValueError):
                fp_score = 0.0
        effective_fp = fp_score if fp_score is not None else 0.0
        final_score = text_score if not hybrid else (float(w_text) * text_score + float(1.0 - w_text) * effective_fp)
        scored.append(
            {
                "structure_id": sid,
                "text_score": text_score,
                "fp_score": fp_score,
                "score": final_score,
            }
        )
    ranked = sorted(scored, key=lambda row: (-float(row["score"]), -float(row["text_score"]), str(row["structure_id"])))
    expected_set = set(str(item) for item in record.get("expected_structure_ids", []))
    relevances: List[int] = []
    for item in ranked[:k]:
        passes = True
        if text_sim_threshold is not None and float(item.get("text_score", 0.0)) < float(text_sim_threshold):
            passes = False
        if fp_sim_threshold is not None and item.get("fp_score") is not None:
            if float(item.get("fp_score", 0.0)) < float(fp_sim_threshold):
                passes = False
        rel = 1 if (passes and item["structure_id"] in expected_set) else 0
        relevances.append(rel)

    hit = 1 if any(relevances) else 0
    rr = 0.0
    for idx, rel in enumerate(relevances, start=1):
        if rel > 0:
            rr = 1.0 / float(idx)
            break
    dcg = _dcg(relevances, k)
    ideal_count = min(len(expected_set), max(1, k))
    idcg = _dcg([1] * ideal_count, k)
    ndcg = (dcg / idcg) if idcg > 0 else 0.0

    top_hits = [
        {"rank": idx, "structure_id": item["structure_id"], "score": item["score"]}
        for idx, item in enumerate(ranked[: min(3, len(ranked))], start=1)
    ]
    return {
        "status": "ok" if ranked else "empty",
        "errors": None,
        "metrics": {
            "hit": int(hit),
            "rr": round(rr, 8),
            "ndcg": round(ndcg, 8),
            "max_relevance": 1 if hit else 0,
            "normalized_relevance": 1.0 if hit else 0.0,
            "hint_fallback_used": False,
        },
        "top_hits": top_hits,
    }


def _summarize_scored_cases(per_case: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_cases = len(per_case)
    if total_cases <= 0:
        return {
            "hit_at_k": 0.0,
            "mrr": 0.0,
            "ndcg_at_k": 0.0,
            "coverage": 0.0,
            "avg_score": 0.0,
            "failure_breakdown": {},
            "total_cases": 0,
        }
    failure_breakdown: Dict[str, int] = {}
    for item in per_case:
        errors = item.get("errors")
        if isinstance(errors, dict):
            code = str(errors.get("code") or "unknown_error")
            failure_breakdown[code] = failure_breakdown.get(code, 0) + 1
    covered_cases = len([item for item in per_case if item["status"] == "ok" and item["top_hits"]])
    hit_at_k = sum(int(item["metrics"]["hit"]) for item in per_case) / float(total_cases)
    mrr = sum(float(item["metrics"]["rr"]) for item in per_case) / float(total_cases)
    ndcg = sum(float(item["metrics"]["ndcg"]) for item in per_case) / float(total_cases)
    avg_score_values = [
        float(item["top_hits"][0]["score"])
        for item in per_case
        if item.get("top_hits") and item["top_hits"][0].get("score") is not None
    ]
    avg_score = (sum(avg_score_values) / float(len(avg_score_values))) if avg_score_values else 0.0
    return {
        "hit_at_k": round(hit_at_k, 8),
        "mrr": round(mrr, 8),
        "ndcg_at_k": round(ndcg, 8),
        "coverage": round(covered_cases / float(total_cases), 8),
        "avg_score": round(avg_score, 8),
        "failure_breakdown": failure_breakdown,
        "total_cases": total_cases,
    }

def run_retrieval_calibration(
    *,
    db_path: Optional[str],
    cases_path: str,
    out_dir: str,
    k: int = 10,
    embed_engine: str = "auto",
    model_name: Optional[str] = None,
    model_version: Optional[str] = None,
    text_engine: str = "caption",
    text_view: str = "caption",
    hybrid: bool = True,
    redacted: bool = True,
    text_sim_min: float = 0.60,
    text_sim_max: float = 0.95,
    text_sim_step: float = 0.05,
    fp_sim_min: float = 0.85,
    fp_sim_max: float = 0.99,
    fp_sim_step: float = 0.02,
    w_text_values: Optional[List[float]] = None,
    run_name: Optional[str] = None,
    preembed_queries: bool = True,
    max_cases: int = 0,
    progress_every: int = 10,
    cache_candidates: bool = True,
    reuse_candidates_cache: bool = True,
    candidate_cache_path: Optional[str] = None,
) -> Dict[str, Any]:
    cases, cases_error = load_benchmark_cases(cases_path)
    if cases_error:
        return _calibration_error(
            code=cases_error.get("code", "cases_invalid_schema"),
            message=cases_error.get("message", "failed to load cases"),
        )

    if w_text_values is None:
        w_text_values = [0.5, 0.6, 0.7, 0.8, 0.9]
    resolved_weights = sorted(float(value) for value in w_text_values)
    for value in resolved_weights:
        if value < 0.0 or value > 1.0:
            raise ValueError(f"w_text must be in [0,1], got {value}")
    if max_cases > 0:
        cases = list(cases[:max_cases])
    progress_every = max(1, int(progress_every))

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
        return _calibration_error(
            code="candidate_set_empty",
            message="No candidate embeddings found for this embedding space.",
            details={
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

    text_thresholds = _frange(text_sim_min, text_sim_max, text_sim_step)
    fp_thresholds = _frange(fp_sim_min, fp_sim_max, fp_sim_step)

    query_vectors: Optional[Dict[str, List[float]]] = None
    if preembed_queries:
        try:
            cached = preembed_case_queries(
                cases=cases,
                embed_engine=resolved_embed_engine,
                model_name=resolved_model_name,
                model_version=resolved_model_version,
                db_path=db_path,
                cache_table=True,
            )
        except Exception as exc:  # pylint: disable=broad-except
            return _calibration_error(
                code="query_embedding_failed",
                message="Failed to pre-embed calibration queries.",
                details={"error": str(exc)},
            )
        query_vectors = cached.get("case_vectors") or {}

    cases_hash = _cases_hash(cases)
    cache_config = _cache_meta_config(
        embed_engine=resolved_embed_engine,
        model_name=resolved_model_name,
        model_version=resolved_model_version,
        text_engine=text_engine,
        text_view=text_view,
        k=k,
        redacted=redacted,
        hybrid=hybrid,
    )
    if candidate_cache_path is None:
        candidate_cache_path = os.path.join(out_dir, "cached_candidates.jsonl")
    case_ids_in_order = [str(case.get("case_id") or "") for case in cases]
    cached_records: Optional[List[Dict[str, Any]]] = None
    reused_cache = False
    if cache_candidates and reuse_candidates_cache:
        cached_records = _load_candidate_cache(
            cache_path=candidate_cache_path,
            expected_config=cache_config,
            expected_cases_hash=cases_hash,
            expected_case_ids=case_ids_in_order,
        )
        reused_cache = cached_records is not None
    if cached_records is None:
        cached_records = _build_candidate_cache_records(
            cases=cases,
            db_path=db_path,
            k=k,
            embed_engine=resolved_embed_engine,
            model_name=resolved_model_name,
            model_version=resolved_model_version,
            text_engine=text_engine,
            text_view=text_view,
            hybrid=hybrid,
            redacted=redacted,
            query_vectors=query_vectors,
            progress_every=progress_every,
        )
        if cache_candidates:
            _write_candidate_cache(
                cache_path=candidate_cache_path,
                config=cache_config,
                cases_hash=cases_hash,
                records=cached_records,
            )

    logger = RunLogger(db_path)
    config = {
        "cases_path": cases_path,
        "k": k,
        "engine": resolved_embed_engine,
        "model": resolved_model_name,
        "model_version": resolved_model_version,
        "text_engine": text_engine,
        "text_view": text_view,
        "hybrid": hybrid,
        "redacted": redacted,
        "text_thresholds": text_thresholds,
        "fp_thresholds": fp_thresholds,
        "w_text_values": resolved_weights,
        "preembed_queries": preembed_queries,
        "max_cases": max_cases,
        "progress_every": progress_every,
        "cache_candidates": cache_candidates,
        "reuse_candidates_cache": reuse_candidates_cache,
        "candidate_cache_path": candidate_cache_path if cache_candidates else None,
        "candidate_cache_reused": reused_cache,
        "run_name": run_name,
    }
    run_id = logger.start_run("calibrate-retrieval", config)
    logger.log_step("load_cases", {"cases_path": cases_path}, {"count": len(cases or [])}, "ok")
    logger.add_evidence("cases_loaded", {"count": len(cases or [])})

    results: List[Dict[str, Any]] = []
    config_index = 0
    total_points = len(text_thresholds) * len(fp_thresholds) * len(resolved_weights)
    total_cases = len(cached_records)
    for text_threshold in text_thresholds:
        for fp_threshold in fp_thresholds:
            for w_text in resolved_weights:
                config_index += 1
                print(
                    (
                        f"[calibrate] sweep {config_index}/{total_points} "
                        f"(w_text={w_text:.4f}, text_thr={text_threshold:.4f}, fp_thr={fp_threshold:.4f}) "
                        f"cases 0/{total_cases} ..."
                    ),
                    file=sys.stderr,
                )
                w_fp = round(1.0 - float(w_text), 8)
                per_case: List[Dict[str, Any]] = []
                for case_idx, record in enumerate(cached_records, start=1):
                    if case_idx == 1 or case_idx % progress_every == 0 or case_idx == total_cases:
                        print(
                            (
                                f"[calibrate] sweep {config_index}/{total_points} "
                                f"(w_text={w_text:.4f}, text_thr={text_threshold:.4f}, fp_thr={fp_threshold:.4f}) "
                                f"cases {case_idx}/{total_cases} ..."
                            ),
                            file=sys.stderr,
                        )
                    scored = _score_cached_case(
                        record=record,
                        k=k,
                        w_text=w_text,
                        hybrid=hybrid,
                        text_sim_threshold=text_threshold,
                        fp_sim_threshold=fp_threshold,
                    )
                    per_case.append(
                        {
                            "case_id": record.get("case_id"),
                            "status": scored["status"],
                            "metrics": scored["metrics"],
                            "top_hits": scored["top_hits"],
                            "errors": scored["errors"],
                        }
                    )
                summary = _summarize_scored_cases(per_case)
                entry = {
                    "config_id": f"cfg_{config_index:04d}",
                    "text_sim_threshold": text_threshold,
                    "fp_sim_threshold": fp_threshold,
                    "w_text": w_text,
                    "w_fp": w_fp,
                    "summary": summary,
                    "errors": None,
                    "bench_run_id": None,
                }
                results.append(entry)
                logger.log_step(
                    "sweep_point",
                    {
                        "text_sim_threshold": text_threshold,
                        "fp_sim_threshold": fp_threshold,
                        "w_text": w_text,
                        "w_fp": w_fp,
                    },
                    {
                        "summary": entry["summary"],
                        "errors": entry["errors"],
                        "bench_run_id": entry["bench_run_id"],
                        "candidate_cache_reused": reused_cache,
                    },
                    "ok",
                )

    valid = [entry for entry in results if entry.get("summary") is not None]
    if not valid:
        logger.finalize_run(status="error", error_text="all calibration points failed")
        return {
            "schema_version": "calibration.v1",
            "run_id": run_id,
            "best": None,
            "results": results,
            "errors": {"code": "calibration_failed", "message": "all sweep points failed"},
        }

    best = sorted(valid, key=_best_config_key)[0]
    os.makedirs(out_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "calibration_summary.json")
    csv_path = os.path.join(out_dir, "calibration_results.csv")
    best_path = os.path.join(out_dir, "calibration_best.json")

    payload = {
        "schema_version": "calibration.v1",
        "run_id": run_id,
        "best": best,
        "results": results,
        "selection_rule": "max ndcg@k, tie mrr, tie coverage, tie smaller thresholds",
        "diagnostics": {
            "candidate_cache_enabled": bool(cache_candidates),
            "candidate_cache_reused": bool(reused_cache),
            "candidate_cache_path": candidate_cache_path if cache_candidates else None,
            "cases_hash": cases_hash,
            "cached_case_count": len(cached_records),
        },
        "errors": None,
    }
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    with open(best_path, "w", encoding="utf-8") as handle:
        json.dump(best, handle, indent=2)
    with open(csv_path, "w", encoding="utf-8") as handle:
        handle.write("config_id,text_sim_threshold,fp_sim_threshold,w_text,w_fp,hit_at_k,mrr,ndcg_at_k,coverage,avg_score,error_code\n")
        for entry in results:
            summary = entry.get("summary") or {}
            error_code = (entry.get("errors") or {}).get("code") if isinstance(entry.get("errors"), dict) else ""
            handle.write(
                ",".join(
                    [
                        str(entry.get("config_id")),
                        str(entry.get("text_sim_threshold")),
                        str(entry.get("fp_sim_threshold")),
                        str(entry.get("w_text")),
                        str(entry.get("w_fp")),
                        str(summary.get("hit_at_k", "")),
                        str(summary.get("mrr", "")),
                        str(summary.get("ndcg_at_k", "")),
                        str(summary.get("coverage", "")),
                        str(summary.get("avg_score", "")),
                        str(error_code),
                    ]
                )
                + "\n"
            )

    logger.log_step(
        "export",
        {"out_dir": out_dir},
        {"summary_path": summary_path, "csv_path": csv_path, "best_path": best_path},
        "ok",
    )
    logger.add_evidence("calibration_results", {"results": results})
    logger.add_evidence("calibration_best", best)
    logger.finalize_run(status="ok")
    payload["paths"] = {"summary": summary_path, "csv": csv_path, "best": best_path}
    return payload
