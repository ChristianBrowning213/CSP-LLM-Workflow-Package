import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Sequence

from .audit_log import AuditLogger
from .db import connect, init_db
from .embeddings import (
    DEFAULT_DIM,
    DEFAULT_EMBED_ENGINE,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    EmbeddingDocumentError,
    embed_document_text,
    resolve_embed_engine,
    resolve_model_version,
)
from .textgen import TEXT_ENGINE_VERSION, generate_text
from .utils import now_iso_utc, stable_hash

TEXT_STATUS_OK = "OK"
TEXT_STATUS_FAILED = "FAILED"
TEXT_VIEW_ROBOCRYS = "robocrys"
TEXT_VIEW_CAPTION = "caption"


def _resolve_text_view(engine: str, text_view: Optional[str]) -> str:
    engine_value = (engine or "").strip().lower()
    value = (text_view or "").strip().lower()
    if value:
        if value not in (TEXT_VIEW_ROBOCRYS, TEXT_VIEW_CAPTION):
            raise ValueError(f"unsupported text_view: {text_view}")
        return value
    return TEXT_VIEW_CAPTION if engine_value == "caption" else TEXT_VIEW_ROBOCRYS


def _fetch_structure_ids(db_path: Optional[str]) -> List[str]:
    conn = connect(db_path)
    init_db(conn)
    rows = conn.execute("SELECT structure_id FROM structures ORDER BY structure_id").fetchall()
    conn.close()
    return [row["structure_id"] for row in rows]


def _chunked(items: Sequence[Dict[str, Any]], size: int) -> List[Sequence[Dict[str, Any]]]:
    if size <= 0:
        size = 1
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_error_type(error: Any, message: Optional[str] = None) -> str:
    text = ((message or "") + " " + str(error or "")).strip()
    lower = text.lower()
    if "2d components don't all have the same orientation" in lower:
        return "ROBOCRYS_VDW_ORIENTATION"

    code = str(error or "UNKNOWN_ERROR").strip()
    if not code:
        return "UNKNOWN_ERROR"
    normalized = []
    for char in code.upper():
        if char.isalnum():
            normalized.append(char)
        else:
            normalized.append("_")
    result = "".join(normalized).strip("_")
    return result or "UNKNOWN_ERROR"


def _sql_in_clause(values: Sequence[str]) -> str:
    if not values:
        return ""
    return ", ".join(["?"] * len(values))


def _validate_shard_config(*, shard_count: int, shard_index: int) -> None:
    if shard_count <= 0:
        raise ValueError("shard_count must be >= 1")
    if shard_count == 1 and shard_index != 0:
        raise ValueError("shard_index must be 0 when shard_count is 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError(f"shard_index must be in [0, {shard_count - 1}]")


def _assign_shard(structure_id: str, shard_count: int) -> int:
    digest = hashlib.sha256((structure_id or "").encode("utf-8")).hexdigest()
    return int(digest, 16) % shard_count


def _filter_shard_ids(*, structure_ids: Sequence[str], shard_count: int, shard_index: int) -> List[str]:
    if shard_count == 1:
        return list(structure_ids)
    return [sid for sid in structure_ids if _assign_shard(sid, shard_count) == shard_index]


def _write_snapshot(path: str, payload: Dict[str, Any]) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    temp_path = f"{path}.tmp.{os.getpid()}"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp_path, path)


