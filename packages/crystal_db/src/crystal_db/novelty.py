import json
import time
from typing import Any, Dict, Optional, Tuple

from .audit_log import AuditLogger
from .db import connect, init_db
from .fingerprint import FINGERPRINT_METHOD, FINGERPRINT_VERSION, fingerprint_structure
from .utils import elements_from_csv, now_iso_utc, stable_hash

_FINGERPRINT_CACHE: Dict[Tuple[Optional[str], str, str], Dict[str, Any]] = {}


def _read_cif(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _run_tool(logger: AuditLogger, tool_name: str, fn, **kwargs) -> Any:
    started_at = now_iso_utc()
    status = "ok"
    error_text = None
    try:
        output = fn(**kwargs)
    except Exception as exc:
        status = "error"
        error_text = str(exc)
        output = {"error": "exception", "message": error_text}
    ended_at = now_iso_utc()
    logger.log_tool_call(tool_name, kwargs, output, started_at, ended_at, status, error_text)
    return output


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def clear_fingerprint_cache() -> None:
    _FINGERPRINT_CACHE.clear()


def _ensure_fingerprints(logger: AuditLogger, db_path: Optional[str]) -> None:
    conn = connect(db_path)
    init_db(conn)

    missing_rows = conn.execute(
        "SELECT s.structure_id FROM structures s "
        "LEFT JOIN structure_fingerprints f "
        "ON s.structure_id = f.structure_id AND f.fingerprint_method = ? AND f.fingerprint_version = ? "
        "WHERE f.structure_id IS NULL",
        (FINGERPRINT_METHOD, FINGERPRINT_VERSION),
    ).fetchall()
    conn.close()

    if not missing_rows:
        return

    for row in missing_rows:
        _run_tool(
            logger,
            "fingerprint_structure",
            fingerprint_structure,
            structure_id=row["structure_id"],
            db_path=db_path,
            store=True,
        )


def _load_fingerprint_index(db_path: Optional[str], force_reload: bool = False) -> Dict[str, Any]:
    key = (db_path, FINGERPRINT_METHOD, FINGERPRINT_VERSION)
    if not force_reload and key in _FINGERPRINT_CACHE:
        return _FINGERPRINT_CACHE[key]

    conn = connect(db_path)
    init_db(conn)
    rows = conn.execute(
        "SELECT f.structure_id, f.vector_json, f.feature_names_json, "
        "m.formula, m.elements_csv, m.space_group, m.band_gap_eV, "
        "s.nsites, s.volume, p.source, p.source_id, p.retrieved_at, p.allow_export "
        "FROM structure_fingerprints f "
        "JOIN metadata m ON m.structure_id = f.structure_id "
        "JOIN structures s ON s.structure_id = f.structure_id "
        "JOIN provenance p ON p.structure_id = f.structure_id "
        "WHERE f.fingerprint_method = ? AND f.fingerprint_version = ?",
        (FINGERPRINT_METHOD, FINGERPRINT_VERSION),
    ).fetchall()
    conn.close()

    feature_names = None
    entries = []

    for row in rows:
        row_feature_names = row["feature_names_json"]
        if feature_names is None:
            feature_names = row_feature_names
        if row_feature_names != feature_names:
            continue
        entries.append(
            {
                "structure_id": row["structure_id"],
                "vector": json.loads(row["vector_json"]),
                "provenance": {
                    "source": row["source"],
                    "source_id": row["source_id"],
                    "retrieved_at": row["retrieved_at"],
                    "allow_export": row["allow_export"],
                },
                "metadata": {
                    "formula": row["formula"],
                    "elements_csv": row["elements_csv"],
                    "space_group": row["space_group"],
                    "band_gap_eV": row["band_gap_eV"],
                    "nsites": row["nsites"],
                    "volume": row["volume"],
                },
            }
        )

    index = {
        "feature_names": json.loads(feature_names) if feature_names else None,
        "entries": entries,
    }
    _FINGERPRINT_CACHE[key] = index
    return index


def preload_fingerprint_index(db_path: Optional[str], force_reload: bool = False) -> Dict[str, Any]:
    return _load_fingerprint_index(db_path, force_reload=force_reload)


def _top_feature_deltas(feature_names, query_vec, neighbor_vec, top_n: int = 3):
    deltas = []
    for name, qv, nv in zip(feature_names, query_vec, neighbor_vec):
        delta = abs(qv - nv)
        deltas.append({"feature": name, "delta": delta, "query_value": qv, "neighbor_value": nv})
    deltas.sort(key=lambda d: (-d["delta"], d["feature"]))
    return deltas[:top_n]


def _find_exact_match(db_path: Optional[str], cif_text: str) -> Optional[Dict[str, Any]]:
    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT s.structure_id, m.formula, m.elements_csv, m.space_group, m.band_gap_eV, "
        "s.nsites, s.volume, p.source, p.source_id, p.retrieved_at, p.allow_export "
        "FROM structures s "
        "JOIN metadata m ON m.structure_id = s.structure_id "
        "JOIN provenance p ON p.structure_id = s.structure_id "
        "WHERE s.cif_text = ? LIMIT 1",
        (cif_text,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "structure_id": row["structure_id"],
        "distance": 0.0,
        "why": {"top_feature_deltas": []},
        "provenance": {
            "source": row["source"],
            "source_id": row["source_id"],
            "retrieved_at": row["retrieved_at"],
            "allow_export": row["allow_export"],
        },
        "metadata": {
            "formula": row["formula"],
            "space_group": row["space_group"],
            "band_gap_eV": row["band_gap_eV"],
            "nsites": row["nsites"],
            "volume": row["volume"],
            "elements": elements_from_csv(row["elements_csv"]),
        },
    }




def run_novelty(
    *,
    cif_path: Optional[str] = None,
    cif_text: Optional[str] = None,
    db_path: Optional[str] = None,
    threshold: float = 25.0,
    k: int = 5,
    run_name: Optional[str] = None,
    run_id: Optional[str] = None,
    force_reload: bool = False,
) -> Dict[str, Any]:
    if not cif_path and not cif_text:
        raise ValueError("cif_path or cif_text is required")

    t0 = _now_ms()
    parse_start = _now_ms()
    if cif_text is None:
        cif_text = _read_cif(cif_path or "")
    parse_cif_ms = _now_ms() - parse_start

    input_hash = stable_hash({"cif_text": cif_text})
    proposed_id = f"proposed-{input_hash[:8]}"

    logger = AuditLogger(
        db_path,
        run_name,
        {"mode": "novelty", "threshold": threshold, "k": k},
        defer_init=True,
        run_id=run_id,
        create_run=run_id is None,
    )
    logger.begin_batch()

    exact_match = _find_exact_match(db_path, cif_text)
    if not exact_match:
        _ensure_fingerprints(logger, db_path)

    fp_start = _now_ms()
    tool_started = now_iso_utc()
    try:
        fp = fingerprint_structure(cif_text=cif_text, db_path=db_path, store=False)
        status = "ok"
        error_text = None
    except Exception as exc:
        fp = {"error": "exception", "message": str(exc)}
        status = "error"
        error_text = str(exc)
    tool_ended = now_iso_utc()
    fingerprint_ms = _now_ms() - fp_start

    if "error" in fp:
        logger.log_tool_call(
            "fingerprint_structure",
            {"cif_text": cif_text, "db_path": db_path, "store": False},
            fp,
            tool_started,
            tool_ended,
            status,
            error_text,
        )
        logger.end_batch()
        return fp

    if exact_match:
        neighbors = [exact_match]
        load_db_fps_ms = 0.0
        knn_ms = 0.0
    else:
        load_start = _now_ms()
        index = _load_fingerprint_index(db_path, force_reload=force_reload)
        load_db_fps_ms = _now_ms() - load_start

        feature_names = fp["feature_names"]
        index_feature_names = index.get("feature_names")
        if index_feature_names and index_feature_names != feature_names:
            logger.end_batch()
            return {"error": "feature_names_mismatch"}
        query_vector = fp["vector"]

        knn_start = _now_ms()
        entries = index.get("entries", [])
        distances = []

        for entry in entries:
            neighbor_vector = entry["vector"]
            total = 0.0
            for qv, nv in zip(query_vector, neighbor_vector):
                delta = qv - nv
                total += delta * delta
            distances.append((total, entry["structure_id"], entry))

        distances.sort(key=lambda row: (row[0], row[1]))
        top = distances[: max(1, k)]

        neighbors = []
        for dist_sq, _, entry in top:
            neighbor_vector = entry["vector"]
            neighbors.append(
                {
                    "structure_id": entry["structure_id"],
                    "distance": dist_sq ** 0.5,
                    "why": {"top_feature_deltas": _top_feature_deltas(feature_names, query_vector, neighbor_vector)},
                    "provenance": entry["provenance"],
                    "metadata": {
                        "formula": entry["metadata"]["formula"],
                        "space_group": entry["metadata"]["space_group"],
                        "band_gap_eV": entry["metadata"]["band_gap_eV"],
                        "nsites": entry["metadata"]["nsites"],
                        "volume": entry["metadata"]["volume"],
                        "elements": elements_from_csv(entry["metadata"]["elements_csv"]),
                    },
                }
            )

        knn_ms = _now_ms() - knn_start

    best = neighbors[0] if neighbors else None
    best_distance = best.get("distance") if best else None
    best_match = best.get("structure_id") if best else None
    is_novel = True
    if best_distance is not None and best_distance <= threshold:
        is_novel = False

    logging_start = _now_ms()
    logger.add_proposed(proposed_id, cif_path or "<inline>", input_hash)
    timings = {
        "parse_cif_ms": parse_cif_ms,
        "fingerprint_ms": fingerprint_ms,
        "load_db_fps_ms": load_db_fps_ms,
        "knn_ms": knn_ms,
    }

    logger.log_tool_call(
        "fingerprint_structure",
        {"cif_text": cif_text, "db_path": db_path, "store": False},
        fp,
        tool_started,
        tool_ended,
        "ok",
        None,
    )

    logger.add_novelty_result(
        proposed_id=proposed_id,
        is_novel=is_novel,
        best_match_structure_id=best_match,
        best_distance=best_distance,
        threshold=threshold,
        neighbors=neighbors,
        timings=timings,
    )

    logger.add_explored_many([neighbor.get("structure_id") for neighbor in neighbors], "neighbor")

    evidence = {
        "proposed_id": proposed_id,
        "input_hash": input_hash,
        "best_match_structure_id": best_match,
        "best_distance": best_distance,
        "threshold": threshold,
        "neighbors": neighbors,
        "timings_ms": timings,
    }
    logger.save_evidence(evidence)
    logging_ms = _now_ms() - logging_start
    timings["logging_ms"] = logging_ms

    total_ms = _now_ms() - t0
    timings["total_ms"] = total_ms
    logger.update_novelty_timings(proposed_id, timings)
    logger.end_batch()

    return {
        "run_id": logger.run_id,
        "proposed_id": proposed_id,
        "is_novel": is_novel,
        "best_match_structure_id": best_match,
        "best_distance": best_distance,
        "threshold": threshold,
        "neighbors": neighbors,
        "timings_ms": timings,
    }
