import os
import sqlite3
from typing import Any, Dict, List, Optional

from .db import resolve_db_path
from .fingerprint import FINGERPRINT_METHOD, FINGERPRINT_VERSION


REQUIRED_BASE_TABLES = (
    "structures",
    "metadata",
    "provenance",
    "text_docs",
    "text_embeddings",
)


def _connect_existing(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return 0
    return int(row[0])


def _group_available_embedding_spaces(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT td.engine, td.text_view, te.embed_engine, te.model, te.model_version, "
        "COUNT(*) AS row_count, COUNT(DISTINCT td.structure_id) AS structure_count "
        "FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        "WHERE te.status = 'OK' "
        "GROUP BY td.engine, td.text_view, te.embed_engine, te.model, te.model_version "
        "ORDER BY structure_count DESC, td.engine ASC, td.text_view ASC, te.embed_engine ASC, te.model ASC, te.model_version ASC"
    ).fetchall()
    return [
        {
            "text_engine": row["engine"],
            "text_view": row["text_view"],
            "embed_engine": row["embed_engine"],
            "model_name": row["model"],
            "model_version": row["model_version"],
            "row_count": int(row["row_count"]),
            "structure_count": int(row["structure_count"]),
        }
        for row in rows
    ]


def _group_available_text_corpora(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT engine, text_view, status, COUNT(*) AS row_count "
        "FROM text_docs "
        "GROUP BY engine, text_view, status "
        "ORDER BY engine ASC, text_view ASC, status ASC"
    ).fetchall()
    return [
        {
            "text_engine": row["engine"],
            "text_view": row["text_view"],
            "status": row["status"],
            "row_count": int(row["row_count"]),
        }
        for row in rows
    ]


def _base_payload(
    *,
    db_path: str,
    surface: str,
    query_mode: str,
    text_engine: str,
    text_view: str,
    embed_engine: str,
    model_name: str,
    model_version: str,
    require_fingerprint_index: bool,
) -> Dict[str, Any]:
    return {
        "ready": False,
        "state": "backend_not_ready",
        "message": "Backend readiness has not been evaluated.",
        "surface": surface,
        "query_mode": query_mode,
        "db_path": db_path,
        "db_exists": os.path.exists(db_path),
        "db_size_bytes": os.path.getsize(db_path) if os.path.exists(db_path) else None,
        "schema_present": False,
        "missing_tables": list(REQUIRED_BASE_TABLES),
        "corpus": {
            "structure_count": 0,
            "metadata_count": 0,
            "provenance_count": 0,
            "text_doc_count": 0,
            "text_doc_ok_count": 0,
        },
        "requested_space": {
            "text_engine": text_engine,
            "text_view": text_view,
            "embed_engine": embed_engine,
            "model_name": model_name,
            "model_version": model_version,
            "text_doc_count": 0,
            "text_doc_ok_count": 0,
            "text_doc_failed_count": 0,
            "embedding_row_count": 0,
            "embedding_ok_count": 0,
            "embedding_failed_count": 0,
            "distinct_structure_count": 0,
            "other_candidate_count": None,
        },
        "embedding_space": {
            "total_ok_count": 0,
            "available_spaces": [],
        },
        "fingerprint_index": {
            "required": bool(require_fingerprint_index),
            "present": False,
            "row_count": 0,
            "fingerprint_method": FINGERPRINT_METHOD,
            "fingerprint_version": FINGERPRINT_VERSION,
        },
    }


def inspect_backend_readiness(
    *,
    db_path: str,
    surface: str,
    query_mode: str,
    text_engine: str,
    text_view: str,
    embed_engine: str,
    model_name: str,
    model_version: str,
    require_fingerprint_index: bool = False,
    query_structure_id: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_db_path = os.path.abspath(resolve_db_path(db_path or None))
    payload = _base_payload(
        db_path=resolved_db_path,
        surface=surface,
        query_mode=query_mode,
        text_engine=text_engine,
        text_view=text_view,
        embed_engine=embed_engine,
        model_name=model_name,
        model_version=model_version,
        require_fingerprint_index=require_fingerprint_index,
    )
    if query_structure_id:
        payload["requested_space"]["query_structure_id"] = query_structure_id
    if not payload["db_exists"]:
        payload["state"] = "missing_db"
        payload["message"] = "Database file is missing."
        return payload

    try:
        conn = _connect_existing(resolved_db_path)
    except sqlite3.Error as exc:
        payload["state"] = "db_unopenable"
        payload["message"] = f"Database file could not be opened: {exc}"
        return payload

    try:
        table_rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        tables = {str(row["name"]) for row in table_rows}
        missing_tables = [name for name in REQUIRED_BASE_TABLES if name not in tables]
        payload["missing_tables"] = missing_tables
        payload["schema_present"] = not missing_tables
        if missing_tables:
            payload["state"] = "db_schema_missing"
            payload["message"] = "Database schema is missing required CrystalDB tables."
            return payload

        payload["corpus"] = {
            "structure_count": _count(conn, "SELECT COUNT(*) FROM structures"),
            "metadata_count": _count(conn, "SELECT COUNT(*) FROM metadata"),
            "provenance_count": _count(conn, "SELECT COUNT(*) FROM provenance"),
            "text_doc_count": _count(conn, "SELECT COUNT(*) FROM text_docs"),
            "text_doc_ok_count": _count(conn, "SELECT COUNT(*) FROM text_docs WHERE status = 'OK'"),
        }

        requested_doc_where = ["text_view = ?"]
        requested_doc_params: List[Any] = [text_view]
        if text_engine != "auto":
            requested_doc_where.append("engine = ?")
            requested_doc_params.append(text_engine)
        requested_doc_where_sql = " AND ".join(requested_doc_where)

        requested_emb_where = [
            "td.text_view = ?",
            "te.embed_engine = ?",
            "te.model = ?",
            "te.model_version = ?",
        ]
        requested_emb_params: List[Any] = [text_view, embed_engine, model_name, model_version]
        if text_engine != "auto":
            requested_emb_where.append("td.engine = ?")
            requested_emb_params.append(text_engine)
        requested_emb_where_sql = " AND ".join(requested_emb_where)

        requested_space = {
            "text_engine": text_engine,
            "text_view": text_view,
            "embed_engine": embed_engine,
            "model_name": model_name,
            "model_version": model_version,
            "text_doc_count": _count(
                conn,
                f"SELECT COUNT(*) FROM text_docs WHERE {requested_doc_where_sql}",
                tuple(requested_doc_params),
            ),
            "text_doc_ok_count": _count(
                conn,
                f"SELECT COUNT(*) FROM text_docs WHERE status = 'OK' AND {requested_doc_where_sql}",
                tuple(requested_doc_params),
            ),
            "text_doc_failed_count": _count(
                conn,
                f"SELECT COUNT(*) FROM text_docs WHERE status != 'OK' AND {requested_doc_where_sql}",
                tuple(requested_doc_params),
            ),
            "embedding_row_count": _count(
                conn,
                "SELECT COUNT(*) "
                "FROM text_embeddings te JOIN text_docs td ON td.id = te.text_doc_id "
                f"WHERE {requested_emb_where_sql}",
                tuple(requested_emb_params),
            ),
            "embedding_ok_count": _count(
                conn,
                "SELECT COUNT(*) "
                "FROM text_embeddings te JOIN text_docs td ON td.id = te.text_doc_id "
                f"WHERE te.status = 'OK' AND {requested_emb_where_sql}",
                tuple(requested_emb_params),
            ),
            "embedding_failed_count": _count(
                conn,
                "SELECT COUNT(*) "
                "FROM text_embeddings te JOIN text_docs td ON td.id = te.text_doc_id "
                f"WHERE te.status != 'OK' AND {requested_emb_where_sql}",
                tuple(requested_emb_params),
            ),
            "distinct_structure_count": _count(
                conn,
                "SELECT COUNT(DISTINCT td.structure_id) "
                "FROM text_embeddings te JOIN text_docs td ON td.id = te.text_doc_id "
                f"WHERE te.status = 'OK' AND {requested_emb_where_sql}",
                tuple(requested_emb_params),
            ),
            "other_candidate_count": None,
        }
        if query_structure_id:
            requested_space["other_candidate_count"] = _count(
                conn,
                "SELECT COUNT(DISTINCT td.structure_id) "
                "FROM text_embeddings te JOIN text_docs td ON td.id = te.text_doc_id "
                f"WHERE te.status = 'OK' AND {requested_emb_where_sql} AND td.structure_id != ?",
                tuple(requested_emb_params + [query_structure_id]),
            )
        payload["requested_space"] = requested_space

        total_ok_embeddings = _count(conn, "SELECT COUNT(*) FROM text_embeddings WHERE status = 'OK'")
        payload["embedding_space"] = {
            "total_ok_count": total_ok_embeddings,
            "available_spaces": _group_available_embedding_spaces(conn),
            "available_text_corpora": _group_available_text_corpora(conn),
        }

        fingerprint_table_present = "structure_fingerprints" in tables
        fingerprint_count = 0
        if fingerprint_table_present:
            fingerprint_count = _count(
                conn,
                "SELECT COUNT(*) FROM structure_fingerprints WHERE fingerprint_method = ? AND fingerprint_version = ?",
                (FINGERPRINT_METHOD, FINGERPRINT_VERSION),
            )
        payload["fingerprint_index"] = {
            "required": bool(require_fingerprint_index),
            "present": fingerprint_table_present and fingerprint_count > 0,
            "row_count": fingerprint_count,
            "fingerprint_method": FINGERPRINT_METHOD,
            "fingerprint_version": FINGERPRINT_VERSION,
        }

        if payload["corpus"]["structure_count"] <= 0:
            payload["state"] = "empty_corpus"
            payload["message"] = "Database schema exists, but the corpus is empty."
            return payload

        if requested_space["embedding_ok_count"] > 0:
            if require_fingerprint_index and fingerprint_count <= 0:
                payload["state"] = "missing_index"
                payload["message"] = "Hybrid retrieval requested, but the structure fingerprint index is missing."
                return payload
            payload["ready"] = True
            payload["state"] = "backend_ready"
            payload["message"] = "Backend is ready for retrieval in the requested space."
            return payload

        if total_ok_embeddings > 0:
            if requested_space["text_doc_ok_count"] <= 0:
                payload["state"] = "query_tool_mismatch"
                payload["message"] = "Requested tool/text view does not match any populated text corpus, but other embedding spaces are available."
                return payload
            payload["state"] = "missing_embedding_space"
            payload["message"] = "Requested embedding space is not populated, but other embedding spaces are available."
            return payload

        if payload["corpus"]["text_doc_ok_count"] > 0:
            payload["state"] = "missing_embedding_space"
            payload["message"] = "Text corpus exists, but no usable embeddings are loaded."
            return payload

        if payload["corpus"]["text_doc_count"] > 0:
            payload["state"] = "backend_not_ready"
            payload["message"] = "Text documents exist, but none are marked usable."
            return payload

        payload["state"] = "candidate_set_empty"
        payload["message"] = "Database is present, but no text corpus has been loaded."
        return payload
    finally:
        conn.close()


def backend_status_to_error(backend_status: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "code": backend_status.get("state") or "backend_not_ready",
        "message": backend_status.get("message") or "Backend is not ready.",
        "diagnostics": {
            "backend_ready": bool(backend_status.get("ready")),
            "db_path": backend_status.get("db_path"),
        },
    }
