import json
from typing import Any, Dict, List, Optional, Tuple

from .db import connect, init_db
from .utils import elements_from_csv, now_iso_utc, parse_cif_text, parse_formula, stable_hash

FINGERPRINT_METHOD = "fp.simple.v1"
FINGERPRINT_VERSION = "v1"

ELEMENT_ORDER = [
    "H", "C", "N", "O", "F", "Li", "Na", "K", "Mg", "Ca",
    "Al", "Si", "P", "S", "Cl", "Fe", "Co", "Ni", "Cu", "Zn",
]


def _feature_names() -> List[str]:
    names = [f"count_{el}" for el in ELEMENT_ORDER]
    names.append("count_other")
    names.extend(["nsites", "volume", "band_gap_eV"])
    return names


def _fetch_fields_from_db(structure_id: str, db_path: Optional[str]) -> Dict[str, Any]:
    conn = connect(db_path)
    init_db(conn)

    row = conn.execute(
        "SELECT s.structure_id, s.nsites, s.volume, m.formula, m.elements_csv, m.space_group, m.band_gap_eV "
        "FROM structures s "
        "JOIN metadata m ON m.structure_id = s.structure_id "
        "WHERE s.structure_id = ?",
        (structure_id,),
    ).fetchone()
    conn.close()

    if row is None:
        return {}

    return {
        "structure_id": row["structure_id"],
        "formula": row["formula"],
        "elements": elements_from_csv(row["elements_csv"]),
        "space_group": row["space_group"],
        "nsites": row["nsites"],
        "volume": row["volume"],
        "band_gap_eV": row["band_gap_eV"],
    }


def _build_vector(fields: Dict[str, Any]) -> Tuple[List[float], List[str], Dict[str, Any]]:
    feature_names = _feature_names()
    formula = fields.get("formula")
    counts = parse_formula(formula)

    vector: List[float] = []
    other_count = 0
    for element in ELEMENT_ORDER:
        count = counts.get(element, 0)
        vector.append(float(count))

    for element, count in counts.items():
        if element not in ELEMENT_ORDER:
            other_count += count

    vector.append(float(other_count))
    vector.append(float(fields.get("nsites") or 0))
    vector.append(float(fields.get("volume") or 0.0))
    vector.append(float(fields.get("band_gap_eV") or 0.0))

    key_features = {
        "formula": formula,
        "counts": counts,
        "nsites": fields.get("nsites"),
        "volume": fields.get("volume"),
        "band_gap_eV": fields.get("band_gap_eV"),
    }

    return vector, feature_names, key_features


def fingerprint_structure(
    *,
    structure_id: Optional[str] = None,
    cif_text: Optional[str] = None,
    db_path: Optional[str] = None,
    store: bool = True,
) -> Dict[str, Any]:
    if not structure_id and not cif_text:
        raise ValueError("structure_id or cif_text is required")

    fields: Dict[str, Any]
    if structure_id:
        fields = _fetch_fields_from_db(structure_id, db_path)
        if not fields:
            return {"error": "not_found", "structure_id": structure_id}
    else:
        cif_fields = parse_cif_text(cif_text or "")
        fields = {
            "structure_id": None,
            "formula": cif_fields.get("formula"),
            "elements": [],
            "space_group": cif_fields.get("space_group"),
            "nsites": None,
            "volume": cif_fields.get("volume"),
            "band_gap_eV": None,
        }

    vector, feature_names, key_features = _build_vector(fields)
    input_hash = stable_hash(
        {
            "fingerprint_method": FINGERPRINT_METHOD,
            "fingerprint_version": FINGERPRINT_VERSION,
            **key_features,
        }
    )

    if structure_id and store:
        conn = connect(db_path)
        init_db(conn)
        existing = conn.execute(
            "SELECT vector_json, feature_names_json, input_hash, generated_at "
            "FROM structure_fingerprints "
            "WHERE structure_id = ? AND fingerprint_method = ? AND fingerprint_version = ?",
            (structure_id, FINGERPRINT_METHOD, FINGERPRINT_VERSION),
        ).fetchone()

        if existing and existing["input_hash"] == input_hash:
            conn.close()
            return {
                "structure_id": structure_id,
                "fingerprint_method": FINGERPRINT_METHOD,
                "vector": json.loads(existing["vector_json"]),
                "feature_names": json.loads(existing["feature_names_json"]),
                "input_hash": existing["input_hash"],
                "generated_at": existing["generated_at"],
            }

        generated_at = now_iso_utc()
        conn.execute(
            "INSERT OR REPLACE INTO structure_fingerprints "
            "(structure_id, fingerprint_method, fingerprint_version, vector_json, feature_names_json, input_hash, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                structure_id,
                FINGERPRINT_METHOD,
                FINGERPRINT_VERSION,
                json.dumps(vector),
                json.dumps(feature_names),
                input_hash,
                generated_at,
            ),
        )
        conn.commit()
        conn.close()

        return {
            "structure_id": structure_id,
            "fingerprint_method": FINGERPRINT_METHOD,
            "vector": vector,
            "feature_names": feature_names,
            "input_hash": input_hash,
            "generated_at": generated_at,
        }

    return {
        "structure_id": structure_id,
        "fingerprint_method": FINGERPRINT_METHOD,
        "vector": vector,
        "feature_names": feature_names,
        "input_hash": input_hash,
        "generated_at": now_iso_utc(),
    }
