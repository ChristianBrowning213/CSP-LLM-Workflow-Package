"""Audit Crystal-DB coverage and result-section candidates.

This script is intentionally read-only for SQLite databases. It writes JSON and
Markdown artifacts under ``artifacts/``.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "data" / "phase6_mp_10k.db"
DEFAULT_POT_ROOTS = (
    Path(r"C:\Users\brown\Downloads\SPP\SPP\SPP\SPP"),
    Path(r"C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP\QLIP_Outputs\SPP\runs"),
)

SECTION1_TARGETS = [
    ("NiO", "rocksalt AX", "rocksalt"),
    ("TiN", "rocksalt AX", "nitride"),
    ("MgO", "rocksalt AX", "rocksalt"),
    ("CeO2", "fluorite AX2", "fluorite"),
    ("ZrO2", "fluorite AX2", "fluorite"),
    ("ThO2", "fluorite AX2", "fluorite"),
    ("CsPbBr3", "halide perovskite ABX3", "halide perovskite"),
    ("CsSnBr3", "halide perovskite ABX3", "halide perovskite"),
    ("CsPbCl3", "halide perovskite ABX3", "halide perovskite"),
    ("ZnFe2O4", "spinel AB2O4", "spinel"),
    ("MgAl2O4", "spinel AB2O4", "spinel"),
    ("CoFe2O4", "spinel AB2O4", "spinel"),
]

SCAFFOLD_SUPPORTED = {
    "NiO",
    "TiN",
    "MgO",
    "CeO2",
    "ZrO2",
    "ThO2",
    "CsPbBr3",
    "CsSnBr3",
    "CsPbCl3",
    "ZnFe2O4",
    "MgAl2O4",
    "CoFe2O4",
    "LiCoO2",
    "NaCoO2",
    "LiNiO2",
    "LiFePO4",
    "NaFePO4",
    "LiMnPO4",
    "Li6PS5Cl",
    "Li6PS5Br",
    "Li6PS5I",
}

HARD_SEEDS = [
    ("LiCoO2", "layered oxide"),
    ("NaCoO2", "layered oxide"),
    ("LiNiO2", "layered oxide"),
    ("LiFePO4", "olivine phosphate"),
    ("NaFePO4", "olivine phosphate"),
    ("LiMnPO4", "olivine phosphate"),
    ("Li6PS5Cl", "argyrodite"),
    ("Li6PS5Br", "argyrodite"),
    ("Li6PS5I", "argyrodite"),
]

MOTIF_TERMS = {
    "kagome/kagomite-like": ["kagome", "kagomite"],
    "pyrochlore": ["pyrochlore"],
    "garnet": ["garnet"],
    "olivine/phosphate": ["olivine", "phosphate"],
    "argyrodite": ["argyrodite"],
    "layered oxide": ["layered", "lithiated", "sodium"],
}


@dataclass(frozen=True)
class PotInventory:
    root: str
    exists: bool
    pot_file_count: int
    pairs: set[str]


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def count(conn: sqlite3.Connection, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int | None:
    if not table_exists(conn, table):
        return None
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return int(conn.execute(sql, params).fetchone()[0])


def canonical_element(symbol: str) -> str:
    value = str(symbol or "").strip()
    return value[:1].upper() + value[1:].lower() if value else value


def parse_formula(formula: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for element, amount in re.findall(r"([A-Z][a-z]?)(\d*)", formula or ""):
        counts[canonical_element(element)] += int(amount or "1")
    return dict(counts)


def reduce_counts(counts: dict[str, int]) -> dict[str, int]:
    values = [value for value in counts.values() if value]
    if not values:
        return {}
    gcd = values[0]
    for value in values[1:]:
        a, b = gcd, value
        while b:
            a, b = b, a % b
        gcd = a
    return {element: value // gcd for element, value in counts.items()}


def normalized_formula(formula: str) -> str:
    counts = reduce_counts(parse_formula(formula))
    return "".join(f"{element}{amount if amount != 1 else ''}" for element, amount in counts.items())


def required_pairs(formula: str) -> list[str]:
    elements = sorted(parse_formula(formula), key=str.lower)
    return [f"{left}-{right}" for left, right in combinations_with_replacement(elements, 2)]


def canonical_pair(pair: str) -> str:
    parts = [canonical_element(part) for part in str(pair).replace("_", "-").split("-") if part]
    return "-".join(sorted(parts, key=str.lower)) if len(parts) == 2 else str(pair)


def load_pot_inventory(root: Path) -> PotInventory:
    if not root.is_dir():
        return PotInventory(str(root), False, 0, set())
    pairs: set[str] = set()
    count_files = 0
    for pot_file in root.rglob("*.POT"):
        count_files += 1
        pairs.add(canonical_pair(pot_file.stem))
    return PotInventory(str(root), True, count_files, pairs)


def audit_pot_coverage(formula: str, inventories: list[PotInventory]) -> dict[str, Any]:
    pairs = [canonical_pair(pair) for pair in required_pairs(formula)]
    by_root = []
    compatible_roots = []
    best_missing: list[str] | None = None
    for inv in inventories:
        missing = sorted(set(pairs) - inv.pairs)
        if best_missing is None or len(missing) < len(best_missing):
            best_missing = missing
        entry = {
            "root": inv.root,
            "exists": inv.exists,
            "pot_file_count": inv.pot_file_count,
            "available_pairs": sorted(set(pairs) & inv.pairs),
            "missing_pairs": missing,
            "compatible": inv.exists and not missing,
        }
        if entry["compatible"]:
            compatible_roots.append(inv.root)
        by_root.append(entry)
    return {
        "required_pairs": sorted(pairs),
        "compatible_roots": compatible_roots,
        "best_missing_pairs": best_missing or [],
        "by_root": by_root,
    }


def inventory_db(path: Path) -> dict[str, Any]:
    with connect_readonly(path) as conn:
        tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        result: dict[str, Any] = {
            "path": str(path),
            "file_size_bytes": path.stat().st_size,
            "tables": tables,
            "rows": {table: count(conn, table) for table in tables},
            "structures_rows": count(conn, "structures"),
            "metadata_rows": count(conn, "metadata"),
            "provenance_rows": count(conn, "provenance"),
            "distinct_formulas": None,
            "distinct_space_groups": None,
            "distinct_provenance_sources": None,
            "cif_availability": {},
            "feature_counts": {},
        }
        if table_exists(conn, "metadata"):
            result["distinct_formulas"] = int(conn.execute("SELECT COUNT(DISTINCT formula) FROM metadata WHERE formula IS NOT NULL AND formula != ''").fetchone()[0])
            result["distinct_space_groups"] = int(conn.execute("SELECT COUNT(DISTINCT space_group) FROM metadata WHERE space_group IS NOT NULL AND space_group != ''").fetchone()[0])
        if table_exists(conn, "provenance"):
            result["distinct_provenance_sources"] = int(conn.execute("SELECT COUNT(DISTINCT source) FROM provenance WHERE source IS NOT NULL AND source != ''").fetchone()[0])
            result["provenance_sources"] = {
                row["source"]: row["n"]
                for row in conn.execute("SELECT source, COUNT(*) AS n FROM provenance GROUP BY source ORDER BY n DESC")
            }
        if table_exists(conn, "structures"):
            result["cif_availability"] = {
                "cif_text_present": count(conn, "structures", "cif_text IS NOT NULL AND cif_text != ''"),
                "cif_text_missing": count(conn, "structures", "cif_text IS NULL OR cif_text = ''"),
                "license_restricted": count(conn, "structures", "COALESCE(license_restricted, 0) != 0"),
            }
        for table in [
            "structure_descriptors",
            "structure_texts",
            "text_docs",
            "text_embeddings",
            "structure_sequences",
            "structure_embeddings",
            "structure_fingerprints",
            "structure_crystalcards",
            "query_embeddings",
        ]:
            if table_exists(conn, table):
                result["feature_counts"][table] = count(conn, table)
        if table_exists(conn, "text_embeddings"):
            result["feature_counts"]["text_embeddings_ok"] = count(conn, "text_embeddings", "status = 'OK'")
            result["embedding_spaces"] = [
                dict(row)
                for row in conn.execute(
                    "SELECT embed_engine, model, model_version, dim, status, COUNT(*) AS n "
                    "FROM text_embeddings GROUP BY embed_engine, model, model_version, dim, status "
                    "ORDER BY n DESC"
                )
            ]
        return result


def formula_rows(conn: sqlite3.Connection, formula: str) -> list[sqlite3.Row]:
    norm = normalized_formula(formula)
    rows = conn.execute(
        "SELECT s.structure_id, s.reduced_formula, s.cif_text, s.license_restricted, "
        "m.formula, m.space_group, p.source, p.source_id, p.allow_export, p.allow_derivatives "
        "FROM structures s "
        "LEFT JOIN metadata m ON m.structure_id = s.structure_id "
        "LEFT JOIN provenance p ON p.structure_id = s.structure_id "
        "ORDER BY COALESCE(p.allow_export, 0) DESC, s.structure_id",
    ).fetchall()
    return [
        row
        for row in rows
        if normalized_formula(row["reduced_formula"] or "") == norm or normalized_formula(row["formula"] or "") == norm
    ]


def feature_presence(conn: sqlite3.Connection, structure_id: str) -> dict[str, bool]:
    return {
        "has_text_embedding": bool(
            table_exists(conn, "text_embeddings")
            and conn.execute(
                "SELECT 1 FROM text_embeddings te JOIN text_docs td ON td.id = te.text_doc_id "
                "WHERE td.structure_id = ? AND te.status = 'OK' LIMIT 1",
                (structure_id,),
            ).fetchone()
        ),
        "has_fingerprint": bool(
            table_exists(conn, "structure_fingerprints")
            and conn.execute("SELECT 1 FROM structure_fingerprints WHERE structure_id = ? LIMIT 1", (structure_id,)).fetchone()
        ),
        "has_crystalcard": bool(
            table_exists(conn, "structure_crystalcards")
            and conn.execute("SELECT 1 FROM structure_crystalcards WHERE structure_id = ? LIMIT 1", (structure_id,)).fetchone()
        ),
    }


def audit_formula(conn: sqlite3.Connection, formula: str, family: str, motif: str, pot_inventories: list[PotInventory]) -> dict[str, Any]:
    rows = formula_rows(conn, formula)
    rep = rows[0] if rows else None
    pot = audit_pot_coverage(formula, pot_inventories)
    features = feature_presence(conn, rep["structure_id"]) if rep else {
        "has_text_embedding": False,
        "has_fingerprint": False,
        "has_crystalcard": False,
    }
    has_export = bool(rep and rep["allow_export"] not in (0, False, None))
    has_cif = bool(rep and rep["cif_text"])
    if not rows:
        status = "blocked_missing_crystaldb"
    elif not pot["compatible_roots"]:
        status = "blocked_missing_pot"
    elif formula not in SCAFFOLD_SUPPORTED:
        status = "scaffold_only"
    elif not has_export:
        status = "partial_candidate"
    elif not (features["has_text_embedding"] and features["has_fingerprint"]):
        status = "partial_candidate"
    else:
        status = "full_result_candidate"
    return {
        "formula": formula,
        "family": family,
        "motif": motif,
        "exact_reduced_formula_present": bool(rows),
        "count": len(rows),
        "representative": dict(rep) if rep else None,
        "space_groups": sorted({row["space_group"] for row in rows if row["space_group"]}),
        "has_cif": has_cif,
        **features,
        "export_allowed": has_export,
        "pot_coverage": pot,
        "scaffold_supported": formula in SCAFFOLD_SUPPORTED,
        "recommended_status": status,
    }


def family_from_formula_space_text(formula: str, space_group: str | None, text: str) -> str | None:
    lower = (text or "").lower()
    counts = parse_formula(formula)
    elements = set(counts)
    if "kagome" in lower or "kagomite" in lower:
        return "kagome/kagomite-like"
    if "pyrochlore" in lower or (space_group in {"Fd-3m", "Fd-3m:2"} and formula.endswith("O7")):
        return "pyrochlore"
    if "garnet" in lower or (space_group in {"Ia-3d"} and formula.endswith("O12")):
        return "garnet"
    if "argyrodite" in lower or formula.startswith("Li6PS5"):
        return "argyrodite"
    if "olivine" in lower or ("P" in elements and "O" in elements and ("Li" in elements or "Na" in elements) and space_group == "Pnma"):
        return "olivine/phosphate"
    if "layered" in lower or (formula in {"LiCoO2", "NaCoO2", "LiNiO2"} or space_group == "R-3m" and "O" in elements and ({"Li", "Na"} & elements)):
        return "layered oxide"
    return None


def hard_candidates(conn: sqlite3.Connection, pot_inventories: list[PotInventory]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for formula, motif in HARD_SEEDS:
        rows = formula_rows(conn, formula)
        if rows:
            row = rows[0]
            candidates[formula] = {
                "formula": formula,
                "family_or_motif": motif,
                "space_group": row["space_group"],
                "count": len(rows),
                "representative_ids": [r["structure_id"] for r in rows[:3]],
            }
    rows = conn.execute(
        "SELECT s.structure_id, m.formula, m.space_group, m.elements_csv, s.nsites, s.volume, "
        "COALESCE(td.text, sd.descriptor_text, '') AS text "
        "FROM structures s "
        "JOIN metadata m ON m.structure_id = s.structure_id "
        "LEFT JOIN text_docs td ON td.structure_id = s.structure_id AND td.status = 'OK' "
        "LEFT JOIN structure_descriptors sd ON sd.structure_id = s.structure_id "
        "WHERE m.formula IS NOT NULL "
        "ORDER BY s.structure_id"
    ).fetchall()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        formula = normalized_formula(row["formula"])
        motif = family_from_formula_space_text(formula, row["space_group"], row["text"])
        if not motif:
            continue
        entry = grouped.setdefault(
            formula,
            {
                "formula": formula,
                "family_or_motif": motif,
                "space_group": row["space_group"],
                "count": 0,
                "representative_ids": [],
                "nsites": row["nsites"],
            },
        )
        entry["count"] += 1
        if len(entry["representative_ids"]) < 3:
            entry["representative_ids"].append(row["structure_id"])
    for formula, entry in grouped.items():
        candidates.setdefault(formula, entry)

    low_sym = conn.execute(
        "SELECT m.formula, m.space_group, COUNT(*) AS n, MIN(s.structure_id) AS sid, MAX(s.nsites) AS nsites "
        "FROM structures s JOIN metadata m ON m.structure_id = s.structure_id "
        "WHERE m.space_group IN ('P1', 'P 1', 'P-1', 'P -1', 'P2_1/c', 'P 21/c', 'C2/m', 'C 2/m', 'Pc', 'Cc') "
        "GROUP BY m.formula, m.space_group ORDER BY n DESC, nsites DESC LIMIT 20"
    ).fetchall()
    for row in low_sym:
        formula = normalized_formula(row["formula"])
        if formula not in candidates:
            candidates[formula] = {
                "formula": formula,
                "family_or_motif": "low-symmetry unusual space group",
                "space_group": row["space_group"],
                "count": row["n"],
                "representative_ids": [row["sid"]],
                "nsites": row["nsites"],
            }

    ranked = sorted(candidates.values(), key=lambda x: (x["family_or_motif"], -int(x.get("count") or 0), x["formula"]))
    out: list[dict[str, Any]] = []
    seen_families = Counter()
    for item in ranked:
        if len(out) >= 18:
            break
        if seen_families[item["family_or_motif"]] >= 4:
            continue
        pot = audit_pot_coverage(item["formula"], pot_inventories)
        scaffold = item["formula"] in SCAFFOLD_SUPPORTED
        if scaffold and pot["compatible_roots"]:
            use = "hard_success_candidate"
        elif scaffold or pot["compatible_roots"]:
            use = "hard_partial_demo"
        else:
            use = "future_dataset_candidate"
        difficulty = {
            "argyrodite": "multi-anion mobile-ion motif with five-element pair space",
            "layered oxide": "ordered layered motif where stacking and cation sublattices matter",
            "olivine/phosphate": "lower-symmetry phosphate framework with complex oxyanion geometry",
            "pyrochlore": "large cubic oxide motif with multiple cation sublattices",
            "garnet": "large formula/unit-cell framework motif",
            "kagome/kagomite-like": "motif-specific net request rather than formula-only retrieval",
            "low-symmetry unusual space group": "low symmetry raises coordinate/orbit intent complexity",
        }.get(item["family_or_motif"], "motif-specific crystallographic intent")
        out.append(
            {
                **item,
                "why_harder": difficulty,
                "pot_coverage": pot,
                "current_qlip_orbit_scaffold_support": scaffold,
                "recommended_use": use,
            }
        )
        seen_families[item["family_or_motif"]] += 1
    return out


def active_db_recommendation(inventories: list[dict[str, Any]]) -> dict[str, Any]:
    def score(item: dict[str, Any]) -> tuple[int, int, int, int]:
        features = item.get("feature_counts", {})
        return (
            int(item.get("structures_rows") or 0),
            int(features.get("text_embeddings_ok") or 0),
            int(features.get("structure_fingerprints") or 0),
            int((item.get("cif_availability") or {}).get("cif_text_present") or 0),
        )

    best = max(inventories, key=score)
    return {
        "path": best["path"],
        "reason": "Largest real-material corpus with MP/local provenance, CIF text, fingerprints, descriptors/text docs, and text embeddings compatible with current retrieval APIs.",
        "score_tuple": score(best),
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("\n", " ") for value in row) + " |")
    return "\n".join(lines)


def render_inventory_md(payload: dict[str, Any]) -> str:
    rows = []
    for item in payload["databases"]:
        rows.append(
            [
                item["path"],
                item["file_size_bytes"],
                item.get("structures_rows"),
                item.get("metadata_rows"),
                item.get("provenance_rows"),
                item.get("distinct_formulas"),
                item.get("distinct_space_groups"),
                (item.get("cif_availability") or {}).get("cif_text_present"),
                (item.get("feature_counts") or {}).get("text_embeddings_ok"),
                (item.get("feature_counts") or {}).get("structure_fingerprints"),
                (item.get("feature_counts") or {}).get("structure_crystalcards"),
            ]
        )
    return "\n\n".join(
        [
            "# Crystal-DB Dataset Inventory",
            "## Executive Summary",
            f"Recommended active DB: `{payload['active_db_recommendation']['path']}`.",
            "## Database Inventory",
            markdown_table(
                ["DB", "bytes", "structures", "metadata", "provenance", "formulas", "SGs", "CIFs", "OK text embeds", "FPs", "CrystalCards"],
                rows,
            ),
            "## POT Roots",
            markdown_table(
                ["root", "exists", "POT files", "distinct pairs"],
                [[p["root"], p["exists"], p["pot_file_count"], p["distinct_pair_count"]] for p in payload["pot_roots"]],
            ),
        ]
    ) + "\n"


def render_candidate_md(payload: dict[str, Any]) -> str:
    section1_rows = []
    for item in payload["section1_candidates"]:
        rep = item.get("representative") or {}
        section1_rows.append(
            [
                item["formula"],
                item["family"],
                item["count"],
                ", ".join(item["space_groups"][:3]),
                rep.get("structure_id", ""),
                "yes" if item["has_cif"] else "no",
                "yes" if item["has_text_embedding"] else "no",
                "yes" if item["has_fingerprint"] else "no",
                "yes" if item["export_allowed"] else "no",
                "yes" if item["pot_coverage"]["compatible_roots"] else "no",
                item["recommended_status"],
            ]
        )
    hard_rows = [
        [
            item["formula"],
            item["family_or_motif"],
            item.get("space_group"),
            item["count"],
            ", ".join(item["representative_ids"]),
            "yes" if item["pot_coverage"]["compatible_roots"] else "no",
            "yes" if item["current_qlip_orbit_scaffold_support"] else "no",
            item["recommended_use"],
        ]
        for item in payload["section2_hard_candidates"]
    ]
    commands = "\n".join(f"- `{cmd}`" for cmd in payload["exact_next_commands"])
    options = [
        ["Kagome-focused MP subset", "MP API via `grab_mp_bulk.py` using element/chemsys filters then folder ingest", "local_cif", "hundreds to low thousands", "motif-text retrieval and hard net requests", "Requires MP API key and a query definition that captures kagome chemistry."],
        ["Battery-material subset", "MP Li/Na transition-metal oxides/phosphates/sulfides", "local_cif", "thousands", "LiCoO2/LiFePO4/argyrodite retrieval and CSP smoke tasks", "Needs acquisition time and post-ingest embeddings."],
        ["Low-symmetry inorganic subset", "MP stable structures filtered after ingest by low-symmetry SG", "local_cif", "hundreds to thousands", "coordinate/SG-intent retrieval distinct from default corpus", "Needs either MP metadata filtering or a larger indexed MP slice."],
        ["MOF/porous framework corpus", "Local legally usable CIF folder if available", "local_cif or restricted", "unknown", "porosity/framework specialist retrieval", "No local MOF/CSD-like source was confirmed by this audit."],
        ["Pharmaceutical/medical crystals", "Only from open/legal CIF sources or user-provided corpus", "restricted unless license clear", "unknown", "domain-shift molecular crystal corpus", "Legal/source clarity required before storage/export claims."],
    ]
    return "\n\n".join(
        [
            "# Result Section Candidate Audit",
            "## Executive Summary",
            payload["executive_summary"],
            "## Active Dataset Recommendation",
            f"`{payload['active_db_recommendation']['path']}`: {payload['active_db_recommendation']['reason']}",
            "## Dataset/Vectorisation/Storage Pipeline",
            "\n".join(f"- {line}" for line in payload["pipeline_summary"]),
            "## Result Section 1 Candidate Table",
            markdown_table(["formula", "family", "count", "SGs", "representative", "CIF", "text emb", "FP", "export", "POT", "status"], section1_rows),
            "## Result Section 2 Hard Candidate Table",
            markdown_table(["formula", "motif", "SG", "count", "representatives", "POT", "scaffold", "use"], hard_rows),
            "## Result Section 3 Specialist-Corpus Options",
            markdown_table(["option", "source/acquisition", "policy", "expected size", "result task", "blockers"], options),
            "## Recommended Final Result Plan",
            "\n".join(f"- {line}" for line in payload["recommended_final_result_plan"]),
            "## Blockers And Exact Next Commands",
            commands,
        ]
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--pot-root", type=Path, action="append", default=[])
    args = parser.parse_args()

    db_paths = sorted(set(args.data_dir.rglob("*.db")))
    inventories = [inventory_db(path) for path in db_paths]
    active = active_db_recommendation(inventories)
    pot_roots = list(args.pot_root) or list(DEFAULT_POT_ROOTS)
    pot_inventories = [load_pot_inventory(root) for root in pot_roots]

    inventory_payload = {
        "schema_version": "crystaldb_dataset_inventory.v1",
        "databases": inventories,
        "active_db_recommendation": active,
        "pot_roots": [
            {
                "root": inv.root,
                "exists": inv.exists,
                "pot_file_count": inv.pot_file_count,
                "distinct_pair_count": len(inv.pairs),
                "sample_pairs": sorted(inv.pairs)[:25],
            }
            for inv in pot_inventories
        ],
    }

    with connect_readonly(args.db) as conn:
        section1 = [audit_formula(conn, formula, family, motif, pot_inventories) for formula, family, motif in SECTION1_TARGETS]
        hard = hard_candidates(conn, pot_inventories)

    pipeline_summary = [
        "CIF acquisition: `grab_mp_bulk.py` uses the Materials Project API, writes CIF files plus `manifest.jsonl`; `ingest-folder` recursively ingests local CIF folders.",
        "Ingestion: `crystal_db.ingest_folder.ingest_folder` normalizes CIF text, hashes it, parses formula/space group/volume, and writes `structures`, `metadata`, and `provenance`.",
        "Policy/provenance: `policies.yaml` controls CIF storage/return/derivatives/export; provenance stores source, source_id, retrieved_at, policy_id, and allow_* flags.",
        "Fingerprints: `crystal_db.fingerprint` builds `fp.simple.v1` vectors from formula element counts plus nsites, volume, and band gap.",
        "Text descriptions: `gen-text`/`crystal_db.text_index` call text engines such as robocrys/caption/baseline and store `text_docs`; legacy `structure_texts` is also populated for robocrys view.",
        "Embeddings: `embed-text` stores vectors in `text_embeddings`; `hash-embed` is deterministic local hashing, while `lmstudio/text-embedding-bge-m3/lmstudio_v1` calls an OpenAI-compatible LM Studio `/embeddings` endpoint.",
        "Retrieval: `similar_struct` uses fingerprint distance; `similar_text` uses existing text embeddings by structure; `similar_seq` canonicalizes CIF text and embeds sequences; `similar_hybrid` reciprocal-rank fuses requested sources.",
        "Current active DB embedding evidence: text embeddings are present in the `lmstudio/text-embedding-bge-m3/lmstudio_v1` space, so the active DB is using real local LM Studio embeddings rather than only hash embeddings for text retrieval.",
    ]
    recommended_plan = [
        "Use Section 1 only for formulas with Crystal-DB rows, text embeddings, fingerprints, and complete real POT coverage; current audit marks missing-DB formulas as blocked.",
        "Lead with the strongest supported families from the active DB, then add hard motif demos where both the DB and scaffold support exist.",
        "For Section 2, prioritize layered oxide, olivine phosphate, and argyrodite candidates if their formulas are present and POT coverage is complete; otherwise treat as retrieval-only/future demos.",
        "For Section 3, build a separate folder-ingested corpus under `local_cif` policy, then run `gen-text` and `embed-text` before claiming dataset agnosticism.",
    ]
    exact_next_commands = [
        '@\'\nimport sqlite3\np="data/phase6_mp_10k.db"\ncon=sqlite3.connect(p)\nfor t in ["structures","metadata","provenance","text_docs","text_embeddings","structure_fingerprints"]:\n    print(t, con.execute(f"select count(*) from {t}").fetchone()[0])\n\'@ | python -',
        'python grab_mp_bulk.py --out data/mp_battery_subset --max 2000 --stable-only --elements Li Na O P S Fe Co Ni Mn --resume',
        'python -m crystal_db ingest-folder --db data/battery_subset.db --path data/mp_battery_subset --source mp_battery_subset --policy local_cif',
        'python -m crystal_db gen-text --db data/battery_subset.db --engine robocrys --text-view robocrys --all --progress-every 100',
        'python -m crystal_db embed-text --db data/battery_subset.db --text-engine robocrys --text-view robocrys --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --all --progress-every 100',
        'python -m crystal_db bench-retrieval --db data/phase6_mp_10k.db --cases <cases.jsonl> --out artifacts/retrieval_eval --k 10',
        'python C:\\Users\\brown\\Documents\\GitHub\\Skill-Loop-CSP\\scripts\\run_prototype_orbit_variable_spp_qlip_smoke.py --pot-dir C:\\Users\\brown\\Downloads\\SPP\\SPP\\SPP\\SPP --require-real-spp --out-root C:\\Users\\brown\\Documents\\GitHub\\Structured_Crystal_Analyser\\local_runs\\result_section_smoke',
    ]
    candidate_payload = {
        "schema_version": "result_section_candidate_audit.v1",
        "executive_summary": "The audit is evidence-backed against live SQLite rows and real `.POT` files. `phase6_mp_10k.db` is the active dataset; Section 1 should use only targets that are present in Crystal-DB and have complete SPP pair coverage.",
        "active_db_recommendation": active,
        "pipeline_summary": pipeline_summary,
        "section1_candidates": section1,
        "section2_hard_candidates": hard,
        "section3_specialist_corpus_options": [
            "kagome-focused MP subset",
            "battery materials subset",
            "low-symmetry inorganic subset",
            "MOF/porous framework corpus if local legal CIFs exist",
            "pharmaceutical/medical crystals only with legal/source clarity",
        ],
        "recommended_final_result_plan": recommended_plan,
        "exact_next_commands": exact_next_commands,
    }

    artifacts = REPO_ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "crystaldb_dataset_inventory.json").write_text(json.dumps(inventory_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (artifacts / "crystaldb_dataset_inventory.md").write_text(render_inventory_md(inventory_payload), encoding="utf-8")
    (artifacts / "result_section_candidate_audit.json").write_text(json.dumps(candidate_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (artifacts / "result_section_candidate_audit.md").write_text(render_candidate_md(candidate_payload), encoding="utf-8")
    print(json.dumps({"inventory": "artifacts/crystaldb_dataset_inventory.json", "candidate_audit": "artifacts/result_section_candidate_audit.json"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
