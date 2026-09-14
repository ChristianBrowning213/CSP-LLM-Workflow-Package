import json
from typing import Any, Dict, Optional

from .db import connect, init_db
from .utils import elements_from_csv, now_iso_utc, parse_cif_text, stable_hash

DESCRIPTOR_VERSION = "desc.v1"


def _build_descriptor_text(fields: Dict[str, Any]) -> str:
    parts = []
    if fields.get("formula"):
        parts.append(f"formula={fields['formula']}")
    if fields.get("space_group"):
        parts.append(f"space_group={fields['space_group']}")
    if fields.get("nsites") is not None:
        parts.append(f"nsites={fields['nsites']}")
    if fields.get("volume") is not None:
        parts.append(f"volume={fields['volume']}")
    if fields.get("band_gap_eV") is not None:
        parts.append(f"band_gap_eV={fields['band_gap_eV']}")

    if parts:
        return "Structure with " + ", ".join(parts) + "."
    return "Structure with no available metadata."


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


def describe_structure(
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

    key_features = {
        "formula": fields.get("formula"),
        "elements": sorted(fields.get("elements") or []),
        "space_group": fields.get("space_group"),
        "nsites": fields.get("nsites"),
        "volume": fields.get("volume"),
        "band_gap_eV": fields.get("band_gap_eV"),
    }

    input_hash = stable_hash({"descriptor_version": DESCRIPTOR_VERSION, **key_features})
    descriptor_text = _build_descriptor_text(fields)

    if structure_id and store:
        conn = connect(db_path)
        init_db(conn)
        existing = conn.execute(
            "SELECT descriptor_text, key_features_json, input_hash, generated_at "
            "FROM structure_descriptors WHERE structure_id = ? AND descriptor_version = ?",
            (structure_id, DESCRIPTOR_VERSION),
        ).fetchone()

        if existing and existing["input_hash"] == input_hash:
            conn.close()
            return {
                "structure_id": structure_id,
                "descriptor_version": DESCRIPTOR_VERSION,
                "descriptor_text": existing["descriptor_text"],
                "key_features": json.loads(existing["key_features_json"]),
                "input_hash": existing["input_hash"],
                "generated_at": existing["generated_at"],
            }

        generated_at = now_iso_utc()
        conn.execute(
            "INSERT OR REPLACE INTO structure_descriptors "
            "(structure_id, descriptor_version, descriptor_text, key_features_json, input_hash, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                structure_id,
                DESCRIPTOR_VERSION,
                descriptor_text,
                json.dumps(key_features, sort_keys=True),
                input_hash,
                generated_at,
            ),
        )
        conn.commit()
        conn.close()
        return {
            "structure_id": structure_id,
            "descriptor_version": DESCRIPTOR_VERSION,
            "descriptor_text": descriptor_text,
            "key_features": key_features,
            "input_hash": input_hash,
            "generated_at": generated_at,
        }

    return {
        "structure_id": structure_id,
        "descriptor_version": DESCRIPTOR_VERSION,
        "descriptor_text": descriptor_text,
        "key_features": key_features,
        "input_hash": input_hash,
        "generated_at": now_iso_utc(),
    }