def _select_pending_text_doc_structures(
    *,
    conn,
    engine: str,
    text_view: str,
    structure_ids: Optional[List[str]],
    limit: Optional[int],
    retry_failed: bool,
    force: bool,
    shard_count: int,
    shard_index: int,
) -> List[str]:
    params: List[Any] = [engine, text_view]
    where = []
    where_params: List[Any] = []
    if structure_ids:
        where.append(f"s.structure_id IN ({_sql_in_clause(structure_ids)})")
        where_params.extend(structure_ids)

    if force:
        pending_filter = "1=1"
        pending_params: List[Any] = []
    elif retry_failed:
        pending_filter = "(td.id IS NULL OR td.status = ?)"
        pending_params = [TEXT_STATUS_FAILED]
    else:
        pending_filter = "td.id IS NULL"
        pending_params = []

    sql = (
        "SELECT s.structure_id "
        "FROM structures s "
        "LEFT JOIN text_docs td ON td.structure_id = s.structure_id "
        "AND td.engine = ? AND td.text_view = ? "
        f"WHERE {pending_filter}"
    )
    if where:
        sql += " AND " + " AND ".join(where)
    params.extend(pending_params)
    params.extend(where_params)
    sql += " ORDER BY s.structure_id"

    rows = conn.execute(sql, tuple(params)).fetchall()
    pending_ids = [row["structure_id"] for row in rows]
    pending_ids = _filter_shard_ids(
        structure_ids=pending_ids,
        shard_count=shard_count,
        shard_index=shard_index,
    )
    if limit is not None and limit > 0:
        pending_ids = pending_ids[:limit]
    return pending_ids


def _upsert_text_doc(
    *,
    conn,
    structure_id: str,
    engine: str,
    text_view: str,
    engine_version: str,
    text: Optional[str],
    text_sha256: Optional[str],
    status: str,
    error_type: Optional[str],
    error_message: Optional[str],
) -> None:
    ts = now_iso_utc()
    conn.execute(
        "INSERT INTO text_docs "
        "(structure_id, engine, text_view, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(structure_id, engine, text_view) DO UPDATE SET "
        "engine_version = excluded.engine_version, "
        "text = excluded.text, text_sha256 = excluded.text_sha256, status = excluded.status, "
        "error_type = excluded.error_type, error_message = excluded.error_message, updated_at = excluded.updated_at",
        (
            structure_id,
            engine,
            text_view,
            engine_version,
            text,
            text_sha256,
            status,
            error_type,
            error_message,
            ts,
            ts,
        ),
    )


def _flush_log_entries(logger: AuditLogger, entries: List[Dict[str, Any]]) -> None:
    if not entries:
        return
    for entry in entries:
        logger.log_tool_call(
            entry["tool_name"],
            entry["input_payload"],
            entry["output_payload"],
            entry["started_at"],
            entry["ended_at"],
            entry["status"],
            entry.get("error_text"),
        )
    entries.clear()


