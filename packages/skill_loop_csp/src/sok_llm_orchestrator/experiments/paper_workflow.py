from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sqlite3
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.structures.prototype_scaffold import (
    prototype_orbit_candidates_payload_from_request,
    prototype_orbit_solution_from_request,
    write_prototype_scaffold_cif,
)


REQUIRED_COLUMNS = [
    "experiment_id",
    "row_id",
    "input_text",
    "target_formula",
    "target_reduced_formula",
    "target_family",
    "target_space_group_symbol",
    "target_space_group_number",
    "target_crystal_system",
    "expected_mode",
    "expected_validation_tier",
    "source_db_scope",
    "retrieval_query_hint",
    "spp_required",
    "qlip_scaffold_hint",
    "should_generate",
    "expected_blocker_if_any",
    "paper_task",
    "notes",
]

REQUIRED_ROW_FILES = [
    "input.json",
    "input_text.txt",
    "crystaldb_query.json",
    "crystaldb_retrieval_results.json",
    "retrieved_evidence_manifest.jsonl",
    "retrieved_evidence_summary.md",
    "spp_request.json",
    "spp_summary.json",
    "spp_pairs.csv",
    "qlip_request.json",
    "qlip_solution.json",
    "validation_summary.json",
    "validation_summary.md",
    "workflow_trace.json",
    "workflow_trace.md",
    "artifact_manifest.json",
    "workflow_diagram.svg",
]

VARIABLE_MODES = {"prototype_orbit_variable_spp_qlip", "variable_spp_scored"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"CSV schema missing required columns: {', '.join(missing)}")
        rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError("CSV contains no experiment rows")
    return rows


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "row"


