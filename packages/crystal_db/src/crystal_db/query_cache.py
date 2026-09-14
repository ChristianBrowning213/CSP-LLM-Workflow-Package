import hashlib
import json
from typing import Any, Dict, List, Optional

from .db import connect, init_db
from .embeddings import DEFAULT_MODEL_NAME, embed_text, resolve_embed_engine, resolve_model_version
from .utils import now_iso_utc


def normalize_query_text(value: str) -> str:
    return " ".join((value or "").split())


def query_text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_query_cache_key(
    *,
    embed_engine: str,
    model_name: str,
    model_version: str,
    query_sha256: str,
) -> str:
    return f"{embed_engine}|{model_name}|{model_version}|{query_sha256}"


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


def get_cached_query_vector(
    *,
    query_text: str,
    embed_engine: str,
    model_name: Optional[str],
    model_version: Optional[str],
    db_path: Optional[str],
) -> Optional[List[float]]:
    if not db_path:
        return None
    resolved_model_name = model_name or DEFAULT_MODEL_NAME
    resolved_embed_engine = resolve_embed_engine(embed_engine, resolved_model_name)
    resolved_model_version = resolve_model_version(
        resolved_model_name,
        model_version,
        embed_engine=resolved_embed_engine,
    )
    normalized_text = normalize_query_text(query_text)
    sha_value = query_text_sha256(normalized_text)

    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT vector, status FROM query_embeddings "
        "WHERE query_sha256 = ? AND embed_engine = ? AND model = ? AND model_version = ? "
        "ORDER BY id DESC LIMIT 1",
        (sha_value, resolved_embed_engine, resolved_model_name, resolved_model_version),
    ).fetchone()
    conn.close()
    if row is None or str(row["status"]).upper() != "OK":
        return None
    return _decode_vector(row["vector"])


def preembed_case_queries(
    cases: List[Dict[str, Any]],
    embed_engine: str,
    model_name: str,
    model_version: str,
    *,
    db_path: Optional[str] = None,
    cache_table: bool = True,
) -> Dict[str, Dict[str, List[float]]]:
    resolved_model_name = model_name or DEFAULT_MODEL_NAME
    resolved_embed_engine = resolve_embed_engine(embed_engine, resolved_model_name)
    resolved_model_version = resolve_model_version(
        resolved_model_name,
        model_version,
        embed_engine=resolved_embed_engine,
    )

    conn = None
    if db_path and cache_table:
        conn = connect(db_path)
        init_db(conn)

    case_vectors: Dict[str, List[float]] = {}
    cache_vectors: Dict[str, List[float]] = {}

    sorted_cases = sorted(
        cases,
        key=lambda item: str(item.get("case_id") or ""),
    )
    for case in sorted_cases:
        case_id = str(case.get("case_id") or "")
        normalized_text = normalize_query_text(str(case.get("query") or ""))
        sha_value = query_text_sha256(normalized_text)
        cache_key = build_query_cache_key(
            embed_engine=resolved_embed_engine,
            model_name=resolved_model_name,
            model_version=resolved_model_version,
            query_sha256=sha_value,
        )
        if cache_key in cache_vectors:
            case_vectors[case_id] = cache_vectors[cache_key]
            continue

        cached_vector: Optional[List[float]] = None
        if conn is not None:
            row = conn.execute(
                "SELECT vector, status FROM query_embeddings "
                "WHERE query_sha256 = ? AND embed_engine = ? AND model = ? AND model_version = ? "
                "ORDER BY id DESC LIMIT 1",
                (sha_value, resolved_embed_engine, resolved_model_name, resolved_model_version),
            ).fetchone()
            if row is not None and str(row["status"]).upper() == "OK":
                cached_vector = _decode_vector(row["vector"])
        if cached_vector is not None:
            cache_vectors[cache_key] = cached_vector
            case_vectors[case_id] = cached_vector
            continue

        try:
            vector = embed_text(
                normalized_text,
                model_name=resolved_model_name,
                model_version=resolved_model_version,
                embed_engine=resolved_embed_engine,
            )
        except Exception as exc:  # pylint: disable=broad-except
            if conn is not None:
                ts = now_iso_utc()
                conn.execute(
                    "INSERT INTO query_embeddings "
                    "(query_sha256, query_text, embed_engine, model, model_version, dim, vector, status, "
                    "error_type, error_message, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(query_sha256, embed_engine, model, model_version) DO UPDATE SET "
                    "query_text = excluded.query_text, dim = excluded.dim, vector = excluded.vector, "
                    "status = excluded.status, error_type = excluded.error_type, "
                    "error_message = excluded.error_message, updated_at = excluded.updated_at",
                    (
                        sha_value,
                        normalized_text,
                        resolved_embed_engine,
                        resolved_model_name,
                        resolved_model_version,
                        None,
                        None,
                        "ERROR",
                        "embedding_failed",
                        str(exc),
                        ts,
                        ts,
                    ),
                )
                conn.commit()
            if conn is not None:
                conn.close()
            raise RuntimeError(f"query embedding failed for case_id={case_id}: {exc}") from exc

        cache_vectors[cache_key] = vector
        case_vectors[case_id] = vector
        if conn is not None:
            ts = now_iso_utc()
            conn.execute(
                "INSERT INTO query_embeddings "
                "(query_sha256, query_text, embed_engine, model, model_version, dim, vector, status, "
                "error_type, error_message, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(query_sha256, embed_engine, model, model_version) DO UPDATE SET "
                "query_text = excluded.query_text, dim = excluded.dim, vector = excluded.vector, "
                "status = excluded.status, error_type = excluded.error_type, "
                "error_message = excluded.error_message, updated_at = excluded.updated_at",
                (
                    sha_value,
                    normalized_text,
                    resolved_embed_engine,
                    resolved_model_name,
                    resolved_model_version,
                    len(vector),
                    json.dumps(vector),
                    "OK",
                    None,
                    None,
                    ts,
                    ts,
                ),
            )

    if conn is not None:
        conn.commit()
        conn.close()
    return {"case_vectors": case_vectors, "cache_vectors": cache_vectors}
