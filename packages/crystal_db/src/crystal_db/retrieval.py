import json
from typing import Any, Dict, List, Optional, Set, Tuple

import os
import re

from .db import connect, init_db
from .embeddings import (
    DEFAULT_EMBED_ENGINE,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    embed_text,
    l2_distance,
    resolve_embed_engine,
    resolve_model_version,
)
from .fingerprint import FINGERPRINT_METHOD, FINGERPRINT_VERSION
from .readiness import backend_status_to_error, inspect_backend_readiness
from .sequence_index import canonicalize_cif
from .similarity import similar_structures
from .utils import elements_from_csv, now_iso_utc, stable_hash





TEXT_VIEW_ROBOCRYS = "robocrys"
TEXT_VIEW_CAPTION = "caption"


def _resolve_text_view(text_engine: str, text_view: Optional[str]) -> str:
    value = (text_view or "").strip().lower()
    if value:
        if value not in (TEXT_VIEW_ROBOCRYS, TEXT_VIEW_CAPTION):
            raise ValueError(f"unsupported text_view: {text_view}")
        return value
    return TEXT_VIEW_CAPTION if (text_engine or "").strip().lower() == "caption" else TEXT_VIEW_ROBOCRYS


def _sql_in_clause(values: List[str]) -> str:
    if not values:
        return ""
    return ", ".join(["?"] * len(values))


def _allow_derivatives(structure_id: str, db_path: Optional[str]) -> bool:
    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT allow_derivatives FROM provenance WHERE structure_id = ?",
        (structure_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return False
    value = row["allow_derivatives"]
    return value is None or int(value) != 0


def _fetch_provenance(conn, structure_id: str) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT source, source_id, retrieved_at, allow_export, allow_derivatives FROM provenance WHERE structure_id = ?",
        (structure_id,),
    ).fetchone()
    if row is None:
        return {}
    return {
        "source": row["source"],
        "source_id": row["source_id"],
        "retrieved_at": row["retrieved_at"],
        "allow_export": row["allow_export"],
        "allow_derivatives": row["allow_derivatives"],
    }


def _redact_if_needed(payload: Dict[str, Any]) -> Dict[str, Any]:
    provenance = payload.get("provenance", {})
    allow_export = provenance.get("allow_export")
    if allow_export in (0, False):
        return {"structure_id": payload.get("structure_id"), "provenance": provenance, "redacted": True}
    return payload


def _decode_vector(raw_value: Any) -> Optional[List[float]]:
    if raw_value is None:
        return None
    if isinstance(raw_value, memoryview):
        raw_value = raw_value.tobytes()
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8", errors="replace")
    if isinstance(raw_value, str):
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw_value, list):
        decoded = raw_value
    else:
        return None
    if not isinstance(decoded, list):
        return None
    try:
        return [float(item) for item in decoded]
    except (TypeError, ValueError):
        return None


def _build_text_remediation(
    *,
    db_path: Optional[str],
    structure_id: str,
    embed_engine: str,
    model_name: str,
    model_version: str,
) -> Dict[str, Any]:
    db_value = db_path or "<db_path>"
    sid_value = structure_id or "<structure_id>"
    return {
        "summary": "Generate text docs and embeddings for this structure in the requested embedding space.",
        "commands": [
            f'python -m crystal_db gen-text --db "{db_value}" --engine <text_engine> --id "{sid_value}"',
            (
                f'python -m crystal_db embed-text --db "{db_value}" --text-engine <text_engine> '
                f'--engine {embed_engine} --model {model_name} --model-version {model_version} '
                f'--id "{sid_value}" --retry-failed'
            ),
        ],
    }


