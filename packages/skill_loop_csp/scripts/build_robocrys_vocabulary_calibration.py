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
DEFAULT_CRYSTAL_DB = REPO_ROOT.parent / "Crystal-DB" / "data" / "phase6_mp_10k.db"
DEFAULT_OUT = REPO_ROOT / "test_workdir" / "paper_evidence_pack_v2" / "reports"
DEFAULT_CSV = REPO_ROOT / "challenge_queries_100.csv"


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


def _challenge_families(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return {row.get("chemistry_family", "") for row in csv.DictReader(handle) if row.get("chemistry_family")}


def _family_from_text(text: str) -> str:
    lower = text.lower()
    checks = [
        ("oxide_perovskite", ["perovskite", "tio6", "corner-sharing octahedra"]),
        ("oxide_spinel", ["spinel", "mgo4", "alo6"]),
        ("layered_oxide", ["layered", "sheets", "coo6"]),
        ("phosphate_olivine", ["olivine", "po4", "channels"]),
        ("sulfide_pyrite", ["pyrite", "s-s", "dumbbell"]),
        ("sulfide_chalcopyrite", ["chalcopyrite"]),
        ("layered_chalcogenide", ["molybdenite", "two-dimensional", "sheets"]),
        ("phosphate_silicate_framework", ["nasicon", "zro6", "sio4", "po4"]),
        ("halide_rocksalt", ["rocksalt"]),
        ("oxide_fluorite", ["fluorite"]),
        ("oxide_garnet", ["garnet"]),
        ("oxide_pyrochlore", ["pyrochlore"]),
    ]
    for family, terms in checks:
        if any(term in lower for term in terms):
            return family
    return "unknown"


def _recommended_strictness(family: str) -> str:
    if family in {"oxide_perovskite", "oxide_spinel", "phosphate_olivine", "sulfide_pyrite", "phosphate_silicate_framework"}:
        return "strict_motif_with_aliases"
    if family in {"layered_oxide", "layered_chalcogenide", "oxide_pyrochlore", "oxide_garnet"}:
        return "motif_and_dimensionality"
    if family == "unknown":
        return "query_terms_only"
    return "moderate_coordination_connectivity"


def load_robocrys_text_docs(db_path: Path, *, limit: int = 10000) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        columns = [row[1] for row in con.execute("PRAGMA table_info(text_docs)").fetchall()]
        if "text_view" in columns:
            query = (
                "SELECT structure_id, engine, text_view, status, text FROM text_docs "
                "WHERE engine='robocrys' AND text_view='robocrys' AND status='OK' LIMIT ?"
            )
        else:
            query = "SELECT structure_id, engine, '' AS text_view, status, text FROM text_docs WHERE engine='robocrys' AND status='OK' LIMIT ?"
        return [dict(row) for row in con.execute(query, (int(limit),)).fetchall()]
    finally:
        con.close()


def build_calibration(db_path: Path, csv_path: Path, *, limit: int = 10000) -> dict[str, Any]:
    from sok_llm_orchestrator.agentic.robocrys_intent_validator import extract_robocrys_vocabulary_features

    docs = load_robocrys_text_docs(db_path, limit=limit)
    family_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    examples: list[dict[str, Any]] = []
    global_counter: Counter[str] = Counter()
    for doc in docs:
        text = str(doc.get("text") or "")
        features = extract_robocrys_vocabulary_features(text)
        family = _family_from_text(text)
        for bucket in ["family_terms", "coordination_terms", "connectivity_terms", "dimensionality_terms", "bond_terms", "polyhedra_terms"]:
            global_counter.update(features.get(bucket, []))
        row = {
            "structure_id": doc.get("structure_id", ""),
            "family": family,
            "text_excerpt": text[:800],
            **features,
        }
        family_rows[family].append(row)
        if len(examples) < 500:
            examples.append(row)
    challenge_families = _challenge_families(csv_path)
    family_summary = []
    for family in sorted(challenge_families | set(family_rows)):
        rows = family_rows.get(family, [])
        counters = {name: Counter() for name in ["family_terms", "coordination_terms", "connectivity_terms", "dimensionality_terms", "polyhedra_terms"]}
        for row in rows:
            for name, counter in counters.items():
                counter.update(row.get(name, []))
        family_summary.append(
            {
                "chemistry_family": family,
                "example_count": len(rows),
                "top_family_terms": counters["family_terms"].most_common(20),
                "top_coordination_terms": counters["coordination_terms"].most_common(20),
                "top_connectivity_terms": counters["connectivity_terms"].most_common(20),
                "top_dimensionality_terms": counters["dimensionality_terms"].most_common(20),
                "top_polyhedra_terms": counters["polyhedra_terms"].most_common(20),
                "recommended_validator_strictness": _recommended_strictness(family),
            }
        )
    return {
        "schema_version": "robocrys_vocabulary_calibration.v1",
        "db_path": str(db_path),
        "csv_path": str(csv_path),
        "text_doc_count": len(docs),
        "challenge_family_count": len(challenge_families),
        "global_top_terms": global_counter.most_common(100),
        "family_summary": family_summary,
        "examples": examples,
    }


def write_calibration_outputs(calibration: Mapping[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "ROBOCRYS_VOCABULARY_CALIBRATION.json"
    csv_path = out_dir / "ROBOCRYS_VOCABULARY_CALIBRATION.csv"
    md_path = out_dir / "ROBOCRYS_VOCABULARY_CALIBRATION.md"
    jsonl_path = out_dir / "robocrys_calibration_examples.jsonl"
    examples_csv_path = out_dir / "robocrys_calibration_examples.csv"
    _write_json(json_path, {key: value for key, value in calibration.items() if key != "examples"})
    family_rows = list(calibration.get("family_summary", []))
    _write_csv(
        csv_path,
        family_rows,
        [
            "chemistry_family",
            "example_count",
            "top_family_terms",
            "top_coordination_terms",
            "top_connectivity_terms",
            "top_dimensionality_terms",
            "top_polyhedra_terms",
            "recommended_validator_strictness",
        ],
    )
    examples = list(calibration.get("examples", []))
    jsonl_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in examples) + ("\n" if examples else ""), encoding="utf-8")
    _write_csv(
        examples_csv_path,
        examples,
        [
            "structure_id",
            "family",
            "text_excerpt",
            "family_terms",
            "coordination_terms",
            "connectivity_terms",
            "dimensionality_terms",
            "bond_terms",
            "polyhedra_terms",
            "has_bond_length_language",
            "has_space_group_language",
        ],
    )
    lines = [
        "# Robocrys Vocabulary Calibration",
        "",
        f"- DB path: {calibration.get('db_path')}",
        f"- Robocrys text docs sampled: {calibration.get('text_doc_count')}",
        f"- Challenge families represented: {calibration.get('challenge_family_count')}",
        "",
        "## Family Summary",
    ]
    for row in family_rows:
        lines.extend(
            [
                "",
                f"### {row.get('chemistry_family')}",
                f"- examples: {row.get('example_count')}",
                f"- recommended strictness: {row.get('recommended_validator_strictness')}",
                f"- top coordination terms: {row.get('top_coordination_terms')}",
                f"- top connectivity terms: {row.get('top_connectivity_terms')}",
            ]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "md": str(md_path),
        "examples_jsonl": str(jsonl_path),
        "examples_csv": str(examples_csv_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_CRYSTAL_DB)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()
    calibration = build_calibration(args.db, args.csv, limit=args.limit)
    outputs = write_calibration_outputs(calibration, args.out_dir)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
