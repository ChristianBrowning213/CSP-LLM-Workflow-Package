import json
from typing import Any, Dict, List, Optional

from .db import connect, init_db
from .fingerprint import fingerprint_structure
from .utils import elements_from_csv, now_iso_utc, parse_cif_text, parse_formula, stable_hash

CRYSTALCARD_VERSION = "v1"


def _crystal_system_from_symbol(symbol: Optional[str]) -> str:
    if not symbol:
        return "unknown"
    s = symbol.replace(" ", "").upper()
    if "M-3" in s or "M3" in s or "432" in s or s.endswith("23"):
        return "cubic"
    if "6" in s:
        return "hexagonal"
    if "4" in s:
        return "tetragonal"
    if "3" in s:
        return "trigonal"
    if "2" in s:
        return "monoclinic"
    if "1" in s:
        return "triclinic"
    return "unknown"


def _chemsys(elements: List[str]) -> str:
    if not elements:
        return "unknown"
    return "-".join(sorted(elements))


def _build_text_summary(summary: Dict[str, Any]) -> str:
    parts = []
    formula = summary.get("formula")
    if formula:
        parts.append(f"Formula {formula}")
    space_group = summary.get("space_group")
    crystal_system = summary.get("crystal_system")
    if space_group:
        if crystal_system and crystal_system != "unknown":
            parts.append(f"space group {space_group} ({crystal_system})")
        else:
            parts.append(f"space group {space_group}")
    elements = summary.get("elements") or []
    if elements:
        parts.append("elements " + ", ".join(elements))
    volume = summary.get("volume")
    if volume is not None:
        parts.append(f"volume {volume:.3f}")
    band_gap = summary.get("band_gap_eV")
    if band_gap is not None:
        parts.append(f"band gap {band_gap} eV")
    return "; ".join(parts)


def _build_motifs(summary: Dict[str, Any]) -> List[str]:
    motifs: List[str] = []
    elements = summary.get("elements") or []
    if elements:
        motifs.append(f"{_chemsys(elements)} system")
    crystal_system = summary.get("crystal_system")
    if crystal_system and crystal_system != "unknown":
        motifs.append(f"{crystal_system} lattice")
    space_group = summary.get("space_group")
    if space_group:
        motifs.append(f"space group {space_group}")
    return motifs


def _fingerprint_summary(fp: Dict[str, Any]) -> Dict[str, Any]:
    vector = fp.get("vector") or []
    feature_names = fp.get("feature_names") or []
    vector_hash = stable_hash({"vector": vector})
    feature_hash = stable_hash({"feature_names": feature_names})
    nonzero = sum(1 for value in vector if value)
    return {
        "fingerprint_method": fp.get("fingerprint_method"),
        "vector_len": len(vector),
        "nonzero_features": nonzero,
        "vector_hash": vector_hash,
        "feature_names_hash": feature_hash,
    }


def _input_hash(payload: Dict[str, Any]) -> str:
    return stable_hash(payload)


def build_crystalcard(
    *,
    structure_id: Optional[str] = None,
    cif_text: Optional[str] = None,
    db_path: Optional[str] = None,
    engine: str = "baseline",
    store: bool = True,
) -> Dict[str, Any]:
    if not structure_id and not cif_text:
        raise ValueError("structure_id or cif_text is required")

    if engine != "baseline":
        return {"error": "engine_unavailable", "engine": engine}

    summary: Dict[str, Any] = {}
    provenance: Optional[Dict[str, Any]] = None
    allow_derivatives = True

    if structure_id:
        conn = connect(db_path)
        init_db(conn)
        row = conn.execute(
            "SELECT s.structure_id, s.nsites, s.volume, m.formula, m.elements_csv, m.space_group, m.band_gap_eV, "
            "p.source, p.source_id, p.retrieved_at, p.allow_export, p.allow_derivatives "
            "FROM structures s "
            "JOIN metadata m ON m.structure_id = s.structure_id "
            "JOIN provenance p ON p.structure_id = s.structure_id "
            "WHERE s.structure_id = ?",
            (structure_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": "not_found", "structure_id": structure_id}

        allow_derivatives = row["allow_derivatives"] is None or int(row["allow_derivatives"]) != 0
        if not allow_derivatives:
            return {"error": "derivatives_restricted", "structure_id": structure_id}

        summary = {
            "formula": row["formula"],
            "elements": elements_from_csv(row["elements_csv"]),
            "space_group": row["space_group"],
            "crystal_system": _crystal_system_from_symbol(row["space_group"]),
            "nsites": row["nsites"],
            "volume": row["volume"],
            "band_gap_eV": row["band_gap_eV"],
            "chemsys": _chemsys(elements_from_csv(row["elements_csv"])),
        }
        provenance = {
            "source": row["source"],
            "source_id": row["source_id"],
            "retrieved_at": row["retrieved_at"],
            "allow_export": row["allow_export"],
            "allow_derivatives": row["allow_derivatives"],
        }
    else:
        parsed = parse_cif_text(cif_text or "")
        formula = parsed.get("formula")
        elements = sorted(parse_formula(formula).keys())
        summary = {
            "formula": formula,
            "elements": elements,
            "space_group": parsed.get("space_group"),
            "crystal_system": _crystal_system_from_symbol(parsed.get("space_group")),
            "nsites": None,
            "volume": parsed.get("volume"),
            "band_gap_eV": None,
            "chemsys": _chemsys(elements),
        }

    fp = fingerprint_structure(structure_id=structure_id, cif_text=cif_text, db_path=db_path, store=bool(structure_id))
    if "error" in fp:
        return fp

    fingerprint = _fingerprint_summary(fp)
    motifs = _build_motifs(summary)
    text_summary = _build_text_summary(summary)

    input_hash = _input_hash(
        {
            "engine": engine,
            "version": CRYSTALCARD_VERSION,
            "summary": summary,
            "fingerprint_input_hash": fp.get("input_hash"),
        }
    )

    card_core = {
        "schema_version": CRYSTALCARD_VERSION,
        "engine": engine,
        "structure_id": structure_id,
        "summary": summary,
        "fingerprint": fingerprint,
        "motifs": motifs,
        "text_summary": text_summary,
        "provenance": provenance,
        "input_hash": input_hash,
    }
    card_hash = stable_hash(card_core)

    card = dict(card_core)
    card["card_hash"] = card_hash
    card["generated_at"] = now_iso_utc()

    if structure_id and store and allow_derivatives:
        conn = connect(db_path)
        init_db(conn)
        existing = conn.execute(
            "SELECT card_json, input_hash FROM structure_crystalcards "
            "WHERE structure_id = ? AND engine = ? AND version = ?",
            (structure_id, engine, CRYSTALCARD_VERSION),
        ).fetchone()
        if existing and existing["input_hash"] == input_hash:
            conn.close()
            return json.loads(existing["card_json"])

        conn.execute(
            "INSERT OR REPLACE INTO structure_crystalcards "
            "(structure_id, engine, version, card_json, input_hash, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                structure_id,
                engine,
                CRYSTALCARD_VERSION,
                json.dumps(card, sort_keys=True, separators=(",", ":")),
                input_hash,
                card["generated_at"],
            ),
        )
        conn.commit()
        conn.close()

    return card