def _similar_text_error(
    *,
    code: str,
    message: str,
    query: Dict[str, Any],
    query_embedding_found: bool,
    candidate_count: int,
    db_path: Optional[str],
    extra_diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    diagnostics: Dict[str, Any] = {
        "query_embedding_found": query_embedding_found,
        "candidate_count": candidate_count,
        "table_used": "text_embeddings",
        "searched_tables": ["text_docs", "text_embeddings"],
        "filter_key": {
            "embed_engine": query["embed_engine"],
            "model_name": query["model_name"],
            "model_version": query["model_version"],
        },
    }
    if extra_diagnostics:
        diagnostics.update(extra_diagnostics)
    return {
        "error": code,
        "message": message,
        "query": query,
        "diagnostics": diagnostics,
        "remediation": _build_text_remediation(
            db_path=db_path,
            structure_id=query["structure_id"],
            embed_engine=query["embed_engine"],
            model_name=query["model_name"],
            model_version=query["model_version"],
        ),
    }


def similar_text(
    *,
    structure_id: str,
    db_path: Optional[str],
    k: int = 10,
    engine: str = DEFAULT_EMBED_ENGINE,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> Dict[str, Any]:
    if model_name is None:
        model_name = DEFAULT_MODEL_NAME
    embed_engine = resolve_embed_engine(engine, model_name)
    model_version = resolve_model_version(model_name, model_version, embed_engine=embed_engine)
    query = {
        "structure_id": structure_id,
        "embed_engine": embed_engine,
        "model_name": model_name,
        "model_version": model_version,
        "k": k,
    }

    conn = connect(db_path)
    init_db(conn)
    candidate_count = int(
        conn.execute(
            "SELECT COUNT(*) AS cnt "
            "FROM text_embeddings te "
            "JOIN text_docs td ON td.id = te.text_doc_id "
            "WHERE te.status = 'OK' AND te.embed_engine = ? AND te.model = ? AND te.model_version = ? "
            "AND td.structure_id != ?",
            (embed_engine, model_name, model_version, structure_id),
        ).fetchone()["cnt"]
    )
    query_row = conn.execute(
        "SELECT te.id, te.vector "
        "FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        "WHERE td.structure_id = ? AND te.status = 'OK' AND te.embed_engine = ? AND te.model = ? AND te.model_version = ? "
        "ORDER BY te.id DESC LIMIT 1",
        (structure_id, embed_engine, model_name, model_version),
    ).fetchone()
    if query_row is None:
        conn.close()
        return _similar_text_error(
            code="query_embedding_missing",
            message="No query text embedding found for this structure in the requested embedding space.",
            query=query,
            query_embedding_found=False,
            candidate_count=candidate_count,
            db_path=db_path,
        )
    query_vector = _decode_vector(query_row["vector"])
    if query_vector is None:
        conn.close()
        return _similar_text_error(
            code="query_embedding_decode_failed",
            message="Query embedding exists but could not be decoded from text_embeddings.vector.",
            query=query,
            query_embedding_found=True,
            candidate_count=candidate_count,
            db_path=db_path,
        )
    if candidate_count <= 0:
        conn.close()
        return _similar_text_error(
            code="candidate_set_empty",
            message="No candidate text embeddings were found in this embedding space.",
            query=query,
            query_embedding_found=True,
            candidate_count=0,
            db_path=db_path,
        )

    rows = conn.execute(
        "SELECT td.structure_id, te.vector, td.text, m.formula, m.elements_csv, m.space_group, "
        "p.source, p.source_id, p.retrieved_at, p.allow_export "
        "FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        "JOIN metadata m ON m.structure_id = td.structure_id "
        "JOIN provenance p ON p.structure_id = td.structure_id "
        "WHERE te.status = 'OK' AND te.embed_engine = ? AND te.model = ? AND te.model_version = ? "
        "AND td.structure_id != ? "
        "ORDER BY td.structure_id ASC, te.id DESC",
        (embed_engine, model_name, model_version, structure_id),
    ).fetchall()
    conn.close()
    if not rows:
        return _similar_text_error(
            code="candidate_set_empty",
            message="No candidate text embeddings were found in this embedding space.",
            query=query,
            query_embedding_found=True,
            candidate_count=0,
            db_path=db_path,
        )

    neighbors: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    decode_failed = 0
    dim_mismatch = 0
    for row in rows:
        sid = row["structure_id"]
        if sid in seen:
            continue
        seen.add(sid)
        vector = _decode_vector(row["vector"])
        if vector is None:
            decode_failed += 1
            continue
        if len(vector) != len(query_vector):
            dim_mismatch += 1
            continue
        distance = l2_distance(query_vector, vector)
        payload = {
            "structure_id": sid,
            "distance": distance,
            "why": {"text_excerpt": (row["text"] or "")[:160]},
            "provenance": {
                "source": row["source"],
                "source_id": row["source_id"],
                "retrieved_at": row["retrieved_at"],
                "allow_export": row["allow_export"],
            },
            "metadata": {
                "formula": row["formula"],
                "elements": elements_from_csv(row["elements_csv"]),
                "space_group": row["space_group"],
            },
        }
        neighbors.append(_redact_if_needed(payload))
    if not neighbors:
        return _similar_text_error(
            code="candidate_vectors_unusable",
            message="Candidate embeddings were found, but none were usable for distance computation.",
            query=query,
            query_embedding_found=True,
            candidate_count=candidate_count,
            db_path=db_path,
            extra_diagnostics={"decode_failed": decode_failed, "dim_mismatch": dim_mismatch},
        )

    neighbors.sort(key=lambda n: (n.get("distance", 0.0), n.get("structure_id", "")))
    return {
        "query": query,
        "neighbors": neighbors[: max(1, k)],
    }


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


def _safe_cif_filename(structure_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (structure_id or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned or "structure"


def _normalize_text_doc_status(status: Optional[str]) -> str:
    return "ok" if str(status or "").upper() == "OK" else "failed"


def _pick_auto_text_doc_row(rows: List[Any], text_view: str) -> Any:
    if not rows:
        return None
    preferred = ("caption", "robocrys", "baseline")
    for engine in preferred:
        for row in rows:
            if (
                row["engine"] == engine
                and row["text_view"] == text_view
                and _normalize_text_doc_status(row["status"]) == "ok"
            ):
                return row
    for engine in preferred:
        for row in rows:
            if row["engine"] == engine and row["text_view"] == text_view:
                return row
    return rows[0]


def _load_display_text_doc(conn, structure_id: str, text_engine: str, text_view: str) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT id, engine, text_view, status, error_type, error_message, text, updated_at "
        "FROM text_docs WHERE structure_id = ? ORDER BY updated_at DESC, id DESC",
        (structure_id,),
    ).fetchall()
    if not rows:
        return {
            "text_doc_id": None,
            "text_engine": text_engine,
            "status": "failed",
            "error": "text_doc_not_found",
        }

    if text_engine != "auto":
        for row in rows:
            if row["engine"] == text_engine and row["text_view"] == text_view:
                selected = row
                break
        else:
            return {
                "text_doc_id": None,
                "text_engine": text_engine,
                "text_view": text_view,
                "status": "failed",
                "error": f"text_doc_not_found_for_engine_or_view:{text_engine}/{text_view}",
            }
    else:
        selected = _pick_auto_text_doc_row(rows, text_view)

    status = _normalize_text_doc_status(selected["status"])
    error = selected["error_message"] or selected["error_type"]
    payload: Dict[str, Any] = {
        "text_doc_id": selected["id"],
        "text_engine": selected["engine"],
        "text_view": selected["text_view"],
        "status": status,
        "error": error,
    }
    if status == "ok":
        if selected["text"] is not None:
            payload["text"] = selected["text"]
        else:
            payload["error"] = payload["error"] or "text_missing"
            payload["status"] = "failed"
    return payload


def _text_search_space_error(
    *,
    query: Dict[str, Any],
    db_path: Optional[str],
    code: str,
    message: str,
    candidate_count: int,
    extra_diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    db_value = db_path or "<db_path>"
    diagnostics: Dict[str, Any] = {
        "candidate_count": candidate_count,
        "table_used": "text_embeddings",
        "searched_tables": ["text_docs", "text_embeddings"],
        "filter_key": {
            "embed_engine": query["embed_engine"],
            "model_name": query["model_name"],
            "model_version": query["model_version"],
            "text_engine": query["text_engine"],
            "text_view": query["text_view"],
        },
    }
    if extra_diagnostics:
        diagnostics.update(extra_diagnostics)
    return {
        "code": code,
        "message": message,
        "diagnostics": diagnostics,
        "remediation": {
            "commands": [
                (
                    f'python -m crystal_db embed-text --db "{db_value}" --text-engine <text_engine> '
                    f'--text-view {query["text_view"]} '
                    f'--engine {query["embed_engine"]} --model {query["model_name"]} '
                    f'--model-version {query["model_version"]} --all'
                ),
                f'python -m crystal_db audit --db "{db_value}" --run-id <embed_text_run_id>',
            ],
            "audit_sql": [
                (
                    "SELECT COUNT(*) FROM text_embeddings "
                    "WHERE status = 'OK' AND embed_engine = :embed_engine "
                    "AND model = :model_name AND model_version = :model_version;"
                ),
            ],
        },
    }


def count_candidate_embeddings(
    db_path: Optional[str],
    text_engine: str,
    text_view: Optional[str],
    embed_engine: str,
    model_name: Optional[str],
    model_version: Optional[str],
) -> int:
    resolved_model_name = model_name or DEFAULT_MODEL_NAME
    resolved_text_view = _resolve_text_view(text_engine, text_view)
    resolved_embed_engine = resolve_embed_engine(embed_engine, resolved_model_name)
    resolved_model_version = resolve_model_version(
        resolved_model_name,
        model_version,
        embed_engine=resolved_embed_engine,
    )

    conn = connect(db_path)
    init_db(conn)
    where_clauses = [
        "te.status = 'OK'",
        "te.embed_engine = ?",
        "te.model = ?",
        "te.model_version = ?",
        "td.text_view = ?",
    ]
    params: List[Any] = [
        resolved_embed_engine,
        resolved_model_name,
        resolved_model_version,
        resolved_text_view,
    ]
    if text_engine != "auto":
        where_clauses.append("td.engine = ?")
        params.append(text_engine)
    row = conn.execute(
        "SELECT COUNT(*) AS cnt "
        "FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        f"WHERE {' AND '.join(where_clauses)}",
        tuple(params),
    ).fetchone()
    conn.close()
    if row is None:
        return 0
    return int(row["cnt"])


def _query_embedding_error(
    *,
    query: Dict[str, Any],
    error_text: str,
) -> Dict[str, Any]:
    return {
        "code": "query_embedding_failed",
        "message": "Failed to create query embedding for text-search.",
        "diagnostics": {"error": error_text},
        "remediation": {
            "steps": [
                "Verify LM Studio server is running and embeddings endpoint is reachable.",
                "Verify embedding model is loaded and matches --model.",
            ],
            "env_vars": ["CRYSTALDB_EMBED_BASE_URL", "CRYSTALDB_EMBED_API_KEY", "CRYSTALDB_EMBED_TIMEOUT_S"],
            "powershell": [
                '$env:CRYSTALDB_EMBED_BASE_URL = "http://127.0.0.1:1234/v1"',
                '$env:CRYSTALDB_EMBED_API_KEY = "lm-studio"',
            ],
            "posix": [
                'export CRYSTALDB_EMBED_BASE_URL="http://127.0.0.1:1234/v1"',
                'export CRYSTALDB_EMBED_API_KEY="lm-studio"',
            ],
            "retry_command": (
                f'python -m crystal_db text-search --db "<db_path>" --query "{query["text"]}" '
                f'--engine {query["embed_engine"]} --model {query["model_name"]} '
                f'--model-version {query["model_version"]}'
            ),
        },
    }


def _result_payload(
    *,
    status: str,
    query: Dict[str, Any],
    neighbors: List[Dict[str, Any]],
    errors: Optional[Dict[str, Any]],
    backend_status: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "status": status,
        "query": query,
        "neighbors": neighbors,
        "errors": errors,
        "backend_status": backend_status,
    }


def text_search(
    *,
    query_text: str,
    db_path: Optional[str],
    k: int = 10,
    embed_engine: str = DEFAULT_EMBED_ENGINE,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
    text_engine: str = "robocrys",
    text_view: Optional[str] = None,
    hybrid: bool = False,
    w_text: float = 1.0,
    w_fp: float = 0.0,
    show_text_top: int = 3,
    export_dir: Optional[str] = None,
    export_top: Optional[int] = None,
    redacted: bool = True,
    demo_export: bool = False,
    query_vector: Optional[List[float]] = None,
) -> Dict[str, Any]:
    text_value = (query_text or "").strip()
    if model_name is None:
        model_name = DEFAULT_MODEL_NAME
    resolved_text_view = _resolve_text_view(text_engine, text_view)
    resolved_embed_engine = resolve_embed_engine(embed_engine, model_name)
    resolved_model_version = resolve_model_version(
        model_name,
        model_version,
        embed_engine=resolved_embed_engine,
    )

    if k <= 0:
        k = 1
    if show_text_top < 0:
        show_text_top = 0
    if export_top is None:
        export_top = show_text_top
    if export_top < 0:
        export_top = 0
    if w_text is None:
        w_text = 1.0
    if w_fp is None:
        w_fp = 0.0

    query: Dict[str, Any] = {
        "text": text_value,
        "embed_engine": resolved_embed_engine,
        "model_name": model_name,
        "model_version": resolved_model_version,
        "text_engine": text_engine,
        "text_view": resolved_text_view,
        "hybrid": bool(hybrid),
        "w_text": float(w_text),
        "w_fp": float(w_fp),
        "k": k,
    }
    if not text_value:
        backend_status = {
            "ready": False,
            "state": "invalid_query",
            "message": "Query text is empty.",
            "surface": "text_search",
            "query_mode": "query",
            "db_path": os.path.abspath(db_path or ""),
        }
        return _result_payload(
            status="error",
            query=query,
            neighbors=[],
            errors={
                "code": "invalid_query",
                "message": "Query text is empty.",
                "diagnostics": {"query_text_length": 0},
            },
            backend_status=backend_status,
        )

    backend_status = inspect_backend_readiness(
        db_path=db_path or "",
        surface="text_search",
        query_mode="query",
        text_engine=text_engine,
        text_view=resolved_text_view,
        embed_engine=resolved_embed_engine,
        model_name=model_name,
        model_version=resolved_model_version,
        require_fingerprint_index=False,
    )
    if not backend_status["ready"]:
        return _result_payload(
            status="error",
            query=query,
            neighbors=[],
            errors=backend_status_to_error(backend_status),
            backend_status=backend_status,
        )

    resolved_query_vector: List[float]
    if query_vector is None:
        try:
            resolved_query_vector = embed_text(
                text_value,
                model_name=model_name,
                model_version=resolved_model_version,
                embed_engine=resolved_embed_engine,
            )
        except Exception as exc:  # pylint: disable=broad-except
            return _result_payload(
                status="error",
                query=query,
                neighbors=[],
                errors=_query_embedding_error(query=query, error_text=str(exc)),
                backend_status=backend_status,
            )
    else:
        try:
            resolved_query_vector = [float(item) for item in query_vector]
        except (TypeError, ValueError):
            return _result_payload(
                status="error",
                query=query,
                neighbors=[],
                errors=_query_embedding_error(query=query, error_text="invalid_precomputed_query_vector"),
                backend_status=backend_status,
            )
    if not resolved_query_vector:
        return _result_payload(
            status="error",
            query=query,
            neighbors=[],
            errors=_query_embedding_error(query=query, error_text="empty_query_embedding"),
            backend_status=backend_status,
        )

    conn = connect(db_path)
    init_db(conn)

    where_clauses = ["te.status = 'OK'", "te.embed_engine = ?", "te.model = ?", "te.model_version = ?", "td.text_view = ?"]
    params: List[Any] = [resolved_embed_engine, model_name, resolved_model_version, resolved_text_view]
    if text_engine != "auto":
        where_clauses.append("td.engine = ?")
        params.append(text_engine)

    where_sql = " AND ".join(where_clauses)
    rows = conn.execute(
        "SELECT td.structure_id, te.vector, p.source, p.source_id, p.retrieved_at, p.allow_export "
        "FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        "LEFT JOIN provenance p ON p.structure_id = td.structure_id "
        f"WHERE {where_sql} "
        "ORDER BY td.structure_id ASC, te.id DESC",
        tuple(params),
    ).fetchall()
    candidate_count = len(rows)
    if candidate_count <= 0:
        conn.close()
        return _result_payload(
            status="error",
            query=query,
            neighbors=[],
            errors=_text_search_space_error(
                query=query,
                db_path=db_path,
                code="candidate_set_empty",
                message="No candidate embeddings found for this embedding space.",
                candidate_count=0,
            ),
            backend_status=backend_status,
        )

    best_by_structure: Dict[str, Dict[str, Any]] = {}
    decode_failed = 0
    dim_mismatch = 0
    for row in rows:
        vector = _decode_vector(row["vector"])
        if vector is None:
            decode_failed += 1
            continue
        if len(vector) != len(resolved_query_vector):
            dim_mismatch += 1
            continue
        structure_id = row["structure_id"]
        score = _cosine_similarity(resolved_query_vector, vector)
        entry = best_by_structure.get(structure_id)
        if entry is not None and entry["score"] >= score:
            continue
        best_by_structure[structure_id] = {
            "structure_id": structure_id,
            "score": score,
            "provenance": {
                "source": row["source"],
                "source_id": row["source_id"],
                "retrieved_at": row["retrieved_at"],
                "allow_export": row["allow_export"],
            },
        }

    if not best_by_structure:
        conn.close()
        return _result_payload(
            status="error",
            query=query,
            neighbors=[],
            errors=_text_search_space_error(
                query=query,
                db_path=db_path,
                code="candidate_vectors_unusable",
                message="Candidate embeddings exist, but none were usable for cosine similarity.",
                candidate_count=candidate_count,
                extra_diagnostics={"decode_failed": decode_failed, "dim_mismatch": dim_mismatch},
            ),
            backend_status=backend_status,
        )

    ranked_by_text = sorted(
        list(best_by_structure.values()),
        key=lambda item: (-item["score"], item["structure_id"]),
    )

    if hybrid:
        pool_size = max(50, k * 10)
        rerank_pool = ranked_by_text[:pool_size]
        if rerank_pool:
            anchor_structure_id = rerank_pool[0]["structure_id"]
            structure_ids = [item["structure_id"] for item in rerank_pool]
            fp_vectors: Dict[str, List[float]] = {}
            fp_rows = conn.execute(
                "SELECT structure_id, vector_json "
                "FROM structure_fingerprints "
                f"WHERE fingerprint_method = ? AND fingerprint_version = ? AND structure_id IN ({_sql_in_clause(structure_ids)})",
                tuple([FINGERPRINT_METHOD, FINGERPRINT_VERSION] + structure_ids),
            ).fetchall()
            for fp_row in fp_rows:
                decoded = _decode_vector(fp_row["vector_json"])
                if decoded is not None:
                    fp_vectors[fp_row["structure_id"]] = decoded

            anchor_fp = fp_vectors.get(anchor_structure_id)
            for item in rerank_pool:
                text_score = float(item["score"])
                candidate_fp = fp_vectors.get(item["structure_id"])
                fp_score = 0.0
                if (
                    anchor_fp is not None
                    and candidate_fp is not None
                    and len(anchor_fp) == len(candidate_fp)
                    and len(anchor_fp) > 0
                ):
                    fp_score = _cosine_similarity(anchor_fp, candidate_fp)
                final_score = float(w_text) * text_score + float(w_fp) * fp_score
                item["text_score"] = text_score
                item["fp_score"] = fp_score
                item["final_score"] = final_score
                item["score"] = final_score
            ranked = sorted(
                rerank_pool,
                key=lambda item: (-item["final_score"], -item["text_score"], item["structure_id"]),
            )[:k]
        else:
            ranked = []
    else:
        ranked = ranked_by_text[:k]

    if export_dir:
        os.makedirs(export_dir, exist_ok=True)

    neighbors: List[Dict[str, Any]] = []
    for rank, item in enumerate(ranked, start=1):
        provenance = item["provenance"]
        policy_blocks_export = provenance.get("allow_export") in (0, False) and not demo_export
        content_redacted = redacted and provenance.get("allow_export") in (0, False)
        neighbor: Dict[str, Any] = {
            "rank": rank,
            "structure_id": item["structure_id"],
            "score": item["score"],
            "provenance": provenance,
            "redacted": bool(content_redacted),
        }
        if hybrid:
            neighbor["text_score"] = item.get("text_score", item["score"])
            neighbor["fp_score"] = item.get("fp_score", 0.0)
            neighbor["final_score"] = item.get("final_score", item["score"])
        if rank <= show_text_top:
            text_doc = _load_display_text_doc(conn, item["structure_id"], text_engine, resolved_text_view)
            if content_redacted and "text" in text_doc:
                text_doc.pop("text", None)
                text_doc["error"] = text_doc.get("error") or "redacted_by_policy"
            neighbor["text_doc"] = text_doc
        if export_dir is not None:
            if rank > export_top:
                neighbor["cif_export"] = {"status": "skipped"}
            elif policy_blocks_export:
                neighbor["cif_export"] = {
                    "status": "blocked",
                    "error": "allow_export=0 and demo_export=false",
                }
            else:
                cif_row = conn.execute(
                    "SELECT cif_text FROM structures WHERE structure_id = ?",
                    (item["structure_id"],),
                ).fetchone()
                if cif_row is None or cif_row["cif_text"] is None:
                    neighbor["cif_export"] = {"status": "error", "error": "cif_missing"}
                else:
                    try:
                        filename = _safe_cif_filename(item["structure_id"]) + ".cif"
                        out_path = os.path.join(export_dir, filename)
                        with open(out_path, "w", encoding="utf-8") as handle:
                            handle.write(cif_row["cif_text"])
                        neighbor["cif_export"] = {"status": "exported", "path": out_path}
                    except Exception as exc:  # pylint: disable=broad-except
                        neighbor["cif_export"] = {"status": "error", "error": str(exc)}
        neighbors.append(neighbor)

    conn.close()
    return _result_payload(
        status="ok",
        query=query,
        neighbors=neighbors,
        errors=None,
        backend_status=backend_status,
    )


def _ensure_seq_embedding(
    structure_id: str,
    db_path: Optional[str],
    format: str,
    model_name: str,
    model_version: str,
) -> Optional[List[float]]:
    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT vector_json FROM structure_embeddings "
        "WHERE structure_id = ? AND modality = 'seq' AND model_name = ? AND model_version = ?",
        (structure_id, model_name, model_version),
    ).fetchone()
    if row is not None:
        vector = json.loads(row["vector_json"])
        conn.close()
        return vector

    if not _allow_derivatives(structure_id, db_path):
        conn.close()
        return None

    row = conn.execute(
        "SELECT cif_text FROM structures WHERE structure_id = ?",
        (structure_id,),
    ).fetchone()
    if row is None or row["cif_text"] is None:
        conn.close()
        return None

    seq_text = canonicalize_cif(row["cif_text"])
    vector = embed_text(seq_text, model_name=model_name, model_version=model_version)
    conn.execute(
        "INSERT OR REPLACE INTO structure_sequences (structure_id, format, seq_text, input_hash, generated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (structure_id, format, seq_text, stable_hash({"format": format, "seq_text": seq_text}), now_iso_utc()),
    )
    conn.execute(
        "INSERT OR REPLACE INTO structure_embeddings "
        "(structure_id, modality, model_name, model_version, vector_json, dim, input_hash, generated_at) "
        "VALUES (?, 'seq', ?, ?, ?, ?, ?, ?)",
        (
            structure_id,
            model_name,
            model_version,
            json.dumps(vector),
            len(vector),
            stable_hash({"format": format, "seq_text": seq_text, "model": model_name}),
            now_iso_utc(),
        ),
    )
    conn.commit()
    conn.close()
    return vector


def similar_seq(
    *,
    structure_id: str,
    db_path: Optional[str],
    k: int = 10,
    format: str = "cif_canon",
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> Dict[str, Any]:
    if model_name is None:
        model_name = DEFAULT_MODEL_NAME
    model_version = resolve_model_version(model_name, model_version)

    query_vector = _ensure_seq_embedding(structure_id, db_path, format, model_name, model_version)
    if query_vector is None:
        return {"error": "embedding_missing", "structure_id": structure_id}

    conn = connect(db_path)
    init_db(conn)

    rows = conn.execute(
        "SELECT e.structure_id, e.vector_json, s.seq_text, m.formula, m.elements_csv, "
        "p.source, p.source_id, p.retrieved_at, p.allow_export "
        "FROM structure_embeddings e "
        "JOIN structure_sequences s ON s.structure_id = e.structure_id AND s.format = ? "
        "JOIN metadata m ON m.structure_id = e.structure_id "
        "JOIN provenance p ON p.structure_id = e.structure_id "
        "WHERE e.modality = 'seq' AND e.model_name = ? AND e.model_version = ?",
        (format, model_name, model_version),
    ).fetchall()
    conn.close()

    neighbors = []
    query_tokens = set()
    for row in rows:
        if row["structure_id"] == structure_id:
            query_tokens = set((row["seq_text"] or "").split())
            break

    for row in rows:
        sid = row["structure_id"]
        if sid == structure_id:
            continue
        vector = json.loads(row["vector_json"])
        distance = l2_distance(query_vector, vector)
        tokens = set((row["seq_text"] or "").split())
        overlap = len(query_tokens & tokens) if query_tokens else 0
        union = len(query_tokens | tokens) if query_tokens else len(tokens)
        jaccard = overlap / union if union else 0.0
        payload = {
            "structure_id": sid,
            "distance": distance,
            "why": {"token_overlap": overlap, "jaccard": round(jaccard, 4)},
            "provenance": {
                "source": row["source"],
                "source_id": row["source_id"],
                "retrieved_at": row["retrieved_at"],
                "allow_export": row["allow_export"],
            },
            "metadata": {
                "formula": row["formula"],
                "elements": elements_from_csv(row["elements_csv"]),
            },
        }
        neighbors.append(_redact_if_needed(payload))

    neighbors.sort(key=lambda n: (n.get("distance", 0.0), n.get("structure_id", "")))
    return {
        "query": {"structure_id": structure_id, "format": format, "model_name": model_name, "k": k},
        "neighbors": neighbors[: max(1, k)],
    }


def similar_struct(
    *,
    structure_id: str,
    db_path: Optional[str],
    method: str = "fp.simple.v1",
    k: int = 10,
) -> Dict[str, Any]:
    result = similar_structures(structure_id=structure_id, db_path=db_path, k=k)
    if "error" in result:
        return result

    neighbors = []
    for neighbor in result.get("neighbors", []):
        payload = dict(neighbor)
        neighbors.append(_redact_if_needed(payload))

    return {
        "query": {"structure_id": structure_id, "method": method, "k": k},
        "neighbors": neighbors,
    }


def similar_hybrid(
    *,
    structure_id: str,
    db_path: Optional[str],
    k: int = 10,
    sources: List[str],
    alpha: float = 0.5,
    beta: float = 0.5,
    gamma: float = 1.0,
) -> Dict[str, Any]:
    source_results: Dict[str, Dict[str, Any]] = {}
    if "text" in sources:
        source_results["text"] = similar_text(structure_id=structure_id, db_path=db_path, k=k)
    if "struct" in sources:
        source_results["struct"] = similar_struct(structure_id=structure_id, db_path=db_path, k=k)
    if "seq" in sources:
        source_results["seq"] = similar_seq(structure_id=structure_id, db_path=db_path, k=k)

    weights = {"text": alpha, "struct": beta, "seq": gamma}
    fused: Dict[str, Dict[str, Any]] = {}

    for source, result in source_results.items():
        neighbors = result.get("neighbors", [])
        for rank, neighbor in enumerate(neighbors, start=1):
            sid = neighbor.get("structure_id")
            if not sid:
                continue
            entry = fused.setdefault(
                sid,
                {
                    "structure_id": sid,
                    "sources": {},
                    "provenance": neighbor.get("provenance"),
                    "metadata": neighbor.get("metadata"),
                },
            )
            entry["sources"][source] = {
                "rank": rank,
                "distance": neighbor.get("distance"),
                "why": neighbor.get("why"),
            }
            score = weights.get(source, 1.0) / (60 + rank)
            entry["fused_score"] = entry.get("fused_score", 0.0) + score

    fused_list = list(fused.values())
    fused_list.sort(key=lambda item: (-item.get("fused_score", 0.0), item.get("structure_id", "")))

    return {
        "query": {"structure_id": structure_id, "sources": sources, "k": k},
        "neighbors": fused_list[: max(1, k)],
    }
