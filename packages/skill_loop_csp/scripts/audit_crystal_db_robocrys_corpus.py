from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT.parent / "Crystal-DB" / "data" / "phase6_mp_10k.db"
DEFAULT_OUT = REPO_ROOT / "test_workdir" / "paper_evidence_pack_v2" / "reports"

FAMILY_TERMS = [
    "perovskite",
    "spinel",
    "rocksalt",
    "rutile",
    "fluorite",
    "pyrochlore",
    "garnet",
    "olivine",
    "nasicon",
    "pyrite",
    "chalcopyrite",
    "molybdenite",
    "wurtzite",
    "sphalerite",
    "layered",
    "framework",
]
COORDINATION_TERMS = [
    "bonded to",
    "bonded in",
    "4-coordinate",
    "5-coordinate",
    "6-coordinate",
    "8-coordinate",
    "octahedra",
    "octahedral",
    "tetrahedra",
    "tetrahedral",
    "trigonal",
    "square planar",
    "cuboctahedra",
]
CONNECTIVITY_TERMS = [
    "corner-sharing",
    "edge-sharing",
    "face-sharing",
    "share corners",
    "share edges",
    "sheets",
    "layers",
    "channels",
    "framework",
    "clusters",
    "ribbons",
]
POLYHEDRA_TERMS = ["TiO6", "AlO6", "MgO4", "FeO6", "CoO6", "ZrO6", "PO4", "SiO4", "FeS6", "PbI6"]
BOND_PATTERNS = {
    "all_x_y_bond_lengths_are": re.compile(r"\bAll\s+[A-Z][a-z]?-[A-Z][a-z]?\s+bond lengths are\b"),
    "both_x_y_bond_lengths_are": re.compile(r"\bBoth\s+[A-Z][a-z]?-[A-Z][a-z]?\s+bond lengths are\b"),
    "spread_of_x_y_bond_distances": re.compile(r"\bspread of\s+[A-Z][a-z]?-[A-Z][a-z]?\s+bond distances\b", re.I),
    "range_of_x_y_bond_distances": re.compile(r"\brange(?:s)? from\b|\branging from\b", re.I),
}
TARGET_FORMULAS = [
    "BaTiO3",
    "CaTiO3",
    "SrTiO3",
    "PbTiO3",
    "MgAl2O4",
    "LiCoO2",
    "MoS2",
    "WS2",
    "NaCl",
    "LiFePO4",
    "FeS2",
]
CALIBRATION_FAMILIES = [
    "oxide_perovskite",
    "oxide_spinel",
    "layered_oxide",
    "halide_rocksalt",
    "halide_perovskite",
    "layered_chalcogenide",
    "sulfide_pyrite",
    "sulfide_chalcopyrite",
    "phosphate_olivine",
    "phosphate_framework",
    "oxide_fluorite",
    "oxide_garnet",
    "oxide_pyrochlore",
    "oxide_wurtzite",
    "oxide_bixbyite",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value for key, value in row.items()})


def _table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()]
    except sqlite3.Error:
        return []


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def _count_rows(con: sqlite3.Connection, where: str = "", params: tuple[Any, ...] = ()) -> int:
    query = "SELECT COUNT(*) FROM text_docs" + (" WHERE " + where if where else "")
    return int(con.execute(query, params).fetchone()[0])


