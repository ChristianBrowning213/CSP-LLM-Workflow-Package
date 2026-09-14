from typing import Any, Dict, Optional

import hashlib
import json

from monty.json import MontyEncoder

from .crystalcard import build_crystalcard
from .db import connect, init_db
from .utils import now_iso_utc, stable_hash

TEXT_ENGINE_VERSION = "v1"
ROBOCRYS_ENGINE_VERSION = "robocrys.v1"
CAPTION_KEYWORDS = [
    "perovskite",
    "spinel",
    "laves",
    "layered",
    "van der waals",
    "2d",
    "octahedra",
    "tetrahedra",
    "corner-sharing",
    "edge-sharing",
]


def _allow_derivatives(structure_id: str, db_path: Optional[str]) -> bool:
    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT allow_derivatives FROM provenance WHERE structure_id = ?",
        (structure_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return False
    value = row["allow_derivatives"]
    return value is None or int(value) != 0


def _compact_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def _first_sentence(text: str) -> str:
    compact = _compact_whitespace(text)
    if not compact:
        return ""
    for token in (". ", "! ", "? "):
        idx = compact.find(token)
        if idx >= 0:
            return compact[: idx + 1]
    return compact


def _extract_caption_keywords(text: str) -> list:
    lowered = _compact_whitespace(text).lower()
    found = []
    for keyword in CAPTION_KEYWORDS:
        if keyword in lowered and keyword not in found:
            found.append(keyword)
    return found


def _extract_formula_hint(text: str) -> Optional[str]:
    compact = _compact_whitespace(text)
    if not compact:
        return None
    token = compact.split(" ", 1)[0]
    if token and any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
        return token
    return None


def _build_caption_from_text(base_text: str) -> str:
    sentence = _first_sentence(base_text)
    keywords = _extract_caption_keywords(base_text)
    formula_hint = _extract_formula_hint(base_text)
    parts = []
    if sentence:
        parts.append(sentence)
    if keywords:
        keyword_text = ", ".join(keywords[:4])
        parts.append(f"Key descriptors: {keyword_text}.")
    if formula_hint:
        parts.append(f"Chemistry hint: {formula_hint}.")
    caption = " ".join(parts).strip()
    if not caption:
        caption = "Crystal structure summary unavailable."
    return caption


def _load_cached_robocrys_text(structure_id: str, db_path: Optional[str]) -> Optional[str]:
    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT text FROM text_docs "
        "WHERE structure_id = ? AND engine = 'robocrys' AND text_view = 'robocrys' AND status = 'OK' "
        "ORDER BY updated_at DESC, id DESC LIMIT 1",
        (structure_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return row["text"]


def generate_robocrys(
    *,
    structure_id: Optional[str] = None,
    cif_text: Optional[str] = None,
    db_path: Optional[str] = None,
    store: bool = True,
) -> Dict[str, Any]:
    """Generate prose and condensed Robocrys data in one deterministic pass."""
    if not structure_id and not cif_text:
        raise ValueError("structure_id or cif_text is required")
    try:
        from robocrys import StructureCondenser, StructureDescriber  # type: ignore
        from pymatgen.core import Structure  # type: ignore
    except Exception:
        return {"error": "engine_unavailable", "engine": "robocrys"}
    if cif_text is None and structure_id:
        conn = connect(db_path)
        init_db(conn)
        row = conn.execute(
            "SELECT cif_text FROM structures WHERE structure_id = ?", (structure_id,)
        ).fetchone()
        conn.close()
        if row is None or row["cif_text"] is None:
            return {"error": "cif_missing", "structure_id": structure_id}
        cif_text = row["cif_text"]
    if structure_id and not _allow_derivatives(structure_id, db_path):
        return {"error": "derivatives_restricted", "structure_id": structure_id}

    structure = Structure.from_str(cif_text or "", fmt="cif")
    condensed = StructureCondenser().condense_structure(structure)
    description = StructureDescriber().describe(condensed)
    condensed_json = json.dumps(
        condensed, cls=MontyEncoder, sort_keys=True, separators=(",", ":")
    )
    condensed_payload = json.loads(condensed_json)
    condensed_sha256 = hashlib.sha256(condensed_json.encode("utf-8")).hexdigest()
    description_sha256 = hashlib.sha256(description.encode("utf-8")).hexdigest()
    generated_at = now_iso_utc()

    if structure_id and store:
        conn = connect(db_path)
        init_db(conn)
        conn.execute(
            "INSERT INTO text_docs "
            "(structure_id, engine, text_view, engine_version, text, text_sha256, "
            "status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, 'robocrys', 'robocrys', ?, ?, ?, 'OK', NULL, NULL, ?, ?) "
            "ON CONFLICT(structure_id, engine, text_view) DO UPDATE SET "
            "engine_version = excluded.engine_version, text = excluded.text, "
            "text_sha256 = excluded.text_sha256, status = excluded.status, "
            "error_type = NULL, error_message = NULL, updated_at = excluded.updated_at",
            (
                structure_id,
                ROBOCRYS_ENGINE_VERSION,
                description,
                description_sha256,
                generated_at,
                generated_at,
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO robocrys_condensed "
            "(structure_id, engine_version, condensed_json, condensed_sha256, "
            "description_sha256, generated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                structure_id,
                ROBOCRYS_ENGINE_VERSION,
                condensed_json,
                condensed_sha256,
                description_sha256,
                generated_at,
            ),
        )
        conn.commit()
        conn.close()

    return {
        "engine": "robocrys",
        "version": ROBOCRYS_ENGINE_VERSION,
        "text": description,
        "condensed": condensed_payload,
        "condensed_sha256": condensed_sha256,
        "description_sha256": description_sha256,
        "input_hash": stable_hash(
            {
                "engine": "robocrys",
                "version": ROBOCRYS_ENGINE_VERSION,
                "description_sha256": description_sha256,
                "condensed_sha256": condensed_sha256,
            }
        ),
        "generated_at": generated_at,
    }


def generate_text(
    *,
    structure_id: Optional[str] = None,
    cif_text: Optional[str] = None,
    engine: str = "baseline",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    if not structure_id and not cif_text:
        raise ValueError("structure_id or cif_text is required")

    if engine == "caption":
        if structure_id and not _allow_derivatives(structure_id, db_path):
            return {"error": "derivatives_restricted", "structure_id": structure_id}
        base_text: Optional[str] = None
        if structure_id:
            base_text = _load_cached_robocrys_text(structure_id, db_path)
        if not base_text:
            # Caption fallback must not change merely because an optional
            # Robocrys installation happens to be importable. Use cached
            # Robocrys text when explicitly available; otherwise use the
            # deterministic baseline directly.
            base = generate_text(structure_id=structure_id, cif_text=cif_text, engine="baseline", db_path=db_path)
            if "error" in base:
                return base
            base_text = base.get("text", "")
        caption = _build_caption_from_text(base_text or "")
        input_hash = stable_hash({"engine": "caption", "version": TEXT_ENGINE_VERSION, "text": caption})
        return {
            "engine": "caption",
            "version": TEXT_ENGINE_VERSION,
            "text": caption,
            "input_hash": input_hash,
        }

    if engine == "robocrys":
        return generate_robocrys(
            structure_id=structure_id,
            cif_text=cif_text,
            db_path=db_path,
            store=bool(structure_id),
        )

    if structure_id and not _allow_derivatives(structure_id, db_path):
        return {"error": "derivatives_restricted", "structure_id": structure_id}

    card = build_crystalcard(structure_id=structure_id, cif_text=cif_text, db_path=db_path, engine="baseline", store=False)
    if "error" in card:
        return card

    motifs = card.get("motifs") or []
    text_summary = card.get("text_summary") or ""
    if motifs:
        text_summary = text_summary + ". Motifs: " + "; ".join(motifs)
    input_hash = stable_hash({"engine": "baseline", "version": TEXT_ENGINE_VERSION, "text": text_summary})

    return {
        "engine": "baseline",
        "version": TEXT_ENGINE_VERSION,
        "text": text_summary,
        "input_hash": input_hash,
    }
