import hashlib
import os
from typing import Dict, List, Optional, Tuple

from .db import connect, init_db
from .policy import get_policy
from .utils import elements_from_csv, now_iso_utc, parse_cif_text, parse_formula


def _normalize_cif(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines) + "\n"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _elements_csv_from_formula(formula: Optional[str]) -> str:
    counts = parse_formula(formula)
    elements = sorted(counts.keys())
    if not elements:
        return ""
    return "," + ",".join(elements) + ","


def ingest_folder(
    *,
    db_path: Optional[str],
    folder_path: str,
    source: str,
    policy_name: str,
    cache_dir: Optional[str] = None,
) -> Dict[str, int]:
    conn = connect(db_path)
    init_db(conn)

    policy = get_policy(policy_name)
    ingested = 0
    skipped = 0

    cif_files: List[str] = []
    for root, _, files in os.walk(folder_path):
        for name in files:
            if name.lower().endswith(".cif"):
                cif_files.append(os.path.join(root, name))

    cif_files.sort()

    for path in cif_files:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        normalized = _normalize_cif(raw)
        input_hash = _hash_text(normalized)
        source_id = os.path.relpath(path, folder_path).replace("\\", "/")
        structure_id = f"{source}-{input_hash[:8]}"

        existing = conn.execute(
            "SELECT structure_id FROM provenance WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        if existing:
            structure_id = existing["structure_id"]

        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            cache_path = os.path.join(cache_dir, f"{input_hash}.cif")
            if not os.path.exists(cache_path):
                with open(cache_path, "w", encoding="utf-8") as cache_file:
                    cache_file.write(normalized)

        cif_text = normalized if policy.allow_cif_store else None
        license_restricted = 0 if policy.allow_cif_return else 1

        parsed = parse_cif_text(normalized)
        formula = parsed.get("formula")
        space_group = parsed.get("space_group")
        volume = parsed.get("volume")

        elements_csv = _elements_csv_from_formula(formula)

        conn.execute(
            "INSERT OR REPLACE INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                structure_id,
                cif_text,
                formula,
                None,
                volume,
                license_restricted,
            ),
        )

        conn.execute(
            "INSERT OR REPLACE INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (structure_id, formula, elements_csv, space_group, None),
        )

        conn.execute(
            "INSERT OR REPLACE INTO provenance (structure_id, source, source_id, retrieved_at, license_notes, "
            "policy_id, allow_cif_store, allow_cif_return, allow_derivatives, allow_export) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                structure_id,
                source,
                source_id,
                now_iso_utc(),
                policy.license_notes,
                policy.name,
                1 if policy.allow_cif_store else 0,
                1 if policy.allow_cif_return else 0,
                1 if policy.allow_derivatives else 0,
                1 if policy.allow_export else 0,
            ),
        )

        if existing:
            skipped += 1
        else:
            ingested += 1

    conn.commit()
    conn.close()

    return {"ingested": ingested, "skipped": skipped, "total": len(cif_files)}