def generate_text_docs(
    *,
    db_path: Optional[str],
    engine: str = "baseline",
    text_view: Optional[str] = None,
    engine_version: str = TEXT_ENGINE_VERSION,
    structure_ids: Optional[List[str]] = None,
    limit: Optional[int] = None,
    batch: int = 32,
    progress_every: int = 100,
    retry_failed: bool = False,
    force: bool = False,
    shard_count: int = 1,
    shard_index: int = 0,
    snapshot_path: Optional[str] = None,
    snapshot_every: int = 0,
    run_name: Optional[str] = None,
) -> Dict[str, Any]:
    if batch <= 0:
        batch = 1
    if progress_every <= 0:
        progress_every = 1
    if snapshot_every < 0:
        snapshot_every = 0
    _validate_shard_config(shard_count=shard_count, shard_index=shard_index)
    resolved_text_view = _resolve_text_view(engine, text_view)

    conn = connect(db_path)
    init_db(conn)
    pending = _select_pending_text_doc_structures(
        conn=conn,
        engine=engine,
        text_view=resolved_text_view,
        structure_ids=structure_ids,
        limit=limit,
        retry_failed=retry_failed,
        force=force,
        shard_count=shard_count,
        shard_index=shard_index,
    )
    total = len(pending)
    if total == 0:
        conn.close()
        return {
            "engine": engine,
            "text_view": resolved_text_view,
            "engine_version": engine_version,
            "selected": 0,
            "ok": 0,
            "failed": 0,
            "processed": 0,
        }

    logger = AuditLogger(
        db_path,
        run_name,
        {"mode": "gen-text", "engine": engine, "text_view": resolved_text_view, "engine_version": engine_version},
    )
    log_entries: List[Dict[str, Any]] = []
    ok_count = 0
    failed_count = 0
    processed = 0
    pending_since_commit = 0
    started_ts = time.time()
    last_structure_id: Optional[str] = None

    for sid in pending:
        last_structure_id = sid
        started = now_iso_utc()
        try:
            text_info = generate_text(structure_id=sid, engine=engine, db_path=db_path)
            if "error" in text_info:
                error_code = text_info["error"]
                error_type = _normalize_error_type(error_code)
                error_message = str(error_code)
                _upsert_text_doc(
                    conn=conn,
                    structure_id=sid,
                    engine=engine,
                    text_view=resolved_text_view,
                    engine_version=engine_version,
                    text=None,
                    text_sha256=None,
                    status=TEXT_STATUS_FAILED,
                    error_type=error_type,
                    error_message=error_message,
                )
                failed_count += 1
                log_entries.append(
                    {
                        "tool_name": "gen_text",
                        "input_payload": {"structure_id": sid, "engine": engine, "text_view": resolved_text_view},
                        "output_payload": {"error": error_code, "error_type": error_type},
                        "started_at": started,
                        "ended_at": now_iso_utc(),
                        "status": "error",
                        "error_text": error_message,
                    }
                )
            else:
                text_value = text_info["text"]
                doc_version = text_info.get("version") or engine_version
                text_sha256 = _sha256_text(text_value)
                _upsert_text_doc(
                    conn=conn,
                    structure_id=sid,
                    engine=engine,
                    text_view=resolved_text_view,
                    engine_version=doc_version,
                    text=text_value,
                    text_sha256=text_sha256,
                    status=TEXT_STATUS_OK,
                    error_type=None,
                    error_message=None,
                )
                ok_count += 1
                log_entries.append(
                    {
                        "tool_name": "gen_text",
                        "input_payload": {"structure_id": sid, "engine": engine, "text_view": resolved_text_view},
                        "output_payload": {
                            "structure_id": sid,
                            "engine": engine,
                            "text_view": resolved_text_view,
                            "engine_version": doc_version,
                        },
                        "started_at": started,
                        "ended_at": now_iso_utc(),
                        "status": "ok",
                    }
                )
        except Exception as exc:  # pylint: disable=broad-except
            error_message = str(exc)
            error_type = _normalize_error_type(exc, message=error_message)
            _upsert_text_doc(
                conn=conn,
                structure_id=sid,
                engine=engine,
                text_view=resolved_text_view,
                engine_version=engine_version,
                text=None,
                text_sha256=None,
                status=TEXT_STATUS_FAILED,
                error_type=error_type,
                error_message=error_message,
            )
            failed_count += 1
            log_entries.append(
                {
                    "tool_name": "gen_text",
                    "input_payload": {"structure_id": sid, "engine": engine, "text_view": resolved_text_view},
                    "output_payload": {"error": error_message, "error_type": error_type},
                    "started_at": started,
                    "ended_at": now_iso_utc(),
                    "status": "error",
                    "error_text": error_message,
                }
            )

        processed += 1
        pending_since_commit += 1
        if pending_since_commit >= batch:
            conn.commit()
            _flush_log_entries(logger, log_entries)
            pending_since_commit = 0
        if processed % progress_every == 0 or processed == total:
            elapsed = max(0.001, time.time() - started_ts)
            rate = processed / elapsed
            print(
                f"[gen-text] {processed}/{total} processed "
                f"(ok={ok_count}, failed={failed_count}, engine={engine}, text_view={resolved_text_view}, "
                f"version={engine_version}, rate={rate:.2f}/s, last_structure_id={sid})"
            )
        if snapshot_path and snapshot_every > 0 and processed % snapshot_every == 0:
            _write_snapshot(
                snapshot_path,
                {
                    "ts": now_iso_utc(),
                    "command": "gen-text",
                    "db": db_path,
                    "text_engine": engine,
                    "text_view": resolved_text_view,
                    "embed_engine": None,
                    "model": None,
                    "model_version": None,
                    "shard_count": shard_count,
                    "shard_index": shard_index,
                    "processed": processed,
                    "ok": ok_count,
                    "error": failed_count,
                    "last_structure_id": last_structure_id,
                    "last_text_doc_id": None,
                },
            )

    if pending_since_commit:
        conn.commit()
    _flush_log_entries(logger, log_entries)
    conn.close()

    if snapshot_path and snapshot_every > 0:
        _write_snapshot(
            snapshot_path,
            {
                "ts": now_iso_utc(),
                "command": "gen-text",
                "db": db_path,
                "text_engine": engine,
                "text_view": resolved_text_view,
                "embed_engine": None,
                "model": None,
                "model_version": None,
                "shard_count": shard_count,
                "shard_index": shard_index,
                "processed": processed,
                "ok": ok_count,
                "error": failed_count,
                "last_structure_id": last_structure_id,
                "last_text_doc_id": None,
            },
        )

    return {
        "engine": engine,
        "text_view": resolved_text_view,
        "engine_version": engine_version,
        "selected": total,
        "ok": ok_count,
        "failed": failed_count,
        "processed": processed,
        "run_id": logger.run_id,
    }


