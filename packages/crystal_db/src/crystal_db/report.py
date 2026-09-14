import csv
import json
import os
from typing import Any, Dict, List, Optional

from .audit_log import AuditLogger
from .crystalcard import build_crystalcard
from .db import connect, init_db
from .novelty import run_novelty
from .utils import now_iso_utc, parse_cif_text, parse_formula


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _read_cif(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _elements_csv_from_formula(formula: Optional[str]) -> str:
    counts = parse_formula(formula)
    elements = sorted(counts.keys())
    if not elements:
        return ""
    return "," + ",".join(elements) + ","


def _elements_from_formula(formula: Optional[str]) -> List[str]:
    counts = parse_formula(formula)
    return sorted(counts.keys())


def _redact_structures(structures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    redacted: List[Dict[str, Any]] = []
    for item in structures:
        provenance = item.get("provenance", {})
        allow_export = provenance.get("allow_export")
        if allow_export in (0, False):
            redacted.append(
                {
                    "structure_id": item.get("structure_id"),
                    "provenance": provenance,
                    "redacted": True,
                }
            )
        else:
            redacted.append(item)
    return redacted


def _property_comparators(
    conn,
    candidate_meta: Dict[str, Any],
    elements_csv: str,
    limit: int = 3,
) -> Dict[str, Any]:
    target_value = None
    target_key = None
    for key in ("band_gap_eV", "predicted_band_gap_eV", "target_band_gap_eV"):
        if key in candidate_meta:
            target_value = candidate_meta.get(key)
            target_key = key
            break

    if target_value is None:
        return {
            "band_gap_eV": {
                "status": "missing_candidate_property",
                "reason": "candidate missing band_gap_eV",
            }
        }

    rows = conn.execute(
        "SELECT m.structure_id, m.formula, m.elements_csv, m.band_gap_eV, "
        "p.source, p.source_id, p.retrieved_at, p.allow_export "
        "FROM metadata m "
        "JOIN provenance p ON p.structure_id = m.structure_id "
        "WHERE m.band_gap_eV IS NOT NULL AND m.elements_csv = ?",
        (elements_csv,),
    ).fetchall()

    if not rows:
        return {
            "band_gap_eV": {
                "status": "no_db_matches",
                "target": target_value,
                "target_key": target_key,
                "reason": "no band_gap_eV data for same chemsys",
            }
        }

    comparators: List[Dict[str, Any]] = []
    for row in rows:
        delta = abs(float(row["band_gap_eV"]) - float(target_value))
        comparators.append(
            {
                "structure_id": row["structure_id"],
                "distance": delta,
                "provenance": {
                    "source": row["source"],
                    "source_id": row["source_id"],
                    "retrieved_at": row["retrieved_at"],
                    "allow_export": row["allow_export"],
                },
                "metadata": {
                    "formula": row["formula"],
                    "elements": _elements_from_formula(row["formula"]),
                    "band_gap_eV": row["band_gap_eV"],
                },
            }
        )

    comparators.sort(key=lambda item: (item["distance"], item["structure_id"]))
    comparators = comparators[: max(1, limit)]

    return {
        "band_gap_eV": {
            "status": "ok",
            "target": target_value,
            "target_key": target_key,
            "comparators": comparators,
        }
    }


def _write_csv(path: str, headers: List[str], rows: List[List[Any]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def _md_table(headers: List[str], rows: List[List[Any]]) -> List[str]:
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join([str(cell) if cell is not None else "" for cell in row]) + " |")
    return lines


def generate_report(
    *,
    db_path: Optional[str],
    run_id: str,
    out_dir: str,
    k: int = 5,
    threshold: float = 25.0,
    include_csv: bool = True,
    crystalcard_engine: str = "baseline",
) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)

    conn = connect(db_path)
    init_db(conn)

    run_row = conn.execute(
        "SELECT run_id, created_at, run_name, config_json FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run_row is None:
        conn.close()
        return {"error": "run_not_found", "run_id": run_id}

    candidates_rows = conn.execute(
        "SELECT candidate_id, input_path, input_hash, source, created_at, meta_json "
        "FROM candidates WHERE run_id = ? ORDER BY candidate_id",
        (run_id,),
    ).fetchall()

    results_rows = conn.execute(
        "SELECT candidate_id, novelty_json, neighbors_json, property_comps_json, created_at "
        "FROM candidate_results WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    results_map = {row["candidate_id"]: row for row in results_rows}

    logger = AuditLogger(
        db_path,
        run_row["run_name"],
        {"mode": "report", "threshold": threshold, "k": k},
        defer_init=True,
        run_id=run_id,
        create_run=False,
    )

    candidates_output: List[Dict[str, Any]] = []
    candidate_results: Dict[str, Any] = {}
    neighbor_cards_cache: Dict[str, Any] = {}

    for row in candidates_rows:
        candidate_id = row["candidate_id"]
        input_path = row["input_path"]
        meta = json.loads(row["meta_json"]) if row["meta_json"] else {}

        cif_text = _read_cif(input_path) if input_path else ""
        parsed = parse_cif_text(cif_text)
        formula = parsed.get("formula")
        elements = _elements_from_formula(formula)
        elements_csv = _elements_csv_from_formula(formula)

        candidate_card = build_crystalcard(
            cif_text=cif_text,
            db_path=db_path,
            engine=crystalcard_engine,
            store=False,
        )

        logger.log_tool_call(
            "crystalcard_candidate",
            {"candidate_id": candidate_id, "engine": crystalcard_engine},
            candidate_card,
            now_iso_utc(),
            now_iso_utc(),
            "ok",
            None,
        )

        candidate_info = {
            "candidate_id": candidate_id,
            "source": row["source"],
            "input_path": input_path,
            "input_hash": row["input_hash"],
            "created_at": row["created_at"],
            "formula": formula,
            "elements": elements,
            "space_group": parsed.get("space_group"),
            "volume": parsed.get("volume"),
            "meta": meta,
        }
        candidates_output.append(candidate_info)

        stored = results_map.get(candidate_id)
        if stored:
            novelty = json.loads(stored["novelty_json"]) if stored["novelty_json"] else None
            neighbors = json.loads(stored["neighbors_json"]) if stored["neighbors_json"] else []
            property_comps = json.loads(stored["property_comps_json"]) if stored["property_comps_json"] else {}
        else:
            novelty = run_novelty(
                cif_text=cif_text,
                db_path=db_path,
                threshold=threshold,
                k=k,
                run_id=run_id,
            )
            neighbors = novelty.get("neighbors", [])

            property_comps = _property_comparators(conn, meta, elements_csv, limit=3)
            logger.log_tool_call(
                "property_comparators",
                {
                    "candidate_id": candidate_id,
                    "elements_csv": elements_csv,
                    "properties": list(property_comps.keys()),
                },
                property_comps,
                now_iso_utc(),
                now_iso_utc(),
                "ok",
                None,
            )

            conn.execute(
                "INSERT OR REPLACE INTO candidate_results "
                "(run_id, candidate_id, novelty_json, neighbors_json, property_comps_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    candidate_id,
                    _json_dumps(novelty),
                    _json_dumps(neighbors),
                    _json_dumps(property_comps),
                    now_iso_utc(),
                ),
            )
            conn.commit()

        redacted_neighbors = _redact_structures(neighbors or [])
        neighbor_cards: Dict[str, Any] = {}
        for neighbor in redacted_neighbors:
            neighbor_id = neighbor.get("structure_id")
            if neighbor.get("redacted") or not neighbor_id:
                neighbor_cards[neighbor_id] = {"status": "redacted"}
                continue
            if neighbor_id in neighbor_cards_cache:
                neighbor_cards[neighbor_id] = neighbor_cards_cache[neighbor_id]
                continue
            card = build_crystalcard(
                structure_id=neighbor_id,
                db_path=db_path,
                engine=crystalcard_engine,
                store=True,
            )
            neighbor_cards_cache[neighbor_id] = card
            neighbor_cards[neighbor_id] = card
            logger.log_tool_call(
                "crystalcard_neighbor",
                {"structure_id": neighbor_id, "engine": crystalcard_engine},
                card,
                now_iso_utc(),
                now_iso_utc(),
                "ok",
                None,
            )
        redacted_comps = dict(property_comps)
        if "band_gap_eV" in redacted_comps and redacted_comps["band_gap_eV"].get("comparators"):
            redacted_comps["band_gap_eV"]["comparators"] = _redact_structures(
                redacted_comps["band_gap_eV"]["comparators"]
            )

        candidate_results[candidate_id] = {
            "novelty": novelty,
            "neighbors": redacted_neighbors,
            "property_comps": redacted_comps,
            "crystalcard": candidate_card,
            "neighbor_crystalcards": neighbor_cards,
        }

    conn.close()

    bundle = {
        "run": {
            "run_id": run_row["run_id"],
            "created_at": run_row["created_at"],
            "run_name": run_row["run_name"],
            "config": json.loads(run_row["config_json"]),
        },
        "candidates": candidates_output,
        "results": candidate_results,
    }

    bundle_path = os.path.join(out_dir, "run_bundle.json")
    with open(bundle_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)

    md_lines: List[str] = []
    md_lines.append("# Crystal-DB Phase 4 Report")
    md_lines.append("")
    md_lines.append(f"Run ID: {run_row['run_id']}")
    md_lines.append(f"Run Name: {run_row['run_name']}")
    md_lines.append(f"Created At: {run_row['created_at']}")
    md_lines.append("")

    candidate_rows: List[List[Any]] = []
    for candidate in candidates_output:
        meta = candidate.get("meta", {})
        candidate_rows.append(
            [
                candidate["candidate_id"],
                candidate.get("source"),
                candidate.get("formula"),
                ",".join(candidate.get("elements") or []),
                meta.get("predicted_energy", meta.get("energy")),
                meta.get("band_gap_eV", meta.get("predicted_band_gap_eV")),
            ]
        )

    md_lines.append("## Candidate Summary")
    md_lines.extend(_md_table([
        "candidate_id",
        "source",
        "formula",
        "elements",
        "predicted_energy",
        "band_gap_eV",
    ], candidate_rows))
    md_lines.append("")

    for candidate in candidates_output:
        cid = candidate["candidate_id"]
        result = candidate_results.get(cid, {})
        novelty = result.get("novelty", {}) if result else {}

        md_lines.append(f"## Candidate {cid}")
        md_lines.append("")
        md_lines.append(f"Source: {candidate.get('source')}")
        md_lines.append(f"Input Path: {candidate.get('input_path')}")
        md_lines.append(f"Formula: {candidate.get('formula')}")
        md_lines.append(f"Elements: {', '.join(candidate.get('elements') or [])}")
        md_lines.append("")

        is_novel = novelty.get("is_novel")
        best_match = novelty.get("best_match_structure_id")
        best_distance = novelty.get("best_distance")
        novelty_label = "novel" if is_novel else "rediscovered"
        md_lines.append(f"Novelty: {novelty_label}")
        md_lines.append(f"Best Match: {best_match}")
        md_lines.append(f"Best Distance: {best_distance}")
        md_lines.append(f"Threshold: {novelty.get('threshold')}")
        md_lines.append("")

        neighbors = result.get("neighbors") or []
        card = result.get("crystalcard") or {}
        md_lines.append("CrystalCard (baseline):")
        if isinstance(card, dict):
            md_lines.append(f"Summary: {card.get('text_summary', '')}")
            motifs = card.get("motifs") or []
            if motifs:
                md_lines.append("Motifs: " + "; ".join(motifs))
        md_lines.append("")

        md_lines.append("Neighbors:")
        neighbor_rows = []
        for idx, neighbor in enumerate(neighbors, start=1):
            neighbor_rows.append(
                [
                    idx,
                    neighbor.get("structure_id"),
                    neighbor.get("distance"),
                    (neighbor.get("metadata") or {}).get("formula") if not neighbor.get("redacted") else "redacted",
                    (neighbor.get("provenance") or {}).get("source"),
                    (neighbor.get("provenance") or {}).get("allow_export"),
                ]
            )
        md_lines.extend(
            _md_table(
                ["rank", "structure_id", "distance", "formula", "source", "allow_export"],
                neighbor_rows,
            )
        )
        md_lines.append("")
        md_lines.append("Neighbor CrystalCards:")
        neighbor_card_rows = []
        neighbor_cards = result.get("neighbor_crystalcards") or {}
        for neighbor in neighbors:
            nid = neighbor.get("structure_id")
            neighbor_card = neighbor_cards.get(nid, {})
            summary = "redacted" if neighbor_card.get("status") == "redacted" else neighbor_card.get("text_summary", "")
            neighbor_card_rows.append([nid, summary])
        if neighbor_card_rows:
            md_lines.extend(_md_table(["structure_id", "summary"], neighbor_card_rows))
        md_lines.append("")

        property_comps = result.get("property_comps") or {}
        if "band_gap_eV" in property_comps:
            bg = property_comps["band_gap_eV"]
            md_lines.append("Property Comparators: band_gap_eV")
            md_lines.append(f"Status: {bg.get('status')}")
            if bg.get("status") == "ok":
                comp_rows = []
                for idx, comp in enumerate(bg.get("comparators", []), start=1):
                    comp_rows.append(
                        [
                            idx,
                            comp.get("structure_id"),
                            comp.get("distance"),
                            (comp.get("metadata") or {}).get("band_gap_eV") if not comp.get("redacted") else "redacted",
                            (comp.get("provenance") or {}).get("source"),
                        ]
                    )
                md_lines.extend(
                    _md_table(
                        ["rank", "structure_id", "|Δ|", "band_gap_eV", "source"],
                        comp_rows,
                    )
                )
            else:
                md_lines.append(f"Reason: {bg.get('reason')}")
            md_lines.append("")

    report_path = os.path.join(out_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    if include_csv:
        candidates_csv = os.path.join(out_dir, "candidates_summary.csv")
        _write_csv(
            candidates_csv,
            ["candidate_id", "source", "formula", "elements", "predicted_energy", "band_gap_eV"],
            candidate_rows,
        )

        neighbors_csv = os.path.join(out_dir, "neighbors_summary.csv")
        neighbor_rows_csv: List[List[Any]] = []
        for candidate in candidates_output:
            cid = candidate["candidate_id"]
            for idx, neighbor in enumerate(candidate_results.get(cid, {}).get("neighbors", []) or [], start=1):
                neighbor_rows_csv.append(
                    [
                        cid,
                        idx,
                        neighbor.get("structure_id"),
                        neighbor.get("distance"),
                        (neighbor.get("provenance") or {}).get("source"),
                        (neighbor.get("provenance") or {}).get("source_id"),
                        (neighbor.get("provenance") or {}).get("allow_export"),
                        neighbor.get("redacted", False),
                    ]
                )
        _write_csv(
            neighbors_csv,
            ["candidate_id", "rank", "structure_id", "distance", "source", "source_id", "allow_export", "redacted"],
            neighbor_rows_csv,
        )

    return {
        "out_dir": out_dir,
        "report_path": report_path,
        "bundle_path": bundle_path,
    }
