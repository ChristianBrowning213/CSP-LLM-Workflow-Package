import json
import math
from typing import Any, Dict, List, Optional

from .db import connect, init_db
from .fingerprint import FINGERPRINT_METHOD, FINGERPRINT_VERSION, fingerprint_structure
from .utils import elements_from_csv


def _distance(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _top_feature_deltas(
    feature_names: List[str],
    query_vec: List[float],
    neighbor_vec: List[float],
    top_n: int = 3,
) -> List[Dict[str, Any]]:
    deltas = []
    for name, qv, nv in zip(feature_names, query_vec, neighbor_vec):
        delta = abs(qv - nv)
        deltas.append({"feature": name, "delta": delta, "query_value": qv, "neighbor_value": nv})

    deltas.sort(key=lambda d: (-d["delta"], d["feature"]))
    return deltas[:top_n]


def similar_structures(
    *,
    structure_id: Optional[str] = None,
    cif_text: Optional[str] = None,
    mode: str = "fingerprint",
    k: int = 10,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    if mode != "fingerprint":
        return {"error": "unsupported_mode", "mode": mode}

    if not structure_id and not cif_text:
        raise ValueError("structure_id or cif_text is required")

    query_fp = fingerprint_structure(
        structure_id=structure_id,
        cif_text=cif_text,
        db_path=db_path,
        store=bool(structure_id),
    )

    if "error" in query_fp:
        return query_fp

    query_vector = query_fp["vector"]
    feature_names = query_fp["feature_names"]

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

    neighbors: List[Dict[str, Any]] = []
    for row in rows:
        neighbor_id = row["structure_id"]
        if structure_id and neighbor_id == structure_id:
            continue

        neighbor_vector = json.loads(row["vector_json"])
        neighbor_feature_names = json.loads(row["feature_names_json"])
        if neighbor_feature_names != feature_names:
            continue

        distance = _distance(query_vector, neighbor_vector)
        neighbors.append(
            {
                "structure_id": neighbor_id,
                "distance": distance,
                "why": {"top_feature_deltas": _top_feature_deltas(feature_names, query_vector, neighbor_vector)},
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
                    "band_gap_eV": row["band_gap_eV"],
                    "nsites": row["nsites"],
                    "volume": row["volume"],
                },
            }
        )

    neighbors.sort(key=lambda n: (n["distance"], n["structure_id"]))
    if k < 1:
        k = 1

    return {
        "query": {"structure_id": structure_id, "mode": mode, "k": k},
        "method": {
            "fingerprint_method": FINGERPRINT_METHOD,
            "fingerprint_version": FINGERPRINT_VERSION,
        },
        "neighbors": neighbors[:k],
    }