def _select_pending_embeddings(
    *,
    conn,
    text_engine: str,
    text_view: str,
    embed_engine: str,
    model: str,
    model_version: str,
    structure_ids: Optional[List[str]],
    limit: Optional[int],
    retry_failed: bool,
    force: bool,
    shard_count: int,
    shard_index: int,
) -> List[Dict[str, Any]]:
    params: List[Any] = [embed_engine, model, model_version, text_engine, text_view]
    where = []
    where_params: List[Any] = []
    if structure_ids:
        where.append(f"td.structure_id IN ({_sql_in_clause(structure_ids)})")
        where_params.extend(structure_ids)

    if force:
        pending_filter = "1=1"
        pending_params: List[Any] = []
    elif retry_failed:
        pending_filter = "(te.id IS NULL OR te.status = ?)"
        pending_params = [TEXT_STATUS_FAILED]
    else:
        pending_filter = "te.id IS NULL"
        pending_params = []

    sql = (
        "SELECT td.id, td.structure_id, td.engine, td.text_view, td.engine_version, td.text, td.text_sha256 "
        "FROM text_docs td "
        "LEFT JOIN text_embeddings te ON te.text_doc_id = td.id "
        "AND te.embed_engine = ? AND te.model = ? AND te.model_version = ? "
        "WHERE td.status = 'OK' AND td.engine = ? AND td.text_view = ? "
        f"AND {pending_filter}"
    )
    if where:
        sql += " AND " + " AND ".join(where)
    params.extend(pending_params)
    params.extend(where_params)
    sql += " ORDER BY td.structure_id"

    rows = conn.execute(sql, tuple(params)).fetchall()
    pending_items = [
        {
            "text_doc_id": row["id"],
            "structure_id": row["structure_id"],
            "engine": row["engine"],
            "text_view": row["text_view"],
            "engine_version": row["engine_version"],
            "text": row["text"] or "",
            "text_sha256": row["text_sha256"],
        }
        for row in rows
    ]
    if shard_count > 1:
        pending_items = [
            item
            for item in pending_items
            if _assign_shard(item["structure_id"], shard_count) == shard_index
        ]
    if limit is not None and limit > 0:
        pending_items = pending_items[:limit]
    return pending_items


def _upsert_text_embedding(
    *,
    conn,
    text_doc_id: int,
    embed_engine: str,
    model: str,
    model_version: str,
    status: str,
    vector: Optional[List[float]],
    error_type: Optional[str],
    error_message: Optional[str],
) -> None:
    ts = now_iso_utc()
    vector_json = json.dumps(vector) if vector is not None else None
    dim = len(vector) if vector is not None else None
    conn.execute(
        "INSERT INTO text_embeddings "
        "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(text_doc_id, embed_engine, model, model_version) DO UPDATE SET "
        "dim = excluded.dim, vector = excluded.vector, status = excluded.status, error_type = excluded.error_type, "
        "error_message = excluded.error_message, updated_at = excluded.updated_at",
        (
            text_doc_id,
            embed_engine,
            model,
            model_version,
            dim,
            vector_json,
            status,
            error_type,
            error_message,
            ts,
            ts,
        ),
    )