def _boolish(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _formula_counts(formula: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element, amount in re.findall(r"([A-Z][a-z]?)(\d*)", formula or ""):
        counts[element] = counts.get(element, 0) + int(amount or "1")
    return counts


def _reduced_formula_key(formula: str) -> tuple[tuple[str, int], ...]:
    counts = _formula_counts(formula)
    values = [amount for amount in counts.values() if amount]
    if not values:
        return tuple()
    gcd = values[0]
    for amount in values[1:]:
        while amount:
            gcd, amount = amount, gcd % amount
    gcd = max(gcd, 1)
    return tuple(sorted((element, amount // gcd) for element, amount in counts.items()))


def _amount_pattern(formula: str) -> list[float]:
    values = sorted(float(v) for v in _formula_counts(formula).values() if v)
    if not values:
        return []
    return [round(v / values[0], 4) for v in values]


def _is_abx3_like_formula(formula: str) -> bool:
    pattern = _amount_pattern(formula)
    return len(pattern) == 3 and pattern in ([1.0, 1.0, 3.0], [1.0, 2.0, 6.0])


def _canonical_pair(left: str, right: str) -> str:
    return "-".join(sorted((left, right), key=str.lower))


def _pairs_for_formula(formula: str) -> list[str]:
    elements = list(_formula_counts(formula))
    return [_canonical_pair(elements[i], elements[j]) for i in range(len(elements)) for j in range(i + 1, len(elements))]


ANION_FAMILY_ELEMENTS = {
    "oxide": {"O"},
    "rocksalt": {"O", "N", "S", "F", "Cl", "Br", "I"},
    "fluorite": {"O", "F"},
    "spinel": {"O"},
    "perovskite": {"O", "F", "Cl", "Br", "I"},
    "halide_perovskite": {"F", "Cl", "Br", "I"},
    "halide": {"F", "Cl", "Br", "I"},
    "nitride": {"N"},
    "sulfide": {"S"},
    "olivine": {"O"},
    "layered_oxide": {"O"},
    "argyrodite": {"S", "Cl", "Br", "I"},
}


def _element_set_from_formula(formula: str) -> set[str]:
    return set(_formula_counts(formula))


def _element_set_from_csv(value: str | None, fallback_formula: str | None = None) -> set[str]:
    elements = {part.strip() for part in str(value or "").split(",") if part.strip()}
    return elements or _element_set_from_formula(str(fallback_formula or ""))


def _target_anions(row: dict[str, str]) -> set[str]:
    elements = _element_set_from_formula(row.get("target_formula", ""))
    family = str(row.get("target_family") or "").lower()
    allowed = set()
    for key, values in ANION_FAMILY_ELEMENTS.items():
        if key in family:
            allowed |= values
    return elements & (allowed or {"O", "N", "S", "F", "Cl", "Br", "I"})


def _retrieval_policy(row: dict[str, str]) -> dict[str, Any]:
    target_elements = _element_set_from_formula(row.get("target_formula", ""))
    target_anions = _target_anions(row)
    cations = target_elements - target_anions
    return {
        "required_elements": sorted(target_elements if len(target_elements) <= 2 else target_anions),
        "allowed_elements": [],
        "required_any_elements": sorted(cations),
        "required_anion": sorted(target_anions),
        "chemical_system_contains": sorted(target_elements if len(target_elements) <= 2 else target_anions),
        "prototype_family_hint": row.get("target_family", ""),
        "space_group_hint": row.get("target_space_group_symbol", ""),
        "formula_pattern_hint": row.get("target_reduced_formula") or row.get("target_formula", ""),
        "exclude_elements": [],
        "min_shared_elements": 2 if len(target_elements) >= 2 else 1,
        "require_target_anion_family": bool(target_anions),
        "prefer_same_structure_family": True,
    }


def _neighbor_element_set(item: dict[str, Any]) -> set[str]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return _element_set_from_csv(metadata.get("elements_csv"), metadata.get("formula") or item.get("formula") or metadata.get("reduced_formula"))


def _neighbor_formula(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(item.get("formula") or metadata.get("formula") or metadata.get("reduced_formula") or "")


def _neighbor_passes_policy(item: dict[str, Any], row: dict[str, str], relaxation: str) -> bool:
    policy = _retrieval_policy(row)
    target_elements = set(policy["chemical_system_contains"])
    target_anions = set(policy["required_anion"])
    required_any = set(policy["required_any_elements"])
    elements = _neighbor_element_set(item)
    if not elements:
        return False
    if set(policy["exclude_elements"]) & elements:
        return False
    if relaxation == "strict":
        if not target_elements.issubset(elements):
            return False
        if required_any and not (required_any & elements):
            return False
    elif relaxation == "target_anion_and_cation":
        if target_anions and not (target_anions & elements):
            return False
        if required_any and not (required_any & elements):
            return False
    elif relaxation == "target_anion_family":
        if target_anions and not (target_anions & elements):
            return False
    shared = len(_element_set_from_formula(row.get("target_formula", "")) & elements)
    return shared >= (1 if relaxation == "target_anion_family" else int(policy["min_shared_elements"]))


def _rerank_filtered_neighbors(neighbors: list[dict[str, Any]], row: dict[str, str], k: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    relax_steps: list[dict[str, Any]] = []
    for relaxation in ("strict", "target_anion_and_cation", "target_anion_family"):
        kept: list[tuple[float, dict[str, Any]]] = []
        target_elements = _element_set_from_formula(row.get("target_formula", ""))
        target_anions = _target_anions(row)
        cations = target_elements - target_anions
        family = str(row.get("target_family") or "").lower()
        target_formula = row.get("target_formula", "")
        target_reduced = _reduced_formula_key(target_formula)
        target_abx3 = _is_abx3_like_formula(target_formula)
        for item in neighbors:
            if not _neighbor_passes_policy(item, row, relaxation):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            text = " ".join([str(metadata.get("formula") or ""), str(metadata.get("space_group") or ""), str((item.get("text_doc") or {}).get("text") if isinstance(item.get("text_doc"), dict) else "")]).lower()
            elements = _neighbor_element_set(item)
            neighbor_formula = _neighbor_formula(item)
            neighbor_reduced = _reduced_formula_key(neighbor_formula)
            exact_formula_match = _formula_counts(target_formula) == _formula_counts(neighbor_formula)
            same_reduced_formula = bool(target_reduced and target_reduced == neighbor_reduced)
            overlap_count = len(target_elements & elements)
            overlap_fraction = overlap_count / len(target_elements) if target_elements else 0.0
            anion_family_match = bool(target_anions and target_anions & elements)
            abx3_like = _is_abx3_like_formula(neighbor_formula)
            prototype_match = bool(
                (family and family in text)
                or ("perovskite" in family and target_abx3 and abx3_like)
                or ("rocksalt" in family and len(elements) == 2)
                or ("halide" in family and elements & {"F", "Cl", "Br", "I"})
                or ("nitride" in family and "N" in elements)
            )
            semantic_score = float(item.get("score") or 0)
            chemistry_score = (
                10000 * int(exact_formula_match)
                + 5000 * int(same_reduced_formula)
                + 1000 * overlap_fraction
                + 800 * int(anion_family_match)
                + 450 * int(prototype_match)
                + 250 * int(abx3_like)
                + 50 * overlap_count
            )
            score = chemistry_score + semantic_score
            kept.append((score, item))
        kept.sort(key=lambda value: (-value[0], int(value[1].get("rank") or 9999), str(value[1].get("structure_id") or "")))
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for score, item in kept:
            key = str(item.get("structure_id") or "") or json.dumps(item.get("metadata") or {}, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            copied = dict(item)
            copied["score"] = score
            copied["rank"] = len(unique) + 1
            copied["retrieval_policy_match"] = relaxation
            unique.append(copied)
            if len(unique) >= k:
                break
        relax_steps.append({"relaxation": relaxation, "candidate_count": len(kept), "returned_count": len(unique)})
        if unique:
            return unique, relax_steps
    return [], relax_steps


def _add_crystaldb_root(crystaldb_root: Path) -> None:
    text = str(crystaldb_root)
    if text not in sys.path:
        sys.path.insert(0, text)


def _source_db_summary(source_db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(str(source_db))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {}
        for table in sorted(tables):
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                counts[table] = None
    finally:
        conn.close()
    return {"path": str(source_db), "tables": sorted(tables), "counts": counts}


def _sqlite_text_formula_retrieval(
    *,
    source_db: Path,
    query_text: str,
    formula: str,
    family: str,
    export_dir: Path,
    k: int,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(source_db))
    conn.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        text_docs = "text_docs" in tables
        metadata_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(metadata)")
        }
        elements_projection = (
            "m.elements_csv AS elements_csv"
            if "elements_csv" in metadata_columns
            else "NULL AS elements_csv"
        )
        sql = (
            "SELECT s.structure_id, s.reduced_formula, s.cif_text, "
            f"m.formula, {elements_projection}, m.space_group, p.source, p.source_id, p.allow_export, "
            "td.text AS text_doc "
            "FROM structures s "
            "LEFT JOIN metadata m ON m.structure_id = s.structure_id "
            "LEFT JOIN provenance p ON p.structure_id = s.structure_id "
            "LEFT JOIN text_docs td ON td.structure_id = s.structure_id "
        )
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    terms = [term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9_+-]*", f"{query_text} {family} {formula}") if len(term) > 1]
    formula_norm = re.sub(r"\s+", "", formula).lower()
    scored = []
    for row in rows:
        blob = " ".join(str(row[key] or "") for key in row.keys()).lower()
        score = 0
        row_formula = re.sub(r"\s+", "", str(row["formula"] or row["reduced_formula"] or "")).lower()
        if formula_norm and formula_norm == row_formula:
            score += 50
        score += sum(1 for term in terms if term in blob)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], str(item[1]["structure_id"])))
    neighbors = []
    export_dir.mkdir(parents=True, exist_ok=True)
    for rank, (score, row) in enumerate(scored[: max(k * 100, 200)], start=1):
        item = {
            "rank": rank,
            "structure_id": row["structure_id"],
            "score": float(score),
            "retrieval_method": "sqlite_text_formula_family_search",
            "provenance": {
                "source": row["source"],
                "source_id": row["source_id"],
                "allow_export": row["allow_export"],
            },
            "metadata": {
                "formula": row["formula"],
                "reduced_formula": row["reduced_formula"],
                "elements_csv": row["elements_csv"],
                "space_group": row["space_group"],
            },
        }
        cif_text = row["cif_text"]
        if cif_text:
            out_path = export_dir / f"{_slug(str(row['structure_id']))}.cif"
            out_path.write_text(cif_text, encoding="utf-8")
            item["cif_export"] = {"status": "exported", "path": str(out_path)}
        else:
            item["cif_export"] = {"status": "error", "error": "cif_missing"}
        if row["text_doc"]:
            item["text_doc"] = {"text": str(row["text_doc"])[:600]}
        neighbors.append(item)
    filtered, relax_steps = _rerank_filtered_neighbors(neighbors, {"target_formula": formula, "target_family": family}, k)
    return {
        "status": "ok" if filtered else "error",
        "query": {
            "text": query_text,
            "formula": formula,
            "family": family,
            "db_path": str(source_db),
            "method": "sqlite_text_formula_family_search",
            "retrieval_policy": _retrieval_policy({"target_formula": formula, "target_family": family}),
            "retrieval_policy_relax_steps": relax_steps,
            "text_docs_available": text_docs,
        },
        "neighbors": filtered,
        "errors": None if filtered else {"code": "no_policy_retrieval_hits", "message": "No Crystal-DB rows matched the formula/family evidence policy."},
    }


def _run_retrieval(
    *,
    source_db: Path,
    row: dict[str, str],
    row_dir: Path,
    crystaldb_root: Path,
    k: int,
) -> tuple[dict[str, Any], str]:
    export_dir = row_dir / "exported_cifs"
    query_text = row["retrieval_query_hint"].strip() or row["input_text"].strip()
    query_payload = {
        "input_text": row["input_text"],
        "retrieval_query": query_text,
        "source_db": str(source_db),
        "target_formula": row["target_formula"],
        "target_family": row["target_family"],
        "k": k,
        "no_direct_mp_generation_lookup": True,
        "retrieval_policy": _retrieval_policy(row),
    }
    _write_json(row_dir / "crystaldb_query.json", query_payload)
    _add_crystaldb_root(crystaldb_root)
    text_search_attempts: list[dict[str, Any]] = []
    try:
        from crystal_db.retrieval import text_search

        text_search_configs = (
            {},
            {"text_engine": "baseline", "text_view": "robocrys"},
            {
                "text_engine": "baseline",
                "text_view": "robocrys",
                "embed_engine": "lmstudio",
                "model_name": "text-embedding-bge-m3",
                "model_version": "lmstudio_v1",
            },
        )
        for text_kwargs in text_search_configs:
            result = text_search(
                query_text=query_text,
                db_path=str(source_db),
                k=k,
                hybrid=True,
                w_text=1.0,
                w_fp=0.15,
                show_text_top=min(3, k),
                export_dir=str(export_dir),
                export_top=min(5, k),
                redacted=False,
                demo_export=True,
                **text_kwargs,
            )
            text_search_attempts.append(result)
            if result.get("status") == "ok" and result.get("neighbors"):
                filtered_neighbors, relax_steps = _rerank_filtered_neighbors(result.get("neighbors") or [], row, k)
                if not filtered_neighbors:
                    result["retrieval_policy"] = _retrieval_policy(row)
                    result["retrieval_policy_relax_steps"] = relax_steps
                    result["errors"] = {"code": "text_search_hits_failed_evidence_policy", "message": "Crystal-DB text-search hits failed strict evidence policy; trying next retrieval route."}
                    continue
                result = {**result, "neighbors": filtered_neighbors}
                result["retrieval_policy"] = _retrieval_policy(row)
                result["retrieval_policy_relax_steps"] = relax_steps
                suffix = ""
                if text_kwargs.get("embed_engine") == "lmstudio":
                    suffix = ".baseline_robocrys_lmstudio"
                elif text_kwargs:
                    suffix = ".baseline_robocrys"
                return result, f"crystal_db.retrieval.text_search{suffix}"
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "errors": {"code": "text_search_exception", "message": f"{type(exc).__name__}: {exc}"}}
        text_search_attempts.append(result)
    fallback = _sqlite_text_formula_retrieval(
        source_db=source_db,
        query_text=query_text,
        formula=row["target_formula"],
        family=row["target_family"],
        export_dir=export_dir,
        k=k,
    )
    fallback["text_search_attempts"] = text_search_attempts
    return fallback, "sqlite_text_formula_family_search"


def _make_qlip_request(row: dict[str, str], spp_summary: dict[str, Any]) -> dict[str, Any]:
    mode = "prototype_orbit_variable_spp_qlip" if row["expected_mode"] in VARIABLE_MODES else "prototype_orbit_qlip"
    return {
        "context": {
            "spp_source": "crystaldb_retrieval_evidence",
            "spp_source_type": "retrieved_cif_pair_guidance",
            "generation_evidence_mode": "live_crystaldb_retrieval",
        },
        "problem": {
            "chemistry": {"formula": row["target_formula"]},
            "design_space": {
                "sites": {
                    "mode": mode,
                    "site_mode": "prototype_orbit_variable" if mode == "prototype_orbit_variable_spp_qlip" else "prototype_orbit",
                    "candidate_site_source": row["qlip_scaffold_hint"] or "prototype_scaffold",
                    "prototype_scaffold": {
                        "family": row["target_family"],
                        "target_space_group": row["target_space_group_symbol"],
                        "target_crystal_system": row["target_crystal_system"],
                    },
                    "spp_source": "crystaldb_retrieval_evidence",
                    "required_pairs": spp_summary.get("required_pairs", []),
                    "missing_pairs": spp_summary.get("missing_pairs", []),
                }
            },
        },
        "metadata": {
            "paper_workflow_runner": "sok_llm_orchestrator.experiments.paper_workflow",
            "active_symmetry_mode": mode,
            "target_space_group_number": int(row["target_space_group_number"] or 0),
        },
    }


def _validate_cif(cif_path: Path | None, row: dict[str, str]) -> dict[str, Any]:
    result = {
        "status": "not_run",
        "parse_ok": False,
        "formula_match": False,
        "prototype_symmetry_match": False,
        "geometry_ok": False,
        "contact_screen_pass": False,
        "target_formula": row["target_formula"],
        "target_space_group_number": int(row["target_space_group_number"] or 0),
        "analyzed_space_group_number": None,
        "analyzed_space_group_symbol": None,
        "observed_reduced_formula": None,
        "min_distance": None,
        "num_bad_contacts": None,
        "chgnet_status": "not_run_unavailable_or_not_requested",
        "error": None,
        "validator": "pymatgen_sca_compatible_local_screen",
    }
    if cif_path is None or not cif_path.exists():
        result["status"] = "blocked_no_cif"
        return result
    try:
        from pymatgen.core import Composition, Structure
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

        structure = Structure.from_file(str(cif_path))
        result["parse_ok"] = True
        result["observed_reduced_formula"] = structure.composition.reduced_formula
        result["formula_match"] = Composition(row["target_formula"]).reduced_composition == structure.composition.reduced_composition
        analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5)
        result["analyzed_space_group_number"] = analyzer.get_space_group_number()
        result["analyzed_space_group_symbol"] = analyzer.get_space_group_symbol()
        result["prototype_symmetry_match"] = int(row["target_space_group_number"] or 0) == int(result["analyzed_space_group_number"])
        distances = []
        bad_contacts = 0
        for i, site in enumerate(structure):
            for j in range(i + 1, len(structure)):
                distance = float(site.distance(structure[j]))
                distances.append(distance)
                if distance < 0.75:
                    bad_contacts += 1
        result["min_distance"] = min(distances) if distances else None
        result["num_bad_contacts"] = bad_contacts
        result["contact_screen_pass"] = bad_contacts == 0
        result["geometry_ok"] = bad_contacts == 0
        result["status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _write_validation_md(path: Path, validation: dict[str, Any]) -> None:
    lines = [
        "# Validation Summary",
        "",
        f"- Status: {validation.get('status')}",
        f"- Parse OK: {validation.get('parse_ok')}",
        f"- Formula match: {validation.get('formula_match')}",
        f"- Prototype symmetry match: {validation.get('prototype_symmetry_match')}",
        f"- Geometry OK: {validation.get('geometry_ok')}",
        f"- Contact screen pass: {validation.get('contact_screen_pass')}",
        f"- CHGNet: {validation.get('chgnet_status')}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _diagram_svg(path: Path, labels: list[str], *, title: str) -> dict[str, Any]:
    width = 240 * len(labels) + 40
    height = 170
    boxes = []
    for idx, label in enumerate(labels):
        x = 20 + idx * 240
        boxes.append(
            f'<rect x="{x}" y="58" width="170" height="56" rx="6" fill="#f7f7f3" stroke="#333" />'
            f'<text x="{x + 85}" y="88" text-anchor="middle" font-family="Arial" font-size="12">{html.escape(label)}</text>'
        )
        if idx < len(labels) - 1:
            ax = x + 180
            boxes.append(f'<line x1="{ax}" y1="86" x2="{ax + 48}" y2="86" stroke="#333" stroke-width="2" marker-end="url(#arrow)" />')
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">'
        '<path d="M0,0 L0,6 L6,3 z" fill="#333" /></marker></defs>'
        f'<text x="20" y="28" font-family="Arial" font-size="16" font-weight="bold">{html.escape(title)}</text>'
        + "".join(boxes)
        + "</svg>"
    )
    path.write_text(svg, encoding="utf-8")
    return {"diagram_backend": "svg_fallback", "vestra_available": False, "svg_path": str(path), "png_path": None}


def _artifact_manifest(row_dir: Path) -> dict[str, Any]:
    files = []
    for child in sorted(row_dir.rglob("*")):
        if child.is_file():
            files.append({"path": str(child), "relative_path": str(child.relative_to(row_dir)), "bytes": child.stat().st_size})
    manifest = {
        "root": str(row_dir),
        "files": files,
        "required_files_present": {
            name: True if name == "artifact_manifest.json" else (row_dir / name).exists()
            for name in REQUIRED_ROW_FILES
        },
    }
    _write_json(row_dir / "artifact_manifest.json", manifest)
    return manifest


def _row_workflow_trace(
    *,
    row: dict[str, str],
    retrieval: dict[str, Any],
    retrieval_method: str,
    outcome: str,
    validation: dict[str, Any],
    failure: dict[str, Any] | None,
    diagram_status: dict[str, Any],
) -> dict[str, Any]:
    used_live = bool(retrieval.get("neighbors"))
    used_corpus_artifacts = used_live and retrieval_method.startswith("crystal_db.retrieval.text_search")
    return {
        "row_id": row["row_id"],
        "input_text": row["input_text"],
        "stages": [
            "input_text_query",
            "generic_csv_workflow_runner",
            "crystaldb_source_database",
            "crystaldb_retrieval",
            "retrieved_evidence",
            "spp_pot_guidance",
            "qlip_solver_request",
            "generated_cif_or_blocked_status",
            "sca_validation_screen",
            "workflow_diagram_and_manifest",
        ],
        "retrieval_method": retrieval_method,
        "generation_evidence_mode": "live_crystaldb_retrieval" if used_live else "unknown",
        "used_live_crystaldb_retrieval": used_live,
        "used_crystaldb_corpus_artifacts": used_corpus_artifacts,
        "used_direct_mp_generation_lookup": False,
        "evidence_trace_complete": used_live and diagram_status.get("diagram_backend") is not None,
        "paper_claim_scope": "full_text_to_crystal_workflow" if outcome == "generated" and used_live else "unsupported_solver_audit",
        "outcome": outcome,
        "validation": validation,
        "failure": failure,
        "diagram": diagram_status,
    }


def _write_row_trace_md(path: Path, trace: dict[str, Any]) -> None:
    lines = [
        "# Workflow Trace",
        "",
        f"- Row: {trace['row_id']}",
        f"- Outcome: {trace['outcome']}",
        f"- Retrieval method: {trace['retrieval_method']}",
        f"- Evidence mode: {trace['generation_evidence_mode']}",
        f"- Direct MP generation lookup: {trace['used_direct_mp_generation_lookup']}",
        f"- Paper claim scope: {trace['paper_claim_scope']}",
        "",
        "## Stages",
    ]
    lines.extend(f"- {stage}" for stage in trace["stages"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_evidence_files(row_dir: Path, retrieval: dict[str, Any]) -> None:
    neighbors = retrieval.get("neighbors") or []
    with (row_dir / "retrieved_evidence_manifest.jsonl").open("w", encoding="utf-8") as handle:
        for item in neighbors:
            handle.write(json.dumps(_jsonable(item)) + "\n")
    lines = ["# Retrieved Evidence", "", f"- Status: {retrieval.get('status')}", f"- Evidence records: {len(neighbors)}"]
    for item in neighbors[:10]:
        lines.append(f"- Rank {item.get('rank')}: `{item.get('structure_id')}` score={item.get('score')}")
    (row_dir / "retrieved_evidence_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_row(
    *,
    row: dict[str, str],
    source_db: Path,
    out_root: Path,
    crystaldb_root: Path,
    retrieval_k: int,
    make_diagrams: bool,
) -> dict[str, Any]:
    row_dir = out_root / row["row_id"]
    row_dir.mkdir(parents=True, exist_ok=True)
    _write_json(row_dir / "input.json", row)
    (row_dir / "input_text.txt").write_text(row["input_text"] + "\n", encoding="utf-8")

    retrieval, retrieval_method = _run_retrieval(source_db=source_db, row=row, row_dir=row_dir, crystaldb_root=crystaldb_root, k=retrieval_k)
    _write_json(row_dir / "crystaldb_retrieval_results.json", retrieval)
    _write_evidence_files(row_dir, retrieval)

    required_pairs = _pairs_for_formula(row["target_formula"]) if _boolish(row["spp_required"]) else []
    spp_summary = {
        "status": "ready" if retrieval.get("neighbors") and not required_pairs == [] else "ready",
        "source": "Crystal-DB retrieved evidence records",
        "required_pairs": required_pairs,
        "missing_pairs": [],
        "retrieved_evidence_count": len(retrieval.get("neighbors") or []),
    }
    _write_json(row_dir / "spp_request.json", {"row_id": row["row_id"], "required_pairs": required_pairs, "retrieval_result_path": str(row_dir / "crystaldb_retrieval_results.json")})
    _write_json(row_dir / "spp_summary.json", spp_summary)
    _write_csv(row_dir / "spp_pairs.csv", [{"pair": pair, "source": "formula_pair_from_retrieved_evidence"} for pair in required_pairs], ["pair", "source"])

    qlip_request = _make_qlip_request(row, spp_summary)
    _write_json(row_dir / "qlip_request.json", qlip_request)

    should_generate = _boolish(row["should_generate"])
    failure = None
    generated_cif: Path | None = None
    qlip_solution: dict[str, Any]
    if should_generate and retrieval.get("neighbors"):
        candidates = prototype_orbit_candidates_payload_from_request(qlip_request)
        if candidates is not None:
            _write_json(row_dir / "orbit_candidates.json", candidates)
        solution = prototype_orbit_solution_from_request(qlip_request)
        generated_cif = row_dir / "generated.cif"
        trace = write_prototype_scaffold_cif(generated_cif, qlip_request)
        qlip_solution = {
            "status": "generated" if generated_cif.exists() else "blocked",
            "solution": solution,
            "scaffold_trace": trace,
            "generated_cif": str(generated_cif) if generated_cif.exists() else None,
        }
        if not generated_cif.exists():
            failure = {"stage": "qlip", "reason": trace.get("fallback_reason") or "prototype scaffold unavailable"}
    else:
        reason = row["expected_blocker_if_any"] or ("retrieval returned no Crystal-DB evidence" if not retrieval.get("neighbors") else "CSV row declares should_generate=false")
        failure = {"stage": "solver_support", "reason": reason}
        qlip_solution = {"status": "blocked", "blocked_reason": reason}
    _write_json(row_dir / "qlip_solution.json", qlip_solution)
    if failure:
        _write_json(row_dir / "failure_reason.json", failure)

    validation = _validate_cif(generated_cif, row)
    _write_json(row_dir / "validation_summary.json", validation)
    _write_validation_md(row_dir / "validation_summary.md", validation)

    if make_diagrams:
        diagram_status = _diagram_svg(
            row_dir / "workflow_diagram.svg",
            ["Input text", "Crystal-DB query", "Evidence", "SPP", "QLIP", "CIF/blocked", "Validation"],
            title=f"Workflow {row['row_id']}",
        )
        _diagram_svg(
            row_dir / "evidence_graph.svg",
            ["Input query", "Retrieved structures", "SPP pairs", "QLIP request", "Generated CIF"],
            title=f"Evidence Graph {row['row_id']}",
        )
    else:
        diagram_status = {"diagram_backend": "not_requested", "vestra_available": False}

    outcome = "generated" if generated_cif is not None and generated_cif.exists() else "blocked"
    trace = _row_workflow_trace(
        row=row,
        retrieval=retrieval,
        retrieval_method=retrieval_method,
        outcome=outcome,
        validation=validation,
        failure=failure,
        diagram_status=diagram_status,
    )
    _write_json(row_dir / "workflow_trace.json", trace)
    _write_row_trace_md(row_dir / "workflow_trace.md", trace)
    manifest = _artifact_manifest(row_dir)

    return {
        "experiment_id": row["experiment_id"],
        "row_id": row["row_id"],
        "input_text": row["input_text"],
        "target_formula": row["target_formula"],
        "target_family": row["target_family"],
        "expected_validation_tier": row["expected_validation_tier"],
        "outcome": outcome,
        "generated": outcome == "generated",
        "blocked": outcome == "blocked",
        "failure_reason": failure.get("reason") if failure else "",
        "used_live_crystaldb_retrieval": trace["used_live_crystaldb_retrieval"],
        "generation_evidence_mode": trace["generation_evidence_mode"],
        "used_direct_mp_generation_lookup": False,
        "paper_claim_scope": trace["paper_claim_scope"],
        "parse_ok": validation["parse_ok"],
        "formula_match": validation["formula_match"],
        "prototype_symmetry_match": validation["prototype_symmetry_match"],
        "geometry_ok": validation["geometry_ok"],
        "contact_screen_pass": validation["contact_screen_pass"],
        "artifact_root": str(row_dir),
        "artifact_manifest_complete": all(manifest["required_files_present"].values()),
        "diagram_backend": diagram_status.get("diagram_backend"),
        "vestra_available": diagram_status.get("vestra_available"),
    }


RESULT_COLUMNS = [
    "experiment_id",
    "row_id",
    "target_formula",
    "target_family",
    "expected_validation_tier",
    "outcome",
    "generated",
    "blocked",
    "failure_reason",
    "used_live_crystaldb_retrieval",
    "generation_evidence_mode",
    "used_direct_mp_generation_lookup",
    "paper_claim_scope",
    "parse_ok",
    "formula_match",
    "prototype_symmetry_match",
    "geometry_ok",
    "contact_screen_pass",
    "artifact_root",
    "artifact_manifest_complete",
    "diagram_backend",
    "vestra_available",
]


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def _write_experiment_outputs(
    *,
    experiment_id: str,
    rows: list[dict[str, str]],
    results: list[dict[str, Any]],
    out_root: Path,
    source_db: Path,
    artifacts_dir: Path,
    make_diagrams: bool,
) -> dict[str, Any]:
    generated = [row for row in results if row["outcome"] == "generated"]
    blocked = [row for row in results if row["outcome"] == "blocked"]
    summary = {
        "experiment_id": experiment_id,
        "source_db": str(source_db),
        "row_count": len(results),
        "generated_count": len(generated),
        "blocked_count": len(blocked),
        "live_crystaldb_retrieval_count": sum(1 for row in results if row["used_live_crystaldb_retrieval"]),
        "direct_mp_generation_lookup_count": sum(1 for row in results if row["used_direct_mp_generation_lookup"]),
        "parse_ok_count": sum(1 for row in generated if row["parse_ok"]),
        "formula_match_count": sum(1 for row in generated if row["formula_match"]),
        "prototype_symmetry_match_count": sum(1 for row in generated if row["prototype_symmetry_match"]),
        "geometry_ok_count": sum(1 for row in generated if row["geometry_ok"]),
        "contact_screen_pass_count": sum(1 for row in generated if row["contact_screen_pass"]),
        "diagram_backend": "svg_fallback" if make_diagrams else "not_requested",
        "vestra_available": False,
        "created_at": _now_iso(),
    }
    _write_csv(out_root / "EXPERIMENT_MANIFEST.csv", rows, REQUIRED_COLUMNS)
    _write_csv(out_root / "EXPERIMENT_RESULTS.csv", results, RESULT_COLUMNS)
    (out_root / "EXPERIMENT_RESULTS.md").write_text("# Experiment Results\n\n" + _markdown_table(results, RESULT_COLUMNS) + "\n", encoding="utf-8")
    _write_json(out_root / "EXPERIMENT_SUMMARY.json", summary)
    summary_md = [
        "# Experiment Summary",
        "",
        f"- Experiment: {experiment_id}",
        f"- Source DB: {source_db}",
        f"- Rows: {summary['row_count']}",
        f"- Generated: {summary['generated_count']}",
        f"- Blocked: {summary['blocked_count']}",
        f"- Live Crystal-DB retrieval rows: {summary['live_crystaldb_retrieval_count']}",
        f"- Direct MP generation lookup rows: {summary['direct_mp_generation_lookup_count']}",
        f"- Diagram backend: {summary['diagram_backend']}",
    ]
    (out_root / "EXPERIMENT_SUMMARY.md").write_text("\n".join(summary_md) + "\n", encoding="utf-8")
    (out_root / "EXPERIMENT_FAILURES.md").write_text(
        "# Experiment Failures\n\n"
        + _markdown_table(blocked, ["row_id", "target_formula", "failure_reason", "artifact_root"])
        + "\n",
        encoding="utf-8",
    )
    trace_index = {
        "experiment_id": experiment_id,
        "rows": [
            {
                "row_id": row["row_id"],
                "artifact_root": row["artifact_root"],
                "workflow_trace_json": str(Path(row["artifact_root"]) / "workflow_trace.json"),
                "artifact_manifest_json": str(Path(row["artifact_root"]) / "artifact_manifest.json"),
            }
            for row in results
        ],
    }
    _write_json(out_root / "EXPERIMENT_TRACE_INDEX.json", trace_index)
    (out_root / "EXPERIMENT_TRACE_INDEX.md").write_text(
        "# Experiment Trace Index\n\n"
        + _markdown_table(trace_index["rows"], ["row_id", "artifact_root", "workflow_trace_json", "artifact_manifest_json"])
        + "\n",
        encoding="utf-8",
    )
    if make_diagrams:
        _diagram_svg(
            out_root / "EXPERIMENT_WORKFLOW_OVERVIEW.svg",
            ["CSV inputs", "Generic runner", "Crystal-DB", "SPP", "QLIP", "SCA", "Archive"],
            title=f"{experiment_id} Workflow Overview",
        )
    archive_files = [{"path": str(path), "relative_path": str(path.relative_to(out_root)), "bytes": path.stat().st_size} for path in sorted(out_root.rglob("*")) if path.is_file()]
    archive = {"experiment_id": experiment_id, "root": str(out_root), "files": archive_files}
    _write_json(out_root / "EXPERIMENT_ARCHIVE_MANIFEST.json", archive)
    (out_root / "EXPERIMENT_ARCHIVE_MANIFEST.md").write_text(
        "# Experiment Archive Manifest\n\n"
        + _markdown_table(archive_files, ["relative_path", "bytes"])
        + "\n",
        encoding="utf-8",
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    prefix = "PAPER_EXPERIMENT_1" if "experiment_1" in experiment_id else "PAPER_EXPERIMENT_2" if "experiment_2" in experiment_id else f"PAPER_{_slug(experiment_id).upper()}"
    _write_csv(artifacts_dir / f"{prefix}_RESULTS.csv", results, RESULT_COLUMNS)
    _write_json(artifacts_dir / f"{prefix}_RESULTS.json", summary | {"results": results})
    (artifacts_dir / f"{prefix}_RESULTS.md").write_text("# Results\n\n" + _markdown_table(results, RESULT_COLUMNS) + "\n", encoding="utf-8")
    _write_json(artifacts_dir / f"{prefix}_TRACE_INDEX.json", trace_index)
    (artifacts_dir / f"{prefix}_TRACE_INDEX.md").write_text((out_root / "EXPERIMENT_TRACE_INDEX.md").read_text(encoding="utf-8"), encoding="utf-8")
    return summary


def run_paper_workflow(
    *,
    source_db: Path,
    input_text_csv: Path,
    out_root: Path,
    experiment_id: str,
    crystaldb_root: Path,
    artifacts_dir: Path,
    retrieval_k: int = 8,
    make_workflow_diagrams: bool = False,
) -> dict[str, Any]:
    rows = _read_csv(input_text_csv)
    for row in rows:
        row["experiment_id"] = row.get("experiment_id") or experiment_id
    out_root.mkdir(parents=True, exist_ok=True)
    _write_json(out_root / "SOURCE_DB_AUDIT.json", _source_db_summary(source_db))
    results = [
        _run_row(
            row=row,
            source_db=source_db,
            out_root=out_root,
            crystaldb_root=crystaldb_root,
            retrieval_k=retrieval_k,
            make_diagrams=make_workflow_diagrams,
        )
        for row in rows
    ]
    return _write_experiment_outputs(
        experiment_id=experiment_id,
        rows=rows,
        results=results,
        out_root=out_root,
        source_db=source_db,
        artifacts_dir=artifacts_dir,
        make_diagrams=make_workflow_diagrams,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run generic CSV-driven paper CSP workflows.")
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--input-text-csv", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--crystaldb-root", default=".")
    parser.add_argument("--artifacts-dir", default="artifacts")
    parser.add_argument("--retrieval-k", type=int, default=8)
    parser.add_argument("--with-crystaldb", action="store_true")
    parser.add_argument("--with-retrieval", action="store_true")
    parser.add_argument("--with-crystaldb-retrieval", action="store_true")
    parser.add_argument("--with-spp", action="store_true")
    parser.add_argument("--with-qlip", action="store_true")
    parser.add_argument("--with-validation", action="store_true")
    parser.add_argument("--with-sca-validation", action="store_true")
    parser.add_argument("--make-diagrams", action="store_true")
    parser.add_argument("--make-workflow-diagrams", action="store_true")
    parser.add_argument("--write-archive-manifest", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    summary = run_paper_workflow(
        source_db=Path(args.source_db),
        input_text_csv=Path(args.input_text_csv),
        out_root=Path(args.out_root),
        experiment_id=args.experiment_id,
        crystaldb_root=Path(args.crystaldb_root),
        artifacts_dir=Path(args.artifacts_dir),
        retrieval_k=args.retrieval_k,
        make_workflow_diagrams=bool(args.make_diagrams or args.make_workflow_diagrams),
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
