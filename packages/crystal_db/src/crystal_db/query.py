import json
from typing import Any, Dict, List, Optional

from .db import connect, init_db

ALLOWED_ORDER_BY = {
    "structure_id": "s.structure_id",
    "formula": "m.formula",
    "space_group": "m.space_group",
    "band_gap_eV": "m.band_gap_eV",
    "nsites": "s.nsites",
    "volume": "s.volume",
    "source_id": "p.source_id",
}


def _parse_filter_spec(filter_spec: Any) -> Dict[str, Any]:
    if filter_spec is None:
        return {}
    if isinstance(filter_spec, str):
        return json.loads(filter_spec)
    if isinstance(filter_spec, dict):
        return filter_spec
    raise ValueError("filter_spec must be dict or JSON string")


def _elements_like(element: str) -> str:
    return f"%,{element},%"


def _elements_from_csv(elements_csv: Optional[str]) -> List[str]:
    if not elements_csv:
        return []
    trimmed = elements_csv.strip(",")
    if not trimmed:
        return []
    return trimmed.split(",")


def query_structures(filter_spec: Any, db_path: Optional[str] = None) -> Dict[str, Any]:
    spec = _parse_filter_spec(filter_spec)

    where_clauses: List[str] = []
    params: List[Any] = []

    elements_include = spec.get("elements_include") or []
    for el in elements_include:
        where_clauses.append("m.elements_csv LIKE ?")
        params.append(_elements_like(el))

    elements_exclude = spec.get("elements_exclude") or []
    for el in elements_exclude:
        where_clauses.append("m.elements_csv NOT LIKE ?")
        params.append(_elements_like(el))

    if spec.get("formula"):
        where_clauses.append("m.formula = ?")
        params.append(spec["formula"])

    if spec.get("space_group"):
        where_clauses.append("m.space_group = ?")
        params.append(spec["space_group"])

    if spec.get("band_gap_eV_min") is not None:
        where_clauses.append("m.band_gap_eV >= ?")
        params.append(spec["band_gap_eV_min"])

    if spec.get("band_gap_eV_max") is not None:
        where_clauses.append("m.band_gap_eV <= ?")
        params.append(spec["band_gap_eV_max"])

    if spec.get("nsites_min") is not None:
        where_clauses.append("s.nsites >= ?")
        params.append(spec["nsites_min"])

    if spec.get("nsites_max") is not None:
        where_clauses.append("s.nsites <= ?")
        params.append(spec["nsites_max"])

    if spec.get("volume_min") is not None:
        where_clauses.append("s.volume >= ?")
        params.append(spec["volume_min"])

    if spec.get("volume_max") is not None:
        where_clauses.append("s.volume <= ?")
        params.append(spec["volume_max"])

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    order_by_key = spec.get("order_by", "structure_id")
    order_by = ALLOWED_ORDER_BY.get(order_by_key, ALLOWED_ORDER_BY["structure_id"])
    order_dir = "DESC" if str(spec.get("order", "asc")).lower() == "desc" else "ASC"

    limit = int(spec.get("limit", 50))
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    conn = connect(db_path)
    init_db(conn)

    count_sql = (
        "SELECT COUNT(*) as cnt "
        "FROM structures s "
        "JOIN metadata m ON m.structure_id = s.structure_id "
        "JOIN provenance p ON p.structure_id = s.structure_id"
        + where_sql
    )
    total_matches = conn.execute(count_sql, params).fetchone()["cnt"]

    select_sql = (
        "SELECT s.structure_id, s.reduced_formula, s.nsites, s.volume, s.license_restricted, "
        "m.formula, m.elements_csv, m.space_group, m.band_gap_eV, "
        "p.source, p.source_id, p.retrieved_at, p.license_notes, p.allow_export "
        "FROM structures s "
        "JOIN metadata m ON m.structure_id = s.structure_id "
        "JOIN provenance p ON p.structure_id = s.structure_id"
        + where_sql
        + f" ORDER BY {order_by} {order_dir}"
        + " LIMIT ?"
    )

    rows = conn.execute(select_sql, params + [limit]).fetchall()
    conn.close()

    results: List[Dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "structure_id": row["structure_id"],
                "source": row["source"],
                "source_id": row["source_id"],
                "retrieved_at": row["retrieved_at"],
                "formula": row["formula"],
                "elements": _elements_from_csv(row["elements_csv"]),
                "space_group": row["space_group"],
                "band_gap_eV": row["band_gap_eV"],
                "reduced_formula": row["reduced_formula"],
                "nsites": row["nsites"],
                "volume": row["volume"],
                "license_notes": row["license_notes"],
                "allow_export": row["allow_export"],
            }
        )

    return {"total_matches": total_matches, "results": results}


def get_structure(structure_id: str, db_path: Optional[str] = None, include_cif: bool = True) -> Dict[str, Any]:
    conn = connect(db_path)
    init_db(conn)

    row = conn.execute(
        "SELECT s.structure_id, s.cif_text, s.reduced_formula, s.nsites, s.volume, s.license_restricted, "
        "p.source, p.source_id, p.retrieved_at, p.license_notes, p.allow_cif_return, p.allow_export "
        "FROM structures s "
        "JOIN provenance p ON p.structure_id = s.structure_id "
        "WHERE s.structure_id = ?",
        (structure_id,),
    ).fetchone()
    conn.close()

    if row is None:
        return {"error": "not_found", "structure_id": structure_id}

    notes = (row["license_notes"] or "").lower()
    allow_cif_return = row["allow_cif_return"]
    restricted = bool(row["license_restricted"]) or (
        "restricted" in notes and "unrestricted" not in notes
    )
    if allow_cif_return is not None and int(allow_cif_return) == 0:
        restricted = True

    cif_text = None
    if include_cif and not restricted:
        cif_text = row["cif_text"]

    return {
        "structure_id": row["structure_id"],
        "source": row["source"],
        "source_id": row["source_id"],
        "retrieved_at": row["retrieved_at"],
        "license_notes": row["license_notes"],
        "allow_export": row["allow_export"],
        "restricted": restricted,
        "cif_text": cif_text,
        "canonical_summary": {
            "reduced_formula": row["reduced_formula"],
            "nsites": row["nsites"],
            "volume": row["volume"],
        },
    }