def _upsert_legacy_text_records(
    *,
    conn,
    structure_id: str,
    text_engine: str,
    text_engine_version: str,
    text: str,
    text_sha256: str,
    model_name: str,
    model_version: str,
    vector: List[float],
) -> None:
    ts = now_iso_utc()
    conn.execute(
        "INSERT OR REPLACE INTO structure_texts (structure_id, engine, version, text, input_hash, generated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (structure_id, text_engine, text_engine_version, text, text_sha256, ts),
    )
    embed_hash = stable_hash({"text_hash": text_sha256, "model": model_name, "version": model_version})
    conn.execute(
        "INSERT OR REPLACE INTO structure_embeddings "
        "(structure_id, modality, model_name, model_version, vector_json, dim, input_hash, generated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            structure_id,
            "text",
            model_name,
            model_version,
            json.dumps(vector),
            len(vector),
            embed_hash,
            ts,
        ),
    )


def _embed_items(
    *,
    items: Sequence[Dict[str, Any]],
    model_name: str,
    model_version: str,
    embed_engine: str,
) -> List[Dict[str, Any]]:
    if not items:
        return []
    results: List[Dict[str, Any]] = []
    for item in items:
        try:
            vector, meta = embed_document_text(
                item["text"],
                model_name=model_name,
                model_version=model_version,
                dim=DEFAULT_DIM,
                embed_engine=embed_engine,
            )
            results.append({"status": TEXT_STATUS_OK, "vector": vector, "meta": meta})
        except EmbeddingDocumentError as doc_exc:
            payload = doc_exc.to_payload()
            diagnostics = dict(payload.get("diagnostics") or {})
            diagnostics["structure_id"] = item.get("structure_id")
            diagnostics["text_engine"] = item.get("engine")
            diagnostics["text_view"] = item.get("text_view")
            payload["diagnostics"] = diagnostics
            message = json.dumps(payload, sort_keys=True)
            results.append(
                {
                    "status": TEXT_STATUS_FAILED,
                    "error_type": _normalize_error_type(payload.get("code"), message=message),
                    "error_message": message,
                }
            )
        except Exception as item_exc:  # pylint: disable=broad-except
            message = str(item_exc)
            results.append(
                {
                    "status": TEXT_STATUS_FAILED,
                    "error_type": _normalize_error_type(item_exc, message=message),
                    "error_message": message,
                }
            )
    return results


