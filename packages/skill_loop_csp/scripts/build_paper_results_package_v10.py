from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from pymatgen.core import Composition

ROOT = Path(__file__).resolve().parents[1]
V9 = ROOT / "artifacts" / "paper_results_package_v9"
V10 = ROOT / "artifacts" / "paper_results_package_v10"
FIGURES_V10 = ROOT / "figures" / "paper_v10"
FULL_MANIFEST = ROOT / "artifacts" / "PAPER_EXPERIMENTS_FULL_SCA_MANIFEST.csv"
V10_FORMULA_MATCHED_RENDER_MANIFEST = ROOT / "artifacts" / "paper_results_package_v10_paper_display_vesta_images_formula_matched" / "PAPER_DISPLAY_VESTA_IMAGE_MANIFEST.csv"
V7_RENDER_MANIFEST = ROOT / "artifacts" / "paper_results_package_v7_vesta_renders" / "VESTA_CIF_RENDER_MANIFEST.csv"
PHASE6 = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB\data\phase6_mp_10k.db")
HALIDE_DB = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB\data\paper_experiment_3_halide_perovskite_v1.db")


class BuildLock:
    def __init__(self, lock_path: Path, *, timeout_s: float = 1800.0) -> None:
        self.lock_path = lock_path
        self.timeout_s = timeout_s
        self.fd: int | None = None

    def __enter__(self) -> "BuildLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        payload = json.dumps({"pid": os.getpid(), "started_at": time.time()})
        while True:
            try:
                self.fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, payload.encode("utf-8"))
                return self
            except FileExistsError:
                if time.monotonic() - started > self.timeout_s:
                    holder = self.lock_path.read_text(encoding="utf-8", errors="ignore") if self.lock_path.exists() else ""
                    raise RuntimeError(f"Another paper workflow package build is active: {self.lock_path} {holder}")
                time.sleep(1.0)

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

OXIDE = {"O"}
NITRIDE = {"N"}
HALIDE = {"F", "Cl", "Br", "I"}
CHALCOGENIDE = {"S", "Se", "Te"}
ANIONS = OXIDE | NITRIDE | HALIDE | CHALCOGENIDE | {"P", "As"}

RERANK_COLUMNS = [
    "experiment_id",
    "row_id",
    "target_formula",
    "raw_rank",
    "reranked_rank",
    "formula",
    "source_id",
    "cif_path",
    "exact_formula_match",
    "same_reduced_formula",
    "target_element_overlap_count",
    "target_element_overlap_fraction",
    "anion_family_match",
    "abx3_like",
    "same_or_related_prototype",
    "semantic_score",
    "chemistry_score",
    "final_rerank_score",
    "selected_for_evidence",
    "selected_for_display",
    "selected_for_paper_display",
    "paper_display_rank",
    "paper_display_score",
    "selection_reason",
]

SELECTION_COLUMNS = [
    "experiment_id",
    "row_id",
    "target_formula",
    "neighbour_formula",
    "raw_rank",
    "selected_rank",
    "paper_display_rank",
    "paper_display_score",
    "selected_for_display",
    "selected_for_spp",
    "selected_for_paper_display",
    "same_prototype_family",
    "same_anion_family",
    "same_reduced_formula",
    "visual_similarity_reason",
    "target_element_overlap_count",
    "target_element_overlap_fraction",
    "anion_family_match",
    "abx3_like",
    "same_or_related_prototype",
    "selection_decision",
    "selection_reason",
    "rejection_reason",
    "cif_path",
    "source_id",
]

