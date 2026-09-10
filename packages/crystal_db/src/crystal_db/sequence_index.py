import json
from typing import Any, Dict, List, Optional

from .audit_log import AuditLogger
from .db import connect, init_db
from .embeddings import DEFAULT_DIM, DEFAULT_MODEL_NAME, DEFAULT_MODEL_VERSION, embed_texts as embed_texts_batch, resolve_model_version
from .utils import now_iso_utc, stable_hash

SEQ_VERSION = "v1"


def _allow_derivatives(structure_id: str, db_path: Optional[str]) -> bool:
    conn = connect(db_path)
    init_db(conn)
    row = conn.execute("SELECT allow_derivatives FROM provenance WHERE structure_id = ?", (structure_id,)).fetchone()
    conn.close()
    if row is None:
        return False
    value = row["allow_derivatives"]
    return value is None or int(value) != 0


def _fetch_structure_ids(db_path: Optional[str]) -> List[str]:
    conn = connect(db_path)
    init_db(conn)
    rows = conn.execute("SELECT structure_id FROM structures ORDER BY structure_id").fetchall()
    conn.close()
    return [row["structure_id"] for row in rows]


def canonicalize_cif(cif_text: str) -> str:
    lines = []
    for raw in cif_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        parts = line.split()
        line = " ".join(parts)
        if line:
            lines.append(line)
    lines.sort()
    return "\n".join(lines) + "\n"


def encode_sequences(
    *,
    db_path: Optional[str],
    format: str = "cif_canon",
    structure_ids: Optional[List[str]] = None,
    run_name: Optional[str] = None,
) -> Dict[str, Any]:
    if format != "cif_canon":
        return {"error": "format_unavailable", "format": format}

    if structure_ids is None:
        structure_ids = _fetch_structure_ids(db_path)

    logger = AuditLogger(db_path, run_name, {"mode": "encode-seq", "format": format})

    conn = connect(db_path)
    init_db(conn)

    results = []
    log_entries = []
    for sid in structure_ids:
        if not _allow_derivatives(sid, db_path):
            results.append({"structure_id": sid, "error": "derivatives_restricted"})
            log_entries.append({"tool": "encode_seq", "structure_id": sid, "output": {"error": "derivatives_restricted"}, "status": "error"})
            continue

        row = conn.execute("SELECT cif_text FROM structures WHERE structure_id = ?", (sid,)).fetchone()
        if row is None or row["cif_text"] is None:
            results.append({"structure_id": sid, "error": "cif_missing"})
            log_entries.append({"tool": "encode_seq", "structure_id": sid, "output": {"error": "cif_missing"}, "status": "error"})
            continue

        seq_text = canonicalize_cif(row["cif_text"])
        input_hash = stable_hash({"format": format, "seq_text": seq_text})

        conn.execute(
            "INSERT OR REPLACE INTO structure_sequences (structure_id, format, seq_text, input_hash, generated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, format, seq_text, input_hash, now_iso_utc()),
        )

        output = {"structure_id": sid, "format": format}
        results.append(output)
        log_entries.append({"tool": "encode_seq", "structure_id": sid, "output": output, "status": "ok"})

    conn.commit()
    conn.close()

    for entry in log_entries:
        logger.log_tool_call(entry["tool"], {"structure_id": entry["structure_id"]}, entry["output"], now_iso_utc(), now_iso_utc(), entry["status"], None)

    return {"processed": len(structure_ids), "results": results, "run_id": logger.run_id}


def embed_sequences(
    *,
    db_path: Optional[str],
    format: str = "cif_canon",
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
    structure_ids: Optional[List[str]] = None,
    run_name: Optional[str] = None,
) -> Dict[str, Any]:
    if format != "cif_canon":
        return {"error": "format_unavailable", "format": format}

    if model_name is None:
        model_name = DEFAULT_MODEL_NAME
    model_version = resolve_model_version(model_name, model_version)

    if structure_ids is None:
        structure_ids = _fetch_structure_ids(db_path)

    logger = AuditLogger(db_path, run_name, {"mode": "embed-seq", "format": format, "model": model_name})

    conn = connect(db_path)
    init_db(conn)

    results = []
    log_entries = []
    pending = []
    for sid in structure_ids:
        if not _allow_derivatives(sid, db_path):
            results.append({"structure_id": sid, "error": "derivatives_restricted"})
            log_entries.append({"tool": "embed_seq", "structure_id": sid, "output": {"error": "derivatives_restricted"}, "status": "error"})
            continue

        row = conn.execute(
            "SELECT seq_text, input_hash FROM structure_sequences WHERE structure_id = ? AND format = ?",
            (sid, format),
        ).fetchone()
        if row is None:
            results.append({"structure_id": sid, "error": "sequence_missing"})
            log_entries.append({"tool": "embed_seq", "structure_id": sid, "output": {"error": "sequence_missing"}, "status": "error"})
            continue

        pending.append(
            {
                "structure_id": sid,
                "seq_text": row["seq_text"],
                "seq_hash": row["input_hash"],
            }
        )

    if pending:
        vectors = embed_texts_batch(
            [item["seq_text"] for item in pending],
            model_name=model_name,
            model_version=model_version,
            dim=DEFAULT_DIM,
        )
        if len(vectors) != len(pending):
            raise RuntimeError("Embedding count mismatch for sequence inputs")

        for item, vector in zip(pending, vectors):
            embed_hash = stable_hash({"seq_hash": item["seq_hash"], "model": model_name, "version": model_version})

            conn.execute(
                "INSERT OR REPLACE INTO structure_embeddings "
                "(structure_id, modality, model_name, model_version, vector_json, dim, input_hash, generated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["structure_id"],
                    "seq",
                    model_name,
                    model_version,
                    json.dumps(vector),
                    len(vector),
                    embed_hash,
                    now_iso_utc(),
                ),
            )

            output = {
                "structure_id": item["structure_id"],
                "format": format,
                "model_name": model_name,
                "model_version": model_version,
            }
            results.append(output)
            log_entries.append({"tool": "embed_seq", "structure_id": item["structure_id"], "output": output, "status": "ok"})

    conn.commit()
    conn.close()

    for entry in log_entries:
        logger.log_tool_call(entry["tool"], {"structure_id": entry["structure_id"]}, entry["output"], now_iso_utc(), now_iso_utc(), entry["status"], None)

    return {"processed": len(structure_ids), "results": results, "run_id": logger.run_id}