def embed_text_docs(
    *,
    db_path: Optional[str],
    text_engine: str = "baseline",
    text_view: Optional[str] = None,
    embed_engine: str = DEFAULT_EMBED_ENGINE,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: Optional[str] = DEFAULT_MODEL_VERSION,
    structure_ids: Optional[List[str]] = None,
    limit: Optional[int] = None,
    batch: int = 32,
    progress_every: int = 100,
    retry_failed: bool = False,
    force: bool = False,
    shard_count: int = 1,
    shard_index: int = 0,
    snapshot_path: Optional[str] = None,
    snapshot_every: int = 0,
    run_name: Optional[str] = None,
) -> Dict[str, Any]:
    if batch <= 0:
        batch = 1
    if progress_every <= 0:
        progress_every = 1
    if snapshot_every < 0:
        snapshot_every = 0
    _validate_shard_config(shard_count=shard_count, shard_index=shard_index)
    if model_name is None:
        model_name = DEFAULT_MODEL_NAME
    resolved_text_view = _resolve_text_view(text_engine, text_view)

    resolved_embed_engine = resolve_embed_engine(embed_engine, model_name)
    resolved_model_version = resolve_model_version(
        model_name,
        model_version,
        embed_engine=resolved_embed_engine,
    )

    conn = connect(db_path)
    init_db(conn)
    pending = _select_pending_embeddings(
        conn=conn,
        text_engine=text_engine,
        text_view=resolved_text_view,
        embed_engine=resolved_embed_engine,
        model=model_name,
        model_version=resolved_model_version,
        structure_ids=structure_ids,
        limit=limit,
        retry_failed=retry_failed,
        force=force,
        shard_count=shard_count,
        shard_index=shard_index,
    )
    total = len(pending)
    if total == 0:
        conn.close()
        return {
            "text_engine": text_engine,
            "text_view": resolved_text_view,
            "embed_engine": resolved_embed_engine,
            "model": model_name,
            "model_version": resolved_model_version,
            "selected": 0,
            "ok": 0,
            "failed": 0,
            "processed": 0,
        }

    logger = AuditLogger(
        db_path,
        run_name,
        {
            "mode": "embed-text",
            "text_engine": text_engine,
            "text_view": resolved_text_view,
            "embed_engine": resolved_embed_engine,
            "model": model_name,
            "model_version": resolved_model_version,
        },
    )
    log_entries: List[Dict[str, Any]] = []
    ok_count = 0
    failed_count = 0
    processed = 0
    started_ts = time.time()
    last_structure_id: Optional[str] = None
    last_text_doc_id: Optional[int] = None

    for chunk in _chunked(pending, batch):
        outcomes = _embed_items(
            items=chunk,
            model_name=model_name,
            model_version=resolved_model_version,
            embed_engine=resolved_embed_engine,
        )
        for item, outcome in zip(chunk, outcomes):
            last_structure_id = item["structure_id"]
            last_text_doc_id = item["text_doc_id"]
            started = now_iso_utc()
            if outcome["status"] == TEXT_STATUS_OK:
                vector = outcome["vector"]
                meta = outcome.get("meta") or {}
                _upsert_text_embedding(
                    conn=conn,
                    text_doc_id=item["text_doc_id"],
                    embed_engine=resolved_embed_engine,
                    model=model_name,
                    model_version=resolved_model_version,
                    status=TEXT_STATUS_OK,
                    vector=vector,
                    error_type=None,
                    error_message=None,
                )
                if resolved_text_view == TEXT_VIEW_ROBOCRYS:
                    _upsert_legacy_text_records(
                        conn=conn,
                        structure_id=item["structure_id"],
                        text_engine=text_engine,
                        text_engine_version=item["engine_version"],
                        text=item["text"],
                        text_sha256=item["text_sha256"] or _sha256_text(item["text"]),
                        model_name=model_name,
                        model_version=resolved_model_version,
                        vector=vector,
                    )
                ok_count += 1
                log_entries.append(
                    {
                        "tool_name": "embed_text",
                        "input_payload": {
                            "structure_id": item["structure_id"],
                            "text_doc_id": item["text_doc_id"],
                            "text_view": item["text_view"],
                        },
                        "output_payload": {
                            "structure_id": item["structure_id"],
                            "text_view": item["text_view"],
                            "embed_engine": resolved_embed_engine,
                            "model_name": model_name,
                            "model_version": resolved_model_version,
                            "dim": len(vector),
                            "chunk_count": int(meta.get("chunk_count", 1)),
                            "max_chunk_tokens": int(meta.get("max_chunk_tokens", 0)),
                            "total_est_tokens": int(meta.get("total_est_tokens", 0)),
                        },
                        "started_at": started,
                        "ended_at": now_iso_utc(),
                        "status": "ok",
                    }
                )
            else:
                error_type = outcome.get("error_type") or "EMBEDDING_ERROR"
                error_message = outcome.get("error_message") or "embedding_failed"
                parsed_error: Optional[Dict[str, Any]] = None
                try:
                    maybe_error = json.loads(error_message)
                    if isinstance(maybe_error, dict):
                        parsed_error = maybe_error
                except json.JSONDecodeError:
                    parsed_error = None
                _upsert_text_embedding(
                    conn=conn,
                    text_doc_id=item["text_doc_id"],
                    embed_engine=resolved_embed_engine,
                    model=model_name,
                    model_version=resolved_model_version,
                    status=TEXT_STATUS_FAILED,
                    vector=None,
                    error_type=error_type,
                    error_message=error_message,
                )
                failed_count += 1
                log_entries.append(
                    {
                        "tool_name": "embed_text",
                        "input_payload": {
                            "structure_id": item["structure_id"],
                            "text_doc_id": item["text_doc_id"],
                            "text_view": item["text_view"],
                        },
                        "output_payload": {
                            "text_view": item["text_view"],
                            "error_type": error_type,
                            "error": parsed_error if parsed_error is not None else error_message,
                        },
                        "started_at": started,
                        "ended_at": now_iso_utc(),
                        "status": "error",
                        "error_text": error_message,
                    }
                )
            processed += 1

        conn.commit()
        _flush_log_entries(logger, log_entries)
        if processed % progress_every == 0 or processed == total:
            last_sid = chunk[-1]["structure_id"] if chunk else None
            elapsed = max(0.001, time.time() - started_ts)
            rate = processed / elapsed
            print(
                f"[embed-text] {processed}/{total} processed "
                f"(ok={ok_count}, failed={failed_count}, text_engine={text_engine}, text_view={resolved_text_view}, "
                f"embed_engine={resolved_embed_engine}, model={model_name}, rate={rate:.2f}/s, "
                f"last_structure_id={last_sid})"
            )
        if snapshot_path and snapshot_every > 0 and processed % snapshot_every == 0:
            _write_snapshot(
                snapshot_path,
                {
                    "ts": now_iso_utc(),
                    "command": "embed-text",
                    "db": db_path,
                    "text_engine": text_engine,
                    "text_view": resolved_text_view,
                    "embed_engine": resolved_embed_engine,
                    "model": model_name,
                    "model_version": resolved_model_version,
                    "shard_count": shard_count,
                    "shard_index": shard_index,
                    "processed": processed,
                    "ok": ok_count,
                    "error": failed_count,
                    "last_structure_id": last_structure_id,
                    "last_text_doc_id": last_text_doc_id,
                },
            )

    _flush_log_entries(logger, log_entries)
    conn.close()
    if snapshot_path and snapshot_every > 0:
        _write_snapshot(
            snapshot_path,
            {
                "ts": now_iso_utc(),
                "command": "embed-text",
                "db": db_path,
                "text_engine": text_engine,
                "text_view": resolved_text_view,
                "embed_engine": resolved_embed_engine,
                "model": model_name,
                "model_version": resolved_model_version,
                "shard_count": shard_count,
                "shard_index": shard_index,
                "processed": processed,
                "ok": ok_count,
                "error": failed_count,
                "last_structure_id": last_structure_id,
                "last_text_doc_id": last_text_doc_id,
            },
        )
    return {
        "text_engine": text_engine,
        "text_view": resolved_text_view,
        "embed_engine": resolved_embed_engine,
        "model": model_name,
        "model_version": resolved_model_version,
        "selected": total,
        "ok": ok_count,
        "failed": failed_count,
        "processed": processed,
        "run_id": logger.run_id,
    }