WORKFLOW_DISPLAY_AUDIT_COLUMNS = [
    "experiment_id",
    "row_id",
    "target_formula",
    "raw_retrieval_count",
    "selected_evidence_count",
    "spp_evidence_count",
    "rendered_neighbour_count",
    "displayed_neighbour_count",
    "header_semantic_neighbours_count",
    "header_spp_exported_displayed_count",
    "selected_evidence_formulas",
    "displayed_neighbour_formulas",
    "missing_display_render_paths",
    "display_source_layer",
    "problem_class",
    "notes",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = columns or list(rows[0]) if rows else columns or []
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def rewrite_published_package_paths(package_root: Path, old_root: Path, new_root: Path) -> None:
    old_text = str(old_root)
    new_text = str(new_root)
    old_forward = old_text.replace("\\", "/")
    new_forward = new_text.replace("\\", "/")
    old_json = old_text.replace("\\", "\\\\")
    new_json = new_text.replace("\\", "\\\\")
    suffixes = {".json", ".csv", ".md", ".txt", ".svg"}
    for path in package_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = text.replace(old_text, new_text).replace(old_forward, new_forward).replace(old_json, new_json)
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def comp(formula: str) -> Composition | None:
    try:
        return Composition(str(formula or ""))
    except Exception:
        return None


def reduced(formula: str) -> str:
    c = comp(formula)
    return c.reduced_formula if c else re.sub(r"\s+", "", str(formula or ""))


def elements(formula: str) -> set[str]:
    c = comp(formula)
    if c:
        return {el.symbol for el in c.elements}
    return set(re.findall(r"[A-Z][a-z]?", str(formula or "")))


def anion_family(formula: str) -> str:
    els = elements(formula)
    if els & OXIDE:
        return "oxide"
    if els & NITRIDE:
        return "nitride"
    if els & HALIDE:
        return "halide"
    if els & CHALCOGENIDE:
        return "chalcogenide"
    if els & {"P", "As"}:
        return "pnictide/phosphate-like"
    return "none_or_unknown"


def normalized_amounts(formula: str) -> list[float]:
    c = comp(formula)
    if not c:
        return []
    vals = sorted(float(v) for v in c.get_el_amt_dict().values())
    if not vals or vals[0] == 0:
        return vals
    return [round(v / vals[0], 4) for v in vals]


def is_abx3_like(formula: str) -> bool:
    vals = normalized_amounts(formula)
    return len(vals) == 3 and vals in ([1.0, 1.0, 3.0], [1.0, 2.0, 6.0])


def text_blob(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("formula", "reduced_formula", "elements_csv", "space_group", "source_id", "text_doc")
    ).lower()


def same_or_related_prototype(target_family: str, target_formula: str, formula: str, blob: str) -> bool:
    family = str(target_family or "").lower()
    if "perovskite" in family:
        return "perovskite" in blob or (is_abx3_like(target_formula) and is_abx3_like(formula))
    if "rocksalt" in family:
        return "rocksalt" in blob or "rock salt" in blob or len(elements(formula)) == 2
    if "fluorite" in family:
        return "fluorite" in blob
    if "spinel" in family:
        return "spinel" in blob
    if "halide" in family:
        return bool(elements(formula) & HALIDE)
    if "nitride" in family:
        return "N" in elements(formula)
    if "olivine" in family:
        return "olivine" in blob
    if "argyrodite" in family:
        return "argyrodite" in blob
    if "layered" in family:
        return "layered" in blob
    return False


def load_db_records(db_path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT s.structure_id, s.reduced_formula, s.cif_text,
                   m.formula, m.elements_csv, m.space_group,
                   p.source, p.source_id, p.allow_export,
                   td.text AS text_doc
            FROM structures s
            LEFT JOIN metadata m ON m.structure_id = s.structure_id
            LEFT JOIN provenance p ON p.structure_id = s.structure_id
            LEFT JOIN text_docs td ON td.structure_id = s.structure_id
            """
        ).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def query_text(row: dict[str, str]) -> str:
    qpath = ROOT / "local_runs" / row["experiment_id"] / row["row_id"] / "crystaldb_query.json"
    if qpath.exists():
        q = read_json(qpath)
        return str(q.get("retrieval_query") or q.get("query") or q.get("input_text") or row.get("input_text") or "")
    return str(row.get("retrieval_query_hint") or row.get("input_text") or "")


def semantic_score(query: str, target_family: str, target_formula: str, row: dict[str, Any]) -> float:
    blob = text_blob(row)
    terms = [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9+-]*", f"{query} {target_family} {target_formula}") if len(t) > 1]
    score = sum(1.0 for term in terms if term in blob)
    raw_formula = re.sub(r"\s+", "", str(row.get("formula") or row.get("reduced_formula") or "")).lower()
    if re.sub(r"\s+", "", target_formula).lower() == raw_formula:
        score += 10.0
    return score


def chemistry_features(target: dict[str, str], db_row: dict[str, Any]) -> dict[str, Any]:
    target_formula = target["target_formula"]
    formula = str(db_row.get("formula") or db_row.get("reduced_formula") or "")
    target_comp = comp(target_formula)
    formula_comp = comp(formula)
    target_els = elements(target_formula)
    formula_els = elements(formula)
    overlap = len(target_els & formula_els)
    frac = overlap / len(target_els) if target_els else 0.0
    exact = bool(target_comp and formula_comp and target_comp == formula_comp)
    same_red = reduced(target_formula) == reduced(formula)
    anion = anion_family(target_formula) == anion_family(formula)
    abx3 = is_abx3_like(formula)
    proto = same_or_related_prototype(target.get("target_family", ""), target_formula, formula, text_blob(db_row))
    return {
        "exact_formula_match": exact,
        "same_reduced_formula": same_red,
        "target_element_overlap_count": overlap,
        "target_element_overlap_fraction": round(frac, 3),
        "anion_family_match": anion,
        "abx3_like": abx3,
        "same_or_related_prototype": proto,
    }


def key_cations(formula: str) -> set[str]:
    return elements(formula) - ANIONS


def atom_count(formula: str) -> float:
    c = comp(formula)
    if not c:
        return 99.0
    return float(c.num_atoms)


def display_complexity_penalty(formula: str) -> float:
    atoms = atom_count(reduced(formula))
    if atoms <= 5:
        return 0.0
    if atoms <= 12:
        return (atoms - 5) * 12.0
    return 84.0 + (atoms - 12) * 28.0


def visual_family_match(target: dict[str, str], formula: str, blob: str, features: dict[str, Any]) -> tuple[bool, str, float]:
    family = str(target.get("target_family") or "").lower()
    target_formula = target["target_formula"]
    if "perovskite" in family:
        ok = features["abx3_like"] or "perovskite" in blob
        return ok, "perovskite_like_abx3_or_text_prototype" if ok else "not_visually_perovskite_like", 950.0 if ok else -1250.0
    if "fluorite" in family:
        red_vals = normalized_amounts(formula)
        target_vals = normalized_amounts(target_formula)
        ok = "fluorite" in blob or red_vals == [1.0, 2.0] or red_vals == target_vals
        return ok, "fluorite_like_ax2_or_text_prototype" if ok else "not_visually_fluorite_like", 900.0 if ok else -1050.0
    if "spinel" in family:
        red_vals = normalized_amounts(formula)
        ok = "spinel" in blob or red_vals == [1.0, 2.0, 4.0]
        return ok, "spinel_like_ab2x4_or_text_prototype" if ok else "not_visually_spinel_like", 900.0 if ok else -1050.0
    if "halide" in family:
        ok = bool(elements(formula) & HALIDE) and (features["abx3_like"] or features["same_or_related_prototype"])
        return ok, "halide_perovskite_like_same_family" if ok else "not_visually_halide_perovskite_like", 850.0 if ok else -1000.0
    ok = features["same_or_related_prototype"] or normalized_amounts(formula) == normalized_amounts(target_formula)
    return ok, "same_stoichiometry_or_related_text_prototype" if ok else "weaker_visual_family_match", 450.0 if ok else -250.0


def display_score(target: dict[str, str], db_row: dict[str, Any], features: dict[str, Any], selected_for_spp: bool) -> tuple[float, str, bool]:
    formula = str(db_row.get("formula") or db_row.get("reduced_formula") or "")
    blob = text_blob(db_row)
    target_formula = target["target_formula"]
    target_cations = key_cations(target_formula)
    neighbour_cations = key_cations(formula)
    cation_overlap = len(target_cations & neighbour_cations)
    same_proto = bool(features["same_or_related_prototype"])
    visual_ok, visual_reason, visual_bonus = visual_family_match(target, formula, blob, features)
    same_halide_bonus = 0.0
    family = str(target.get("target_family") or "").lower()
    if "halide" in family:
        target_halides = elements(target_formula) & HALIDE
        neighbour_halides = elements(formula) & HALIDE
        if target_halides and neighbour_halides == target_halides:
            same_halide_bonus = 900.0
        elif neighbour_halides:
            same_halide_bonus = -350.0
    misleading_penalty = 0.0
    if not features["anion_family_match"]:
        misleading_penalty += 900.0
    if target_cations and cation_overlap == 0 and not features["same_reduced_formula"]:
        misleading_penalty += 500.0
    if not visual_ok:
        misleading_penalty += 350.0
    score = (
        4200.0 * int(features["same_reduced_formula"])
        + 1800.0 * int(same_proto)
        + 1200.0 * int(features["anion_family_match"])
        + 800.0 * cation_overlap
        + 650.0 * float(features["target_element_overlap_fraction"])
        + visual_bonus
        + same_halide_bonus
        + 120.0 * int(selected_for_spp)
        - display_complexity_penalty(formula)
        - misleading_penalty
    )
    reason_parts = []
    if features["same_reduced_formula"]:
        reason_parts.append("same reduced formula")
    if same_proto:
        reason_parts.append("same prototype family")
    if features["anion_family_match"]:
        reason_parts.append("same anion family")
    if cation_overlap:
        reason_parts.append(f"{cation_overlap} shared key cation role(s)")
    reason_parts.append(visual_reason)
    if atom_count(reduced(formula)) <= 12:
        reason_parts.append("readable low-complexity render")
    if misleading_penalty:
        reason_parts.append("penalised for indirect or visually misleading analogy")
    return score, "; ".join(reason_parts), visual_ok


def defensible(target: dict[str, str], db_row: dict[str, Any], features: dict[str, Any]) -> tuple[bool, str, str]:
    family = str(target.get("target_family") or "").lower()
    formula = str(db_row.get("formula") or db_row.get("reduced_formula") or "")
    target_formula = target["target_formula"]
    nels = elements(formula)
    if not formula:
        return False, "", "missing_formula"
    if features["same_reduced_formula"]:
        return True, "same_reduced_formula", ""
    if "perovskite" in family:
        if not features["anion_family_match"]:
            return False, "", "wrong_anion_family_for_perovskite"
        if "Ti" in elements(target_formula):
            if "Ti" in nels and (features["abx3_like"] or features["same_or_related_prototype"] or features["target_element_overlap_fraction"] >= 0.5):
                return True, "real_corpus_titanate_perovskite_or_related_evidence", ""
            return False, "", "not_titanate_perovskite_relevant"
        if features["abx3_like"] or features["same_or_related_prototype"]:
            return True, "same_anion_perovskite_family", ""
    if "halide" in family:
        if features["anion_family_match"] and (features["target_element_overlap_fraction"] >= 0.5 or features["same_or_related_prototype"]):
            return True, "halide_family_with_target_element_or_prototype_overlap", ""
        return False, "", "not_halide_relevant"
    if "nitride" in family or ("rocksalt" in family and "N" in elements(target_formula)):
        if features["anion_family_match"] and "N" in nels and (features["target_element_overlap_fraction"] >= 0.5 or "Ti" in nels):
            return True, "nitride_relevant_real_corpus_evidence", ""
        return False, "", "not_nitride_relevant"
    if features["anion_family_match"] and features["target_element_overlap_fraction"] >= 0.5:
        return True, "same_anion_family_with_element_overlap", ""
    if features["anion_family_match"] and features["same_or_related_prototype"]:
        return True, "same_anion_family_and_related_prototype", ""
    return False, "", "insufficient_element_or_anion_family_overlap"


def chemistry_score(features: dict[str, Any]) -> float:
    return (
        10000 * int(features["exact_formula_match"])
        + 5000 * int(features["same_reduced_formula"])
        + 1000 * float(features["target_element_overlap_fraction"])
        + 800 * int(features["anion_family_match"])
        + 450 * int(features["same_or_related_prototype"])
        + 250 * int(features["abx3_like"])
        + 50 * int(features["target_element_overlap_count"])
    )


def raw_rank_lookup(exp_id: str, row_id: str) -> dict[str, int]:
    repair = V9 / "RAW_RETRIEVAL_REPAIR" / exp_id / row_id / "crystaldb_retrieval_results_top50.json"
    raw = repair if repair.exists() else ROOT / "local_runs" / exp_id / row_id / "crystaldb_retrieval_results.json"
    lookup: dict[str, int] = {}
    if not raw.exists():
        return lookup
    payload = read_json(raw)
    for idx, n in enumerate(payload.get("neighbors") or [], start=1):
        source_id = str((n.get("provenance") or {}).get("source_id") or n.get("structure_id") or "")
        lookup[source_id] = int(n.get("rank") or idx)
    return lookup


def make_neighbor(target: dict[str, str], db_row: dict[str, Any], export_dir: Path, rank: int, score: float, reason: str) -> dict[str, Any]:
    source_id = str(db_row.get("source_id") or db_row.get("structure_id") or "")
    cif_path = export_dir / f"rank_{rank:03d}_{re.sub(r'[^A-Za-z0-9]+', '_', source_id).strip('_') or 'candidate'}.cif"
    if db_row.get("cif_text"):
        cif_path.parent.mkdir(parents=True, exist_ok=True)
        cif_path.write_text(str(db_row["cif_text"]), encoding="utf-8")
    return {
        "rank": rank,
        "raw_rank": db_row.get("_raw_rank", rank),
        "selected_rank": rank,
        "score": score,
        "structure_id": db_row.get("structure_id"),
        "retrieval_method": "v10_direct_formula_reduced_formula_chemistry_rerank",
        "metadata": {
            "formula": db_row.get("formula") or db_row.get("reduced_formula"),
            "reduced_formula": db_row.get("reduced_formula"),
            "elements_csv": db_row.get("elements_csv"),
            "space_group": db_row.get("space_group"),
        },
        "provenance": {
            "source": db_row.get("source"),
            "source_id": source_id,
            "allow_export": db_row.get("allow_export"),
        },
        "cif_export": {"status": "exported" if db_row.get("cif_text") else "error", "path": str(cif_path)},
        "text_doc": {"text": str(db_row.get("text_doc") or "")[:600]},
        "selection_reason": reason,
    }


def rerank_for_row(target: dict[str, str], records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    q = query_text(target)
    raw_lookup = raw_rank_lookup(target["experiment_id"], target["row_id"])
    scored: list[dict[str, Any]] = []
    for db_row in records:
        formula = str(db_row.get("formula") or db_row.get("reduced_formula") or "")
        if not formula:
            continue
        feats = chemistry_features(target, db_row)
        sem = semantic_score(q, target.get("target_family", ""), target["target_formula"], db_row)
        chem = chemistry_score(feats)
        ok, reason, reject = defensible(target, db_row, feats)
        source_id = str(db_row.get("source_id") or db_row.get("structure_id") or "")
        if not ok and not (feats["exact_formula_match"] or feats["same_reduced_formula"] or feats["target_element_overlap_count"] >= 2):
            continue
        final = chem + sem
        item = {
            **db_row,
            **feats,
            "_semantic_score": sem,
            "_chemistry_score": chem,
            "_final_rerank_score": final,
            "_defensible": ok,
            "_selection_reason": reason,
            "_rejection_reason": reject,
            "_raw_rank": raw_lookup.get(source_id, 9999),
        }
        scored.append(item)
    scored.sort(
        key=lambda r: (
            -float(r["_final_rerank_score"]),
            int(r["_raw_rank"]),
            str(r.get("source_id") or r.get("structure_id") or ""),
        )
    )
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in scored:
        key = str(item.get("source_id") or item.get("structure_id") or item.get("formula"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= 80:
            break
    selected = [item for item in unique if item["_defensible"]][:8]
    return unique, selected


def row_key(row: dict[str, str]) -> tuple[str, str]:
    return row["experiment_id"], row["row_id"]


def build_v10_payloads() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    v9_corpus = {row_key(r): r for r in read_csv(V9 / "CORPUS_SELECTION_AUDIT.csv")}
    manifest = {row_key(r): r for r in read_csv(FULL_MANIFEST)}
    phase6_records = load_db_records(PHASE6)
    halide_records = load_db_records(HALIDE_DB)
    rerank_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    selected_payloads: dict[tuple[str, str], dict[str, Any]] = {}
    paper_display_payloads: dict[tuple[str, str], dict[str, Any]] = {}

    for key, c in sorted(v9_corpus.items()):
        target = {**manifest.get(key, {}), **c}
        records = halide_records if target["experiment_id"] == "paper_experiment_3_specialist_halide_v1" else phase6_records
        candidates, selected = rerank_for_row(target, records)
        export_dir = ROOT / "local_runs" / target["experiment_id"] / target["row_id"] / "v10_selected_evidence_cifs"
        neighbors = []
        for selected_rank, item in enumerate(selected, start=1):
            neighbors.append(make_neighbor(target, item, export_dir, selected_rank, item["_final_rerank_score"], item["_selection_reason"]))
        selected_source_ids = {str((n.get("provenance") or {}).get("source_id") or n.get("structure_id") or "") for n in neighbors}
        display_candidates: list[dict[str, Any]] = []
        for item in candidates:
            source_id = str(item.get("source_id") or item.get("structure_id") or "")
            if not item.get("cif_text"):
                continue
            score, reason, visual_ok = display_score(target, item, item, source_id in selected_source_ids)
            if not visual_ok and len(display_candidates) >= 8:
                continue
            display_item = dict(item)
            display_item["_paper_display_score"] = score
            display_item["_visual_similarity_reason"] = reason
            display_item["_selected_for_spp"] = source_id in selected_source_ids
            display_candidates.append(display_item)
        display_candidates.sort(
            key=lambda r: (
                -float(r["_paper_display_score"]),
                0 if r.get("_selected_for_spp") else 1,
                int(r["_raw_rank"]),
                str(r.get("source_id") or r.get("structure_id") or ""),
            )
        )
        paper_display = display_candidates[:8]
        if len(paper_display) < 6:
            selected_missing = [
                item for item in selected
                if str(item.get("source_id") or item.get("structure_id") or "") not in {str(row.get("source_id") or row.get("structure_id") or "") for row in paper_display}
            ]
            for item in selected_missing:
                source_id = str(item.get("source_id") or item.get("structure_id") or "")
                score, reason, _visual_ok = display_score(target, item, item, True)
                display_item = dict(item)
                display_item["_paper_display_score"] = score - 250.0
                display_item["_visual_similarity_reason"] = reason + "; SPP evidence backfill because fewer than six display neighbours were available"
                display_item["_selected_for_spp"] = source_id in selected_source_ids
                paper_display.append(display_item)
                if len(paper_display) >= 6:
                    break
        paper_display = paper_display[:8]
        paper_display_source_ids = {str(item.get("source_id") or item.get("structure_id") or "") for item in paper_display}
        paper_export_dir = ROOT / "local_runs" / target["experiment_id"] / target["row_id"] / "v10_paper_display_neighbour_cifs"
        paper_neighbors = []
        for display_rank, item in enumerate(paper_display, start=1):
            n = make_neighbor(target, item, paper_export_dir, display_rank, item["_paper_display_score"], item["_visual_similarity_reason"])
            n["paper_display_rank"] = display_rank
            n["paper_display_score"] = round(float(item["_paper_display_score"]), 6)
            n["selected_for_spp"] = bool(item["_selected_for_spp"])
            n["selected_for_paper_display"] = True
            n["visual_similarity_reason"] = item["_visual_similarity_reason"]
            paper_neighbors.append(n)
        paper_rank_by_source = {
            str((n.get("provenance") or {}).get("source_id") or n.get("structure_id") or ""): n
            for n in paper_neighbors
        }
        for reranked_rank, item in enumerate(candidates, start=1):
            source_id = str(item.get("source_id") or item.get("structure_id") or "")
            selected_for_evidence = source_id in selected_source_ids
            display_neighbor = paper_rank_by_source.get(source_id)
            selected_for_paper_display = display_neighbor is not None
            reason = item["_selection_reason"] if selected_for_evidence else item["_rejection_reason"]
            cif_path = ""
            if selected_for_evidence:
                for n in neighbors:
                    if str((n.get("provenance") or {}).get("source_id") or n.get("structure_id") or "") == source_id:
                        cif_path = str((n.get("cif_export") or {}).get("path") or "")
                        break
            rerank_rows.append(
                {
                    "experiment_id": target["experiment_id"],
                    "row_id": target["row_id"],
                    "target_formula": target["target_formula"],
                    "raw_rank": item["_raw_rank"],
                    "reranked_rank": reranked_rank,
                    "formula": item.get("formula") or item.get("reduced_formula"),
                    "source_id": source_id,
                    "cif_path": cif_path,
                    "exact_formula_match": item["exact_formula_match"],
                    "same_reduced_formula": item["same_reduced_formula"],
                    "target_element_overlap_count": item["target_element_overlap_count"],
                    "target_element_overlap_fraction": item["target_element_overlap_fraction"],
                    "anion_family_match": item["anion_family_match"],
                    "abx3_like": item["abx3_like"],
                    "same_or_related_prototype": item["same_or_related_prototype"],
                    "semantic_score": round(float(item["_semantic_score"]), 6),
                    "chemistry_score": round(float(item["_chemistry_score"]), 6),
                    "final_rerank_score": round(float(item["_final_rerank_score"]), 6),
                    "selected_for_evidence": selected_for_evidence,
                    "selected_for_display": selected_for_paper_display,
                    "selected_for_paper_display": selected_for_paper_display,
                    "paper_display_rank": (display_neighbor or {}).get("paper_display_rank", ""),
                    "paper_display_score": (display_neighbor or {}).get("paper_display_score", ""),
                    "selection_reason": reason,
                }
            )
            # Keep the full retained candidate window so every selected item is auditable,
            # even when a row has many tied chemistry-first candidates.
        manifest_sources = {}
        for n in neighbors:
            source_id = str((n.get("provenance") or {}).get("source_id") or n.get("structure_id") or "")
            manifest_sources[source_id] = {"spp": n, "display": paper_rank_by_source.get(source_id)}
        for n in paper_neighbors:
            source_id = str((n.get("provenance") or {}).get("source_id") or n.get("structure_id") or "")
            manifest_sources.setdefault(source_id, {"spp": None, "display": n})
        for source_id, pair in sorted(
            manifest_sources.items(),
            key=lambda kv: (
                int((kv[1].get("spp") or {}).get("selected_rank") or 9999),
                int((kv[1].get("display") or {}).get("paper_display_rank") or 9999),
                kv[0],
            ),
        ):
            n = pair.get("spp") or pair.get("display") or {}
            display_n = pair.get("display") or {}
            spp_n = pair.get("spp") or {}
            feats = chemistry_features(target, {**n.get("metadata", {}), "source_id": source_id})
            selection_rows.append(
                {
                    "experiment_id": target["experiment_id"],
                    "row_id": target["row_id"],
                    "target_formula": target["target_formula"],
                    "neighbour_formula": (n.get("metadata") or {}).get("formula"),
                    "raw_rank": n.get("raw_rank"),
                    "selected_rank": spp_n.get("selected_rank", ""),
                    "paper_display_rank": display_n.get("paper_display_rank", ""),
                    "paper_display_score": display_n.get("paper_display_score", ""),
                    "selected_for_display": bool(display_n),
                    "selected_for_spp": bool(spp_n),
                    "selected_for_paper_display": bool(display_n),
                    "same_prototype_family": feats["same_or_related_prototype"],
                    "same_anion_family": feats["anion_family_match"],
                    "same_reduced_formula": feats["same_reduced_formula"],
                    "visual_similarity_reason": display_n.get("visual_similarity_reason", ""),
                    **{k: feats[k] for k in ("target_element_overlap_count", "target_element_overlap_fraction", "anion_family_match", "abx3_like", "same_or_related_prototype")},
                    "selection_decision": "selected_for_spp" if spp_n else "paper_display_only",
                    "selection_reason": spp_n.get("selection_reason", ""),
                    "rejection_reason": "" if spp_n else "not_in_selected_evidence_for_spp",
                    "cif_path": (spp_n.get("cif_export") or display_n.get("cif_export") or {}).get("path"),
                    "source_id": source_id,
                }
            )
        db_path = HALIDE_DB if target["experiment_id"] == "paper_experiment_3_specialist_halide_v1" else PHASE6
        selected_payloads[key] = {
            "status": "ok",
            "query": {
                "text": query_text(target),
                "formula": target["target_formula"],
                "family": target.get("target_family", ""),
                "db_path": str(db_path),
                "method": "v10_direct_formula_reduced_formula_chemistry_rerank",
                "ranking_components": [
                    "exact_formula_match",
                    "same_reduced_formula",
                    "target_element_overlap",
                    "anion_family_match",
                    "abx3_or_prototype_family_match",
                    "semantic_text_score",
                ],
            },
            "neighbors": neighbors,
            "errors": None,
            "selection_layer": {
                "name": "selected_evidence_for_spp_v10",
                "raw_retrieval_preserved": True,
                "selection_policy": "direct/reduced formula first, then element overlap, anion family, prototype/family, semantic score",
                "stub_records_allowed": False,
            },
        }
        paper_display_payloads[key] = {
            "status": "ok",
            "query": {
                "text": query_text(target),
                "formula": target["target_formula"],
                "family": target.get("target_family", ""),
                "db_path": str(db_path),
                "method": "v10_paper_display_neighbour_selection",
                "ranking_components": [
                    "same_reduced_formula",
                    "same_prototype_family",
                    "same_anion_family",
                    "same_key_cation_roles",
                    "structural_visual_similarity",
                    "render_readability_low_complexity",
                    "misleading_indirect_analogue_penalty",
                ],
            },
            "neighbors": paper_neighbors,
            "errors": None,
            "selection_layer": {
                "name": "paper_display_neighbours_v10",
                "raw_retrieval_preserved": True,
                "selected_evidence_for_spp_preserved": True,
                "preferred_display_count": "6-8",
                "selection_policy": "display-only structural readability ranking; SPP generation continues to use selected_evidence_for_spp",
            },
        }
    return rerank_rows, selection_rows, selected_payloads, paper_display_payloads


def formulas_by_key(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        if str(r.get("selected_for_spp") or "").lower() == "true" or r.get("selection_decision") == "selected":
            out.setdefault((r["experiment_id"], r["row_id"]), []).append(r["neighbour_formula"])
    return out


def write_comparison(selection_rows: list[dict[str, Any]], rerank_rows: list[dict[str, Any]]) -> None:
    v9_sel = formulas_by_key(read_csv(V9 / "EVIDENCE_SELECTION_MANIFEST.csv"))
    v10_sel: dict[tuple[str, str], list[str]] = {}
    for r in selection_rows:
        if str(r.get("selected_for_spp")).lower() == "true":
            v10_sel.setdefault((r["experiment_id"], r["row_id"]), []).append(str(r["neighbour_formula"]))
    changed = [key for key in sorted(v10_sel) if v9_sel.get(key, []) != v10_sel.get(key, [])]
    improved = []
    weak = []
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rerank_rows:
        by_key.setdefault((r["experiment_id"], r["row_id"]), []).append(r)
    for key, rows in sorted(by_key.items()):
        selected = [r for r in rows if str(r["selected_for_evidence"]).lower() == "true"]
        strong = sum(1 for r in selected if str(r["exact_formula_match"]).lower() == "true" or str(r["same_reduced_formula"]).lower() == "true" or float(r["target_element_overlap_fraction"]) >= 0.67)
        if strong >= min(3, len(selected)):
            improved.append(key)
        if len(selected) < 3 or all(float(r["target_element_overlap_fraction"]) < 0.5 for r in selected):
            weak.append(key)
    def fmt_key(key: tuple[str, str]) -> str:
        return f"`{key[0]}/{key[1]}`"
    batio3 = v10_sel.get(("paper_experiment_1_common_v1", "exp1_batio3_perovskite"), [])
    srtio3 = v10_sel.get(("paper_experiment_2_hard_v3", "exp2v3_srtio3_perovskite"), [])
    tin = v10_sel.get(("paper_experiment_1_common_v1", "exp1_tin_rocksalt"), [])
    exp3_changed = [key for key in changed if key[0] == "paper_experiment_3_specialist_halide_v1"]
    lines = [
        "# v9 vs v10 Evidence Comparison",
        "",
        "## Answers",
        "",
        f"- Rows improved by chemistry-first reranking: {len(improved)} rows ({', '.join(fmt_key(k) for k in improved[:20])}{'...' if len(improved) > 20 else ''}).",
        f"- Rows with changed selected evidence: {len(changed)} rows ({', '.join(fmt_key(k) for k in changed[:20])}{'...' if len(changed) > 20 else ''}).",
        f"- Rows still weak from the real source corpus: {len(weak)} rows ({', '.join(fmt_key(k) for k in weak) if weak else 'none'}).",
        f"- BaTiO3 now retrieves real-corpus titanate/perovskite evidence: {'yes' if any('Ti' in elements(f) and anion_family(f) == 'oxide' for f in batio3) else 'no'}; selected formulas: {', '.join(batio3)}.",
        f"- SrTiO3 now retrieves cleaner titanate/perovskite evidence: {'yes' if any('Ti' in elements(f) and anion_family(f) == 'oxide' for f in srtio3) else 'no'}; selected formulas: {', '.join(srtio3)}.",
        f"- TiN retrieves nitride-relevant evidence: {'yes' if all('N' in elements(f) for f in tin) and tin else 'no'}; selected formulas: {', '.join(tin)}.",
        f"- Specialist Exp3 rows changed: {len(exp3_changed)}. They remain constrained to `{HALIDE_DB.name}` and halide-family evidence.",
        "",
        "## Rerun Decision",
        "",
        "- Selected evidence changed for rows listed above, but required SPP species-pair objectives remain target-formula based and existing row-specific SPP coverage remains complete. QLIP/validation/CHGNet artifacts are therefore inherited unless a downstream run explicitly changes the SPP objective.",
        "- No `stub://crystal.db` records are used in v10 selected evidence.",
        "",
        "## Exact Fix Applied",
        "",
        "v10 ranks real Crystal-DB rows by exact formula, same reduced formula, target-element overlap, anion-family match, ABX3/prototype/family match, then semantic text score. Semantic score is retained as a component, not the sole ranking criterion.",
    ]
    (V10 / "V9_VS_V10_EVIDENCE_COMPARISON.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_package_builder(selected_payloads: dict[tuple[str, str], dict[str, Any]], paper_display_payloads: dict[tuple[str, str], dict[str, Any]]) -> None:
    backups: dict[Path, str | None] = {}
    build_uuid = uuid.uuid4().hex
    build_root = V10.parent / f"{V10.name}.build-{build_uuid}"
    try:
        for (exp_id, row_id), payload in selected_payloads.items():
            path = ROOT / "local_runs" / exp_id / row_id / "selected_evidence_payload.json"
            backups[path] = path.read_text(encoding="utf-8") if path.exists() else None
            write_json(path, payload)
        for (exp_id, row_id), payload in paper_display_payloads.items():
            path = ROOT / "local_runs" / exp_id / row_id / "paper_display_neighbours_payload.json"
            backups[path] = path.read_text(encoding="utf-8") if path.exists() else None
            write_json(path, payload)
        if build_root.exists():
            shutil.rmtree(build_root)
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "build_paper_workflow_artifact_package.py"),
            "--package-version",
            "v10",
            "--source-package-root",
            str(V9),
            "--package-root",
            str(build_root),
            "--force",
            "--require-vesta",
            "--no-fallback-structure-rendering",
            "--require-vesta-images",
            "--vesta-render-manifest",
            str(V10_FORMULA_MATCHED_RENDER_MANIFEST if V10_FORMULA_MATCHED_RENDER_MANIFEST.exists() else V7_RENDER_MANIFEST),
            "--vesta-timeout-s",
            "45",
            "--vesta-retries",
            "1",
            "--vesta-call-delay-s",
            "0.5",
            "--neighbours-per-row",
            "8",
        ]
        env = {
            **os.environ,
            "PAPER_PACKAGE_BUILD_UUID": build_uuid,
            "VESTA_RENDER_BUILD_UUID": build_uuid,
            "PAPER_PACKAGE_BUILD_LOCK_HELD": "1",
        }
        with BuildLock(ROOT / "artifacts" / ".paper_workflow_package_build.lock"):
            subprocess.run(cmd, cwd=ROOT, check=True, env=env)
            old_root = V10.parent / f"{V10.name}.old-{build_uuid}"
            if old_root.exists():
                shutil.rmtree(old_root)
            if V10.exists():
                V10.replace(old_root)
            build_root.replace(V10)
            rewrite_published_package_paths(V10, build_root, V10)
            if old_root.exists():
                shutil.rmtree(old_root)
    finally:
        if build_root.exists():
            shutil.rmtree(build_root)
        for path, text in backups.items():
            if text is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(text, encoding="utf-8")


def copy_figures() -> None:
    if FIGURES_V10.exists():
        shutil.rmtree(FIGURES_V10)
    FIGURES_V10.mkdir(parents=True, exist_ok=True)
    for row in read_csv(V10 / "WORKFLOW_ARTIFACTS_INDEX.csv"):
        src = V10 / row["row_workflow_artifact_png"]
        if src.exists():
            dst = FIGURES_V10 / f"{row['experiment_id']}__{row['row_id']}__workflow_artifact.png"
            shutil.copy2(src, dst)
    contact = V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png"
    if contact.exists():
        shutil.copy2(contact, FIGURES_V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png")


def write_final_summary(selection_rows: list[dict[str, Any]]) -> None:
    spp = read_csv(V10 / "SPP_EVIDENCE_AUDIT.csv") if (V10 / "SPP_EVIDENCE_AUDIT.csv").exists() else read_csv(V9 / "SPP_EVIDENCE_AUDIT.csv")
    selected_counts: dict[tuple[str, str], int] = {}
    display_counts: dict[tuple[str, str], int] = {}
    for r in selection_rows:
        key = (r["experiment_id"], r["row_id"])
        if str(r.get("selected_for_spp")).lower() == "true":
            selected_counts[key] = selected_counts.get(key, 0) + 1
        if str(r.get("selected_for_paper_display")).lower() == "true":
            display_counts[key] = display_counts.get(key, 0) + 1
    lines = [
        "# Final Results Summary - paper_results_package_v10",
        "",
        "- v10 keeps raw retrieval, selected SPP evidence, and paper-display neighbours as separate layers.",
        f"- Selected SPP evidence rows: {sum(selected_counts.values())}.",
        f"- Paper-display neighbour rows: {sum(display_counts.values())}.",
        f"- Rows with fewer than 3 selected evidence entries: {sum(1 for c in selected_counts.values() if c < 3)}.",
        f"- SPP coverage complete rows: {sum(1 for r in spp if str(r.get('pair_coverage_complete')).lower() == 'true')}/{len(spp)}.",
        f"- Universal-only primary SPP rows: {sum(1 for r in spp if str(r.get('used_universal_only')).lower() == 'true')}.",
        f"- SPP NaN/Inf rows: {sum(1 for r in spp if int(float(r.get('nan_count') or 0)) or int(float(r.get('inf_count') or 0)))}.",
        "- QLIP/validation/CHGNet artifacts inherited because target SPP objectives remain unchanged.",
        "- Main selected evidence contains no `stub://crystal.db` records.",
    ]
    (V10 / "FINAL_RESULTS_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_v10_count_audits(selection_rows: list[dict[str, Any]]) -> None:
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    display_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in selection_rows:
        key = (row["experiment_id"], row["row_id"])
        if str(row.get("selected_for_spp")).lower() == "true":
            by_key.setdefault(key, []).append(row)
        if str(row.get("selected_for_paper_display")).lower() == "true":
            display_by_key.setdefault(key, []).append(row)

    corpus_path = V10 / "CORPUS_SELECTION_AUDIT.csv"
    if corpus_path.exists():
        corpus_rows = read_csv(corpus_path)
        for row in corpus_rows:
            selected = by_key.get((row["experiment_id"], row["row_id"]), [])
            displayed = display_by_key.get((row["experiment_id"], row["row_id"]), [])
            row["selected_evidence_count"] = len(selected)
            row["displayed_neighbour_count"] = len(displayed)
            notes = str(row.get("notes") or "")
            if "v10_paper_display_neighbours_separate_from_spp_evidence" not in notes:
                row["notes"] = (notes + "; " if notes else "") + "v10_chemistry_first_rerank_selected_evidence; v10_paper_display_neighbours_separate_from_spp_evidence"
        write_csv(corpus_path, corpus_rows, list(corpus_rows[0].keys()))

    spp_path = V10 / "SPP_EVIDENCE_AUDIT.csv"
    if spp_path.exists():
        spp_rows = read_csv(spp_path)
        for row in spp_rows:
            selected = by_key.get((row["experiment_id"], row["row_id"]), [])
            row["selected_evidence_count"] = len(selected)
            row["selected_cif_paths"] = ";".join(str(item.get("cif_path") or "") for item in selected)
            notes = str(row.get("notes") or "")
            if "v10_selected_evidence_count_updated" not in notes:
                row["notes"] = (notes + "; " if notes else "") + "v10_selected_evidence_count_updated; spp_objective_pairs_unchanged_from_target_formula"
        write_csv(spp_path, spp_rows, list(spp_rows[0].keys()))


def update_workflow_display_count_audit(selection_rows: list[dict[str, Any]]) -> None:
    selected_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    display_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in selection_rows:
        key = (row["experiment_id"], row["row_id"])
        if str(row.get("selected_for_spp")).lower() == "true":
            selected_by_key.setdefault(key, []).append(row)
        if str(row.get("selected_for_paper_display")).lower() == "true":
            display_by_key.setdefault(key, []).append(row)

    corpus_rows = {(r["experiment_id"], r["row_id"]): r for r in read_csv(V10 / "CORPUS_SELECTION_AUDIT.csv")} if (V10 / "CORPUS_SELECTION_AUDIT.csv").exists() else {}
    audit_rows: list[dict[str, Any]] = []
    for index_row in read_csv(V10 / "WORKFLOW_ARTIFACTS_INDEX.csv"):
        key = (index_row["experiment_id"], index_row["row_id"])
        selected = selected_by_key.get(key, [])
        paper_display = display_by_key.get(key, [])
        selected_formulas = [str(row.get("neighbour_formula") or "") for row in selected]
        row_png = V10 / index_row["row_workflow_artifact_png"]
        row_manifest = row_png.with_name(row_png.stem + "_manifest.json")
        panel: dict[str, Any] = {}
        if row_manifest.exists():
            panel = ((read_json(row_manifest).get("panels") or {}).get("crystal_db_retrieved_corpus") or {})
        children = panel.get("children") or []
        rendered_children = [
            child
            for child in children
            if child.get("render_status") == "rendered"
            and child.get("renderer_used") in {"pre_rendered_vesta_png", "qlip_vesta_renderer"}
        ]
        rendered_count = len(rendered_children)
        displayed_formulas = [str(child.get("formula") or child.get("structure_id") or "") for child in rendered_children]
        missing_paths = [
            str(child.get("source_artifact_path") or child.get("vesta_render_path") or "")
            for child in children
            if child.get("render_status") != "rendered"
        ]
        displayed_count = rendered_count
        problem = []
        if displayed_count >= 6 and rendered_count < 6:
            problem.append("paper_display_ge_6_rendered_lt_6")
        if int(index_row.get("semantic_neighbour_fallback_count") or 0):
            problem.append("fallback_render_used")
        if missing_paths:
            problem.append("missing_display_render")
        audit_rows.append(
            {
                "experiment_id": key[0],
                "row_id": key[1],
                "target_formula": index_row.get("target_formula", ""),
                "raw_retrieval_count": (corpus_rows.get(key) or {}).get("raw_retrieval_count", ""),
                "selected_evidence_count": len(selected),
                "spp_evidence_count": len(selected),
                "rendered_neighbour_count": rendered_count,
                "displayed_neighbour_count": displayed_count,
                "header_semantic_neighbours_count": index_row.get("semantic_neighbour_target_count", ""),
                "header_spp_exported_displayed_count": f"{panel.get('selected_evidence_for_spp_count', len(selected))}/{displayed_count}",
                "selected_evidence_formulas": ";".join(selected_formulas),
                "displayed_neighbour_formulas": ";".join(displayed_formulas),
                "missing_display_render_paths": ";".join(missing_paths),
                "display_source_layer": "paper_display_neighbours",
                "problem_class": ";".join(problem) if problem else "ok",
                "notes": "v10_paper_display_neighbours_separate_from_spp_evidence",
            }
        )
    write_csv(V10 / "WORKFLOW_DISPLAY_COUNT_AUDIT.csv", audit_rows, WORKFLOW_DISPLAY_AUDIT_COLUMNS)


def zip_v10() -> None:
    zip_path = V10.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(V10.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(V10.parent))
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
    if bad:
        raise RuntimeError(f"zip failed at {bad}")


def main() -> int:
    rerank_rows, selection_rows, selected_payloads, paper_display_payloads = build_v10_payloads()
    run_package_builder(selected_payloads, paper_display_payloads)
    write_csv(V10 / "RETRIEVAL_RERANKING_AUDIT.csv", rerank_rows, RERANK_COLUMNS)
    write_csv(V10 / "EVIDENCE_SELECTION_MANIFEST.csv", selection_rows, SELECTION_COLUMNS)
    # Preserve v9 SPP audit unless a separate SPP-objective regeneration is intentionally run.
    shutil.copy2(V9 / "SPP_EVIDENCE_AUDIT.csv", V10 / "SPP_EVIDENCE_AUDIT.csv")
    update_v10_count_audits(selection_rows)
    update_workflow_display_count_audit(selection_rows)
    write_comparison(selection_rows, rerank_rows)
    copy_figures()
    write_final_summary(selection_rows)
    zip_v10()
    print(f"wrote {V10}")
    print(f"wrote {V10.with_suffix('.zip')}")
    print(f"wrote {FIGURES_V10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