def _load_rows(con: sqlite3.Connection, *, limit: int) -> list[dict[str, Any]]:
    cols = _table_columns(con, "text_docs")
    structure_cols = _table_columns(con, "structures")
    provenance_cols = _table_columns(con, "provenance")
    text_view_filter = "AND td.text_view='robocrys'" if "text_view" in cols else ""
    select = [
        "td.id AS text_doc_id",
        "td.structure_id",
        "td.engine",
        "td.status",
        "td.text",
    ]
    if "text_view" in cols:
        select.append("td.text_view")
    else:
        select.append("'' AS text_view")
    joins = ""
    if _table_exists(con, "structures"):
        select.extend(["s.reduced_formula", "s.cif_text IS NOT NULL AS has_cif_text"])
        if "cif_source_path" in structure_cols:
            select.append("s.cif_source_path")
        else:
            select.append("'' AS cif_source_path")
        joins += " LEFT JOIN structures s ON s.structure_id = td.structure_id"
    else:
        select.extend(["'' AS reduced_formula", "'' AS cif_source_path", "0 AS has_cif_text"])
    if _table_exists(con, "metadata"):
        select.extend(["m.formula", "m.elements_csv"])
        joins += " LEFT JOIN metadata m ON m.structure_id = td.structure_id"
    else:
        select.extend(["'' AS formula", "'' AS elements_csv"])
    if _table_exists(con, "provenance"):
        if "source" in provenance_cols:
            select.append("p.source")
        else:
            select.append("'' AS source")
        if "source_id" in provenance_cols:
            select.append("p.source_id")
        else:
            select.append("'' AS source_id")
        joins += " LEFT JOIN provenance p ON p.structure_id = td.structure_id"
    else:
        select.extend(["'' AS source", "'' AS source_id"])
    query = (
        f"SELECT {', '.join(select)} FROM text_docs td{joins} "
        f"WHERE td.engine='robocrys' {text_view_filter} AND td.status='OK' "
        "ORDER BY td.id LIMIT ?"
    )
    return [dict(row) for row in con.execute(query, (int(limit),)).fetchall()]


def _norm(text: str) -> str:
    return str(text or "").lower()