def embed_texts(
    *,
    db_path: Optional[str],
    engine: str = "baseline",
    text_view: Optional[str] = None,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
    structure_ids: Optional[List[str]] = None,
    run_name: Optional[str] = None,
    embed_engine: str = DEFAULT_EMBED_ENGINE,
    limit: Optional[int] = None,
    batch: int = 32,
    progress_every: int = 100,
    retry_failed: bool = False,
    force: bool = False,
    shard_count: int = 1,
    shard_index: int = 0,
    snapshot_path: Optional[str] = None,
    snapshot_every: int = 0,
) -> Dict[str, Any]:
    if structure_ids is None:
        structure_ids = _fetch_structure_ids(db_path)
    resolved_text_view = _resolve_text_view(engine, text_view)

    gen_result = generate_text_docs(
        db_path=db_path,
        engine=engine,
        text_view=resolved_text_view,
        structure_ids=structure_ids,
        limit=limit,
        batch=batch,
        progress_every=progress_every,
        retry_failed=retry_failed,
        force=force,
        shard_count=shard_count,
        shard_index=shard_index,
        snapshot_path=snapshot_path,
        snapshot_every=snapshot_every,
        run_name=run_name,
    )
    embed_result = embed_text_docs(
        db_path=db_path,
        text_engine=engine,
        text_view=resolved_text_view,
        embed_engine=embed_engine,
        model_name=model_name,
        model_version=model_version,
        structure_ids=structure_ids,
        limit=limit,
        batch=batch,
        progress_every=progress_every,
        retry_failed=retry_failed,
        force=force,
        shard_count=shard_count,
        shard_index=shard_index,
        snapshot_path=snapshot_path,
        snapshot_every=snapshot_every,
        run_name=run_name,
    )
    return {
        "processed": embed_result["processed"],
        "generated": gen_result,
        "embedded": embed_result,
    }
