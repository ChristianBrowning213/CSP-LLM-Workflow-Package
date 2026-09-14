import json
from typing import Any, Dict, List, Optional, Tuple

from .db import connect, init_db
from .embeddings import (
    DEFAULT_EMBED_ENGINE,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    embed_text,
    resolve_embed_engine,
    resolve_model_version,
)
from .fingerprint import (
    FINGERPRINT_METHOD,
    FINGERPRINT_VERSION,
    fingerprint_structure,
)
from .runlog import RunLogger
from .textgen import generate_text
from .utils import now_iso_utc


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
    else:
        decoded = raw_value
    if not isinstance(decoded, list):
        return None
    try:
        return [float(item) for item in decoded]
    except (TypeError, ValueError):
        return None


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


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _load_best_text_embedding_for_id(
    *,
    conn,
    structure_id: str,
    embed_engine: str,
    model_name: str,
    model_version: str,
) -> Optional[List[float]]:
    row = conn.execute(
        "SELECT te.vector FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        "WHERE td.structure_id = ? AND te.status = 'OK' "
        "AND te.embed_engine = ? AND te.model = ? AND te.model_version = ? "
        "ORDER BY te.id DESC LIMIT 1",
        (structure_id, embed_engine, model_name, model_version),
    ).fetchone()
    if row is None:
        return None
    return _decode_vector(row["vector"])


def _text_comparators_for_vector(
    *,
    conn,
    query_vector: List[float],
    embed_engine: str,
    model_name: str,
    model_version: str,
    exclude_structure_id: Optional[str],
    k: int,
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT td.structure_id, te.vector "
        "FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        "WHERE te.status = 'OK' AND te.embed_engine = ? AND te.model = ? AND te.model_version = ? "
        "ORDER BY td.structure_id ASC, te.id DESC",
        (embed_engine, model_name, model_version),
    ).fetchall()
    best: Dict[str, float] = {}
    for row in rows:
        sid = row["structure_id"]
        if exclude_structure_id and sid == exclude_structure_id:
            continue
        vec = _decode_vector(row["vector"])
        if vec is None or len(vec) != len(query_vector):
            continue
        score = _cosine_similarity(query_vector, vec)
        if sid not in best or score > best[sid]:
            best[sid] = score
    ordered = sorted(best.items(), key=lambda item: (-item[1], item[0]))[: max(1, k)]
    return [{"structure_id": sid, "score": score, "mode": "text"} for sid, score in ordered]


def _load_fingerprint_for_id(conn, structure_id: str) -> Optional[List[float]]:
    row = conn.execute(
        "SELECT vector_json FROM structure_fingerprints "
        "WHERE structure_id = ? AND fingerprint_method = ? AND fingerprint_version = ?",
        (structure_id, FINGERPRINT_METHOD, FINGERPRINT_VERSION),
    ).fetchone()
    if row is None:
        return None
    return _decode_vector(row["vector_json"])


def _fingerprint_comparators_for_vector(
    *,
    conn,
    query_vector: List[float],
    exclude_structure_id: Optional[str],
    k: int,
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT structure_id, vector_json FROM structure_fingerprints "
        "WHERE fingerprint_method = ? AND fingerprint_version = ?",
        (FINGERPRINT_METHOD, FINGERPRINT_VERSION),
    ).fetchall()
    result = []
    for row in rows:
        sid = row["structure_id"]
        if exclude_structure_id and sid == exclude_structure_id:
            continue
        vec = _decode_vector(row["vector_json"])
        if vec is None or len(vec) != len(query_vector):
            continue
        score = _cosine_similarity(query_vector, vec)
        result.append({"structure_id": sid, "score": score, "mode": "fingerprint"})
    result.sort(key=lambda item: (-item["score"], item["structure_id"]))
    return result[: max(1, k)]