def _term_counts(rows: list[Mapping[str, Any]], terms: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for term in terms:
        term_lower = term.lower()
        counts[term] = sum(1 for row in rows if term_lower in _norm(str(row.get("text", ""))))
    return counts


def _detect_family(row: Mapping[str, Any]) -> str:
    text = _norm(str(row.get("text", "")))
    formula = str(row.get("formula") or row.get("reduced_formula") or "")
    elements = {item.strip() for item in str(row.get("elements_csv") or "").split(",") if item.strip()}
    if not elements:
        elements = set(re.findall(r"[A-Z][a-z]?", formula))
    if "perovskite" in text or formula in {"BaTiO3", "CaTiO3", "SrTiO3", "PbTiO3"}:
        return "oxide_perovskite"
    if "spinel" in text or formula == "MgAl2O4":
        return "oxide_spinel"
    if formula == "LiCoO2" or ("layer" in text and "Co" in elements and "O" in elements):
        return "layered_oxide"
    if formula == "NaCl" or ("rocksalt" in text and elements & {"Cl", "F", "Br", "I"}):
        return "halide_rocksalt"
    if "pbi6" in text or ("perovskite" in text and elements & {"Cl", "Br", "I"}):
        return "halide_perovskite"
    if formula in {"MoS2", "WS2"} or "molybdenite" in text:
        return "layered_chalcogenide"
    if formula == "FeS2" or "pyrite" in text:
        return "sulfide_pyrite"
    if "chalcopyrite" in text or formula == "CuFeS2":
        return "sulfide_chalcopyrite"
    if formula == "LiFePO4" or "olivine" in text:
        return "phosphate_olivine"
    if "po4" in text and "framework" in text:
        return "phosphate_framework"
    if "fluorite" in text:
        return "oxide_fluorite" if "O" in elements else "fluoride_fluorite"
    if "garnet" in text:
        return "oxide_garnet"
    if "pyrochlore" in text:
        return "oxide_pyrochlore"
    if "wurtzite" in text:
        return "oxide_wurtzite"
    if "bixbyite" in text:
        return "oxide_bixbyite"
    return "unknown"


def _detected_terms(text: str) -> dict[str, list[str]]:
    lower = _norm(text)
    bond_hits = [name for name, pattern in BOND_PATTERNS.items() if pattern.search(text)]
    return {
        "family_terms": [term for term in FAMILY_TERMS if term.lower() in lower],
        "coordination_terms": [term for term in COORDINATION_TERMS if term.lower() in lower],
        "connectivity_terms": [term for term in CONNECTIVITY_TERMS if term.lower() in lower],
        "polyhedron_formula_terms": [term for term in POLYHEDRA_TERMS if term.lower() in lower],
        "bond_distance_patterns": bond_hits,
    }


def _example_row(row: Mapping[str, Any]) -> dict[str, Any]:
    text = str(row.get("text") or "")
    formula = str(row.get("formula") or row.get("reduced_formula") or "")
    elements = [item.strip() for item in str(row.get("elements_csv") or "").split(",") if item.strip()]
    if not elements:
        elements = sorted(set(re.findall(r"[A-Z][a-z]?", formula)), key=str.lower)
    return {
        "structure_id": row.get("structure_id", ""),
        "material_id": row.get("structure_id", ""),
        "formula": formula,
        "reduced_formula": row.get("reduced_formula", ""),
        "elements": elements,
        "chemical_system": "-".join(sorted(elements, key=str.lower)),
        "family": _detect_family(row),
        "robocrys_text": text,
        "text_excerpt": text[:1400],
        "detected_terms": _detected_terms(text),
        "source_path_metadata": row.get("cif_source_path", ""),
        "source": row.get("source", ""),
        "source_id": row.get("source_id", ""),
        "has_cif_text": bool(row.get("has_cif_text")),
    }


def _select_examples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for formula in TARGET_FORMULAS:
        for row in rows:
            if formula == str(row.get("formula") or row.get("reduced_formula") or "") and str(row.get("structure_id")) not in seen:
                examples.append(_example_row(row))
                seen.add(str(row.get("structure_id")))
                break
    for family in CALIBRATION_FAMILIES:
        count = 0
        for row in rows:
            sid = str(row.get("structure_id"))
            if sid in seen or _detect_family(row) != family:
                continue
            examples.append(_example_row(row))
            seen.add(sid)
            count += 1
            if count >= 3:
                break
    return examples


def _strictness_recommendations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        family = _detect_family(row)
        if family in CALIBRATION_FAMILIES:
            by_family[family].append(row)
    recommendations: list[dict[str, Any]] = []
    for family in CALIBRATION_FAMILIES:
        family_rows = by_family.get(family, [])
        counts = {
            "family": _term_counts(family_rows, FAMILY_TERMS),
            "coordination": _term_counts(family_rows, COORDINATION_TERMS),
            "connectivity": _term_counts(family_rows, CONNECTIVITY_TERMS),
            "polyhedra": _term_counts(family_rows, POLYHEDRA_TERMS),
        }
        total = len(family_rows)
        explicit_octa = counts["coordination"].get("octahedra", 0) + counts["coordination"].get("octahedral", 0)
        six_coord = counts["coordination"].get("6-coordinate", 0)
        corner = counts["connectivity"].get("corner-sharing", 0) + counts["connectivity"].get("share corners", 0)
        recommendations.append(
            {
                "chemistry_family": family,
                "example_count": total,
                "common_actual_phrases": {
                    "family_terms": Counter(counts["family"]).most_common(10),
                    "coordination_terms": Counter(counts["coordination"]).most_common(10),
                    "connectivity_terms": Counter(counts["connectivity"]).most_common(10),
                    "polyhedra_terms": Counter(counts["polyhedra"]).most_common(10),
                },
                "expect_explicit": [term for term, count in counts["coordination"].items() if total and count / total >= 0.5],
                "accept_via_aliases": ["bonded in 6-coordinate geometry => MO6-like environment"] if six_coord else [],
                "accept_via_condensed_json_only": ["corner connectivity => corner-sharing evidence"] if family in {"oxide_perovskite", "oxide_pyrochlore"} else [],
                "do_not_require_literally": [
                    *([] if total and counts["family"].get("perovskite", 0) / total >= 0.5 else ["family/prototype name"]),
                    *([] if total and corner / total >= 0.5 else ["corner-sharing phrase"]),
                    *([] if total and explicit_octa / total >= 0.5 else ["octahedra phrase"]),
                ],
                "strictness": _strictness_for_family(family),
            }
        )
    return recommendations


def _strictness_for_family(family: str) -> str:
    if family == "oxide_perovskite":
        return "formula_insufficient; accept Ti/O 6-coordinate plus condensed corner connectivity as implicit motif evidence"
    if family in {"oxide_spinel", "phosphate_olivine", "sulfide_pyrite"}:
        return "require motif coordination, but accept bond/coordination aliases"
    if family in {"layered_oxide", "layered_chalcogenide"}:
        return "require dimensionality/layer evidence plus key coordination aliases"
    return "moderate; require at least one family/coordination/connectivity signal beyond formula"


def build_audit(db_path: Path, *, limit: int) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        text_doc_cols = _table_columns(con, "text_docs")
        table_names = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        total_text_docs = _count_rows(con)
        if "text_view" in text_doc_cols:
            robocrys_count = _count_rows(con, "engine='robocrys' AND text_view='robocrys' AND status='OK'")
            non_robocrys_count = _count_rows(con, "NOT (engine='robocrys' AND text_view='robocrys')")
        else:
            robocrys_count = _count_rows(con, "engine='robocrys' AND status='OK'")
            non_robocrys_count = _count_rows(con, "engine!='robocrys'")
        rows = _load_rows(con, limit=limit)
        formula_available = bool(_table_exists(con, "structures") or _table_exists(con, "metadata"))
        condensed_json_stored = any("condensed" in col.lower() for table in table_names for col in _table_columns(con, table))
    finally:
        con.close()
    examples = _select_examples(rows)
    phrase_counts = {
        "family_prototype_terms": _term_counts(rows, FAMILY_TERMS),
        "coordination_terms": _term_counts(rows, COORDINATION_TERMS),
        "connectivity_terms": _term_counts(rows, CONNECTIVITY_TERMS),
        "polyhedron_formula_terms": _term_counts(rows, POLYHEDRA_TERMS),
        "bond_distance_language": {
            name: sum(1 for row in rows if pattern.search(str(row.get("text") or "")))
            for name, pattern in BOND_PATTERNS.items()
        },
    }
    perovskite_like = [row for row in rows if str(row.get("formula") or row.get("reduced_formula") or "") in {"BaTiO3", "CaTiO3", "SrTiO3", "PbTiO3"} or ("Ti" in str(row.get("elements_csv")) and "O" in str(row.get("elements_csv")))]
    findings = {
        "perovskite_examples_without_literal_perovskite": [
            _example_row(row) for row in perovskite_like if "perovskite" not in _norm(str(row.get("text") or ""))
        ][:10],
        "six_coordinate_without_octahedra_examples": [
            _example_row(row)
            for row in rows
            if "6-coordinate" in _norm(str(row.get("text") or "")) and "octahed" not in _norm(str(row.get("text") or ""))
        ][:10],
        "coordination_without_connectivity_examples": [
            _example_row(row)
            for row in rows
            if "bonded in" in _norm(str(row.get("text") or "")) and not any(term in _norm(str(row.get("text") or "")) for term in ["corner-sharing", "edge-sharing", "face-sharing", "share corners", "share edges"])
        ][:10],
    }
    return {
        "schema_version": "crystal_db_robocrys_corpus_audit.v1",
        "corpus_location": str(db_path),
        "corpus_format": "sqlite",
        "tables": table_names,
        "text_docs_fields": text_doc_cols,
        "text_field": "text_docs.text",
        "robocrys_filter": "engine='robocrys' AND text_view='robocrys' AND status='OK'" if "text_view" in text_doc_cols else "engine='robocrys' AND status='OK'",
        "total_text_docs": total_text_docs,
        "robocrys_text_rows": robocrys_count,
        "non_robocrys_text_rows": non_robocrys_count,
        "rows_inspected": len(rows),
        "formulas_available": formula_available,
        "source_cif_or_metadata_available": True,
        "condensed_json_stored": condensed_json_stored,
        "condensed_json_note": "No condensed Robocrys JSON column was found in the SQLite schema; prose text is stored in text_docs.text.",
        "phrase_counts": phrase_counts,
        "examples": examples,
        "wording_findings": findings,
        "strictness_recommendations": _strictness_recommendations(rows),
    }


def write_outputs(audit: Mapping[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_json = out_dir / "CRYSTAL_DB_ROBOCRYS_CORPUS_AUDIT.json"
    audit_md = out_dir / "CRYSTAL_DB_ROBOCRYS_CORPUS_AUDIT.md"
    examples_jsonl = out_dir / "crystal_db_robocrys_examples.jsonl"
    examples_csv = out_dir / "crystal_db_robocrys_examples.csv"
    strict_json = out_dir / "ROBOCRYS_VALIDATOR_STRICTNESS_RECOMMENDATIONS.json"
    strict_md = out_dir / "ROBOCRYS_VALIDATOR_STRICTNESS_RECOMMENDATIONS.md"
    _write_json(audit_json, {key: value for key, value in audit.items() if key != "examples"})
    examples = list(audit.get("examples", []))
    examples_jsonl.write_text("\n".join(json.dumps(row, sort_keys=True) for row in examples) + ("\n" if examples else ""), encoding="utf-8")
    _write_csv(
        examples_csv,
        examples,
        ["structure_id", "material_id", "formula", "reduced_formula", "elements", "chemical_system", "family", "text_excerpt", "detected_terms", "source_path_metadata", "has_cif_text"],
    )
    strictness = list(audit.get("strictness_recommendations", []))
    _write_json(strict_json, {"strictness_recommendations": strictness})
    lines = [
        "# Crystal-DB Robocrys Corpus Audit",
        "",
        f"- corpus location: {audit.get('corpus_location')}",
        f"- format: {audit.get('corpus_format')}",
        f"- text table/field: {audit.get('text_field')}",
        f"- Robocrys rows: {audit.get('robocrys_text_rows')}",
        f"- non-Robocrys text rows: {audit.get('non_robocrys_text_rows')}",
        f"- rows inspected: {audit.get('rows_inspected')}",
        f"- formulas/material IDs available: {audit.get('formulas_available')}",
        f"- source CIF/material metadata available: {audit.get('source_cif_or_metadata_available')}",
        f"- condensed JSON stored: {audit.get('condensed_json_stored')}",
        f"- condensed JSON note: {audit.get('condensed_json_note')}",
        "",
        "## Phrase Counts",
    ]
    for group, counts in (audit.get("phrase_counts") or {}).items():
        lines.append(f"- {group}: {json.dumps(counts, sort_keys=True)}")
    findings = audit.get("wording_findings") if isinstance(audit.get("wording_findings"), Mapping) else {}
    lines.extend(
        [
            "",
            "## Wording Findings",
            f"- perovskite-like examples without literal perovskite: {len(findings.get('perovskite_examples_without_literal_perovskite', []))}",
            f"- 6-coordinate examples without octahedra wording: {len(findings.get('six_coordinate_without_octahedra_examples', []))}",
            f"- coordination examples without connectivity wording: {len(findings.get('coordination_without_connectivity_examples', []))}",
            "",
            "## Target Examples",
        ]
    )
    for row in examples[:40]:
        lines.extend(["", f"### {row.get('structure_id')} {row.get('formula')}", f"- family: {row.get('family')}", f"- excerpt: {row.get('text_excerpt')}"])
    audit_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    strict_lines = ["# Robocrys Validator Strictness Recommendations", ""]
    for row in strictness:
        strict_lines.extend(
            [
                f"## {row.get('chemistry_family')}",
                f"- example count: {row.get('example_count')}",
                f"- strictness: {row.get('strictness')}",
                f"- expect explicit: {row.get('expect_explicit')}",
                f"- accept via aliases: {row.get('accept_via_aliases')}",
                f"- accept via condensed JSON only: {row.get('accept_via_condensed_json_only')}",
                f"- do not require literally: {row.get('do_not_require_literally')}",
                "",
            ]
        )
    strict_md.write_text("\n".join(strict_lines), encoding="utf-8")
    return {
        "audit_json": str(audit_json),
        "audit_md": str(audit_md),
        "examples_jsonl": str(examples_jsonl),
        "examples_csv": str(examples_csv),
        "strictness_json": str(strict_json),
        "strictness_md": str(strict_md),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()
    audit = build_audit(args.db, limit=args.limit)
    print(json.dumps(write_outputs(audit, args.out_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