def run_novelty_check(
    *,
    db_path: Optional[str],
    structure_id: Optional[str] = None,
    cif_path: Optional[str] = None,
    k: int = 5,
    embed_engine: str = DEFAULT_EMBED_ENGINE,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
    text_engine: str = "robocrys",
    text_sim_threshold: float = 0.80,
    fp_sim_threshold: float = 0.95,
    force: bool = False,
    run_name: Optional[str] = None,
) -> Dict[str, Any]:
    args = {
        "structure_id": structure_id,
        "cif_path": cif_path,
        "k": k,
        "engine": embed_engine,
        "model": model_name,
        "model_version": model_version,
        "text_engine": text_engine,
        "text_sim_threshold": text_sim_threshold,
        "fp_sim_threshold": fp_sim_threshold,
        "force": force,
        "run_name": run_name,
    }
    logger = RunLogger(db_path)
    try:
        run_id = logger.start_run("novelty-check", args)
    except Exception as exc:  # pylint: disable=broad-except
        return {
            "candidate": {},
            "comparators": [],
            "novelty": None,
            "run_id": None,
            "errors": [{"code": "run_start_failed", "message": str(exc)}],
        }
    errors: List[Dict[str, Any]] = []

    if (structure_id is None) == (cif_path is None):
        err = {"code": "invalid_candidate", "message": "Provide exactly one of --id or --cif."}
        logger.finalize_run(status="error", error_text=err["message"])
        return {"candidate": {}, "comparators": [], "novelty": None, "run_id": run_id, "errors": [err]}

    resolved_model_name = model_name or DEFAULT_MODEL_NAME
    resolved_embed_engine = resolve_embed_engine(embed_engine, resolved_model_name)
    resolved_model_version = resolve_model_version(
        resolved_model_name,
        model_version,
        embed_engine=resolved_embed_engine,
    )

    conn = connect(db_path)
    init_db(conn)
    candidate: Dict[str, Any]
    candidate_text_vector: Optional[List[float]] = None
    candidate_fp_vector: Optional[List[float]] = None
    candidate_cif_text: Optional[str] = None

    if structure_id:
        candidate = {"structure_id": structure_id, "source": "structure_id"}
        started = now_iso_utc()
        candidate_text_vector = _load_best_text_embedding_for_id(
            conn=conn,
            structure_id=structure_id,
            embed_engine=resolved_embed_engine,
            model_name=resolved_model_name,
            model_version=resolved_model_version,
        )
        logger.log_step(
            "load_text_embedding",
            {
                "structure_id": structure_id,
                "embed_engine": resolved_embed_engine,
                "model_name": resolved_model_name,
                "model_version": resolved_model_version,
            },
            {"found": candidate_text_vector is not None},
            "ok",
            started_at=started,
            ended_at=now_iso_utc(),
        )
        started = now_iso_utc()
        candidate_fp_vector = _load_fingerprint_for_id(conn, structure_id)
        logger.log_step(
            "load_fingerprint",
            {"structure_id": structure_id},
            {"found": candidate_fp_vector is not None},
            "ok",
            started_at=started,
            ended_at=now_iso_utc(),
        )
        if candidate_fp_vector is None and force:
            started = now_iso_utc()
            fp = fingerprint_structure(structure_id=structure_id, db_path=db_path, store=True)
            logger.log_step(
                "fingerprint_structure",
                {"structure_id": structure_id, "store": True},
                fp,
                "error" if "error" in fp else "ok",
                error_text=fp.get("error") if isinstance(fp, dict) else None,
                started_at=started,
                ended_at=now_iso_utc(),
            )
            if isinstance(fp, dict) and "vector" in fp:
                candidate_fp_vector = _decode_vector(fp["vector"])
    else:
        candidate_cif_text = _read_file(cif_path or "")
        candidate = {"cif_path": cif_path, "source": "cif"}
        proposal_id = logger.add_proposal(source="user", cif_path=cif_path, status="draft")
        candidate["proposal_id"] = proposal_id

        started = now_iso_utc()
        text_info = generate_text(cif_text=candidate_cif_text, engine=text_engine, db_path=db_path)
        logger.log_step(
            "generate_text",
            {"cif_path": cif_path, "text_engine": text_engine},
            text_info,
            "error" if "error" in text_info else "ok",
            error_text=text_info.get("error") if isinstance(text_info, dict) else None,
            started_at=started,
            ended_at=now_iso_utc(),
        )
        if "error" not in text_info:
            started = now_iso_utc()
            try:
                candidate_text_vector = embed_text(
                    text_info.get("text", ""),
                    model_name=resolved_model_name,
                    model_version=resolved_model_version,
                    embed_engine=resolved_embed_engine,
                )
                embed_output: Dict[str, Any] = {"ok": True, "dim": len(candidate_text_vector)}
                logger.log_step(
                    "embed_text",
                    {
                        "embed_engine": resolved_embed_engine,
                        "model_name": resolved_model_name,
                        "model_version": resolved_model_version,
                    },
                    embed_output,
                    "ok",
                    started_at=started,
                    ended_at=now_iso_utc(),
                )
            except Exception as exc:  # pylint: disable=broad-except
                err = {"code": "query_embedding_failed", "message": str(exc)}
                errors.append(err)
                logger.log_step(
                    "embed_text",
                    {
                        "embed_engine": resolved_embed_engine,
                        "model_name": resolved_model_name,
                        "model_version": resolved_model_version,
                    },
                    err,
                    "error",
                    error_text=str(exc),
                    started_at=started,
                    ended_at=now_iso_utc(),
                )

        started = now_iso_utc()
        fp = fingerprint_structure(cif_text=candidate_cif_text, db_path=db_path, store=False)
        logger.log_step(
            "fingerprint_structure",
            {"cif_path": cif_path, "store": False},
            fp,
            "error" if "error" in fp else "ok",
            error_text=fp.get("error") if isinstance(fp, dict) else None,
            started_at=started,
            ended_at=now_iso_utc(),
        )
        if isinstance(fp, dict) and "vector" in fp:
            candidate_fp_vector = _decode_vector(fp["vector"])

    text_comparators: List[Dict[str, Any]] = []
    fp_comparators: List[Dict[str, Any]] = []
    if candidate_text_vector is not None:
        started = now_iso_utc()
        text_comparators = _text_comparators_for_vector(
            conn=conn,
            query_vector=candidate_text_vector,
            embed_engine=resolved_embed_engine,
            model_name=resolved_model_name,
            model_version=resolved_model_version,
            exclude_structure_id=structure_id,
            k=k,
        )
        logger.log_step(
            "search_text_space",
            {"k": k},
            {"comparators": text_comparators},
            "ok",
            started_at=started,
            ended_at=now_iso_utc(),
        )
    else:
        errors.append({"code": "text_embedding_missing", "message": "Candidate text embedding is unavailable."})

    if candidate_fp_vector is not None:
        started = now_iso_utc()
        fp_comparators = _fingerprint_comparators_for_vector(
            conn=conn,
            query_vector=candidate_fp_vector,
            exclude_structure_id=structure_id,
            k=k,
        )
        logger.log_step(
            "search_fingerprint_space",
            {"k": k},
            {"comparators": fp_comparators},
            "ok",
            started_at=started,
            ended_at=now_iso_utc(),
        )
    else:
        errors.append({"code": "fingerprint_missing", "message": "Candidate fingerprint is unavailable."})

    conn.close()

    max_text_similarity = max((item["score"] for item in text_comparators), default=0.0)
    max_fp_similarity = max((item["score"] for item in fp_comparators), default=0.0)
    reason_codes: List[str] = []
    if max_text_similarity >= text_sim_threshold:
        reason_codes.append("TEXT_TOO_SIMILAR")
    if max_fp_similarity >= fp_sim_threshold:
        reason_codes.append("FP_TOO_SIMILAR")
    if not text_comparators:
        reason_codes.append("NO_TEXT_COMPARATORS")
    if not fp_comparators:
        reason_codes.append("NO_FP_COMPARATORS")
    if not reason_codes:
        reason_codes.append("NOVEL")

    is_novel = (max_text_similarity < text_sim_threshold) and (max_fp_similarity < fp_sim_threshold)
    novelty = {
        "is_novel": is_novel,
        "thresholds": {
            "text_sim_threshold": text_sim_threshold,
            "fp_sim_threshold": fp_sim_threshold,
        },
        "max_text_similarity": max_text_similarity,
        "max_fp_similarity": max_fp_similarity,
        "reason_codes": reason_codes,
    }

    comparators = sorted(
        text_comparators + fp_comparators,
        key=lambda item: (-item["score"], item["structure_id"], item["mode"]),
    )[: max(1, k)]
    for item in comparators:
        logger.add_explored(item["structure_id"], "retrieved_neighbor")
    logger.add_evidence(
        "novelty",
        {
            "candidate": candidate,
            "comparators": comparators,
            "novelty": novelty,
            "errors": errors,
        },
    )

    if errors and (candidate_text_vector is None or candidate_fp_vector is None):
        logger.finalize_run(status="error", error_text=errors[0]["message"])
    else:
        logger.finalize_run(status="ok")

    return {
        "candidate": candidate,
        "comparators": comparators,
        "novelty": novelty,
        "run_id": run_id,
        "errors": errors or None,
    }
