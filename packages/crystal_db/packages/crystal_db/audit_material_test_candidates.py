#!/usr/bin/env python3
"""Score Crystal-DB/SPP material systems for Skill-Loop-CSP smoke demos.

This is a stricter companion to audit_material_capabilities.py. The broad
capability audit answers "can every required POT pair be found?" This script
answers "is this a sane, high-confidence demo/test candidate?"
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from audit_material_capabilities import (  # noqa: E402
    DEFAULT_DB_PATH,
    DEFAULT_SPP_RUNS,
    canonical_formula,
    load_pot_roots,
    parse_formula_counts,
    required_pairs,
)


JSON_OUT = REPO_ROOT / "artifacts" / "material_test_candidate_audit.json"
MD_OUT = REPO_ROOT / "docs" / "material_test_candidate_audit.md"
SMOKE_SUITE_OUT = REPO_ROOT / "artifacts" / "skill_loop_smoke_suite.json"

DEMONSTRATED_COMPLETE = {"CoAs2", "CaTiO3", "BaTiO3"}
PREFERRED_COMPLETE = ["CoAs2", "CaTiO3", "BaTiO3", "Al2O3", "Fe2O3", "CoO", "CeO2"]
MANUALLY_VERIFIED = {"CoAs2", "CaTiO3", "TiO2", "ZnO"}
EXPECTED_PARTIAL = ["ZnS", "LiCoO2", "TiO2", "ZnO", "BrCl", "CeF3"]
EDGE_CASES = [
    {
        "id": "generic_abo3_requires_concrete_composition",
        "formula": "ABO3",
        "prompt": "Generate an ABO3 perovskite-like crystal without specifying concrete A and B elements.",
        "reason": "Prototype request should be rejected or clarified before SPP/QLIP because POT pairs require concrete elements.",
        "expected_outcome": "blocked_or_partial",
        "expected_error_codes": ["non_concrete_formula"],
        "expected_failure_family": "non_concrete_formula",
    },
    {
        "id": "not_in_crystaldb_unobtainium",
        "formula": "UnobtainiumO2",
        "prompt": "Generate an UnobtainiumO2 oxide candidate using Crystal-DB retrieval and QLIP.",
        "reason": "Non-real/non-indexed composition should be blocked before retrieval/POT handoff.",
        "expected_outcome": "blocked_or_partial",
        "expected_error_codes": ["spp_request_ref_unavailable", "missing_corpus_path", "empty_corpus_ref"],
        "expected_failure_family": "unsupported_material",
    },
]

RADIOACTIVE_OR_UNWANTED = {
    "Ac",
    "Am",
    "At",
    "Bk",
    "Cf",
    "Cm",
    "Es",
    "Fm",
    "Fr",
    "Lr",
    "Md",
    "Np",
    "No",
    "Pa",
    "Po",
    "Pu",
    "Ra",
    "Rn",
    "Th",
    "U",
}
DEMO_FRIENDLY_ELEMENTS = {
    "Ag",
    "Al",
    "As",
    "Ba",
    "Ca",
    "Ce",
    "Co",
    "Cu",
    "Fe",
    "Ga",
    "In",
    "Li",
    "Mg",
    "Na",
    "Nb",
    "O",
    "S",
    "Se",
    "Si",
    "Sr",
    "Ti",
    "Zn",
}
COMMON_FORMULA_BONUS = {
    "CoAs2": 28,
    "CaTiO3": 28,
    "BaTiO3": 26,
    "Al2O3": 24,
    "Fe2O3": 24,
    "CoO": 22,
    "CeO2": 22,
    "TiO2": 22,
    "ZnO": 22,
    "ZnS": 18,
    "LiCoO2": 18,
}

EXPECTED_PARTIAL_ERROR_CODES = {
    "ZnS": ["spp_request_ref_unavailable", "pot_root_material_system_mismatch"],
    "LiCoO2": ["spp_request_ref_unavailable", "pot_root_material_system_mismatch"],
    "TiO2": ["spp_request_ref_unavailable", "pot_root_material_system_mismatch"],
    "ZnO": ["spp_request_ref_unavailable", "pot_root_material_system_mismatch"],
    "Al2O3": ["spp_request_ref_unavailable", "pot_root_material_system_mismatch"],
    "Fe2O3": ["spp_request_ref_unavailable", "pot_root_material_system_mismatch"],
}


def formula_id(formula: str) -> str:
    out = []
    for ch in formula.lower():
        out.append(ch if ch.isalnum() else "_")
    return "".join(out).strip("_") or "material"


def total_atoms(formula: str) -> int:
    _, counts = parse_formula_counts(formula)
    return int(sum(counts.values()))


def load_crystaldb_evidence(db_path: Path) -> Dict[str, Dict[str, Any]]:
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT s.structure_id, s.cif_text, s.reduced_formula, "
        "m.formula, m.elements_csv, p.source, p.source_id, p.allow_export, "
        "MAX(CASE WHEN td.engine = 'robocrys' AND td.text_view = 'robocrys' AND td.status = 'OK' THEN 1 ELSE 0 END) AS has_robocrys_text, "
        "MAX(CASE WHEN td.status = 'OK' THEN 1 ELSE 0 END) AS has_text_doc, "
        "MAX(CASE WHEN te.status = 'OK' THEN 1 ELSE 0 END) AS has_embedding, "
        "MAX(CASE WHEN fp.structure_id IS NOT NULL THEN 1 ELSE 0 END) AS has_fingerprint "
        "FROM structures s "
        "JOIN metadata m ON m.structure_id = s.structure_id "
        "LEFT JOIN provenance p ON p.structure_id = s.structure_id "
        "LEFT JOIN text_docs td ON td.structure_id = s.structure_id "
        "LEFT JOIN text_embeddings te ON te.text_doc_id = td.id "
        "LEFT JOIN structure_fingerprints fp ON fp.structure_id = s.structure_id "
        "WHERE m.formula IS NOT NULL AND TRIM(m.formula) != '' "
        "GROUP BY s.structure_id"
    ).fetchall()
    conn.close()

    materials: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        formula = canonical_formula(row["formula"])
        if not formula:
            continue
        _, counts = parse_formula_counts(formula)
        elements = sorted(counts.keys())
        entry = materials.setdefault(
            formula,
            {
                "formula": formula,
                "elements": elements,
                "crystaldb_count": 0,
                "representative_structure_ids": [],
                "representative_material_ids": [],
                "has_robocrys_text_count": 0,
                "has_text_doc_count": 0,
                "has_embedding_count": 0,
                "has_fingerprint_count": 0,
                "cif_stored_count": 0,
                "export_allowed_count": 0,
                "raw_formulas": set(),
            },
        )
        entry["elements"] = sorted(set(entry["elements"]) | set(elements))
        entry["raw_formulas"].add(row["formula"])
        entry["crystaldb_count"] += 1
        if len(entry["representative_structure_ids"]) < 5:
            entry["representative_structure_ids"].append(row["structure_id"])
        if row["source_id"] and len(entry["representative_material_ids"]) < 5:
            entry["representative_material_ids"].append(row["source_id"])
        entry["has_robocrys_text_count"] += int(row["has_robocrys_text"] or 0)
        entry["has_text_doc_count"] += int(row["has_text_doc"] or 0)
        entry["has_embedding_count"] += int(row["has_embedding"] or 0)
        entry["has_fingerprint_count"] += int(row["has_fingerprint"] or 0)
        entry["cif_stored_count"] += 1 if row["cif_text"] is not None else 0
        entry["export_allowed_count"] += 1 if row["allow_export"] not in (None, 0, False) else 0

    for entry in materials.values():
        entry["raw_formulas"] = sorted(entry["raw_formulas"])
    return materials


def select_roots(elements: Sequence[str], formula: str, pot_roots: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    pairs = set(required_pairs(elements))
    compatible = []
    best_missing: Optional[List[str]] = None
    for root in pot_roots:
        if not root.get("compat_passed"):
            continue
        missing = sorted(pairs - set(root.get("pairs") or []))
        if not missing:
            compatible.append(root)
        if best_missing is None or len(missing) < len(best_missing):
            best_missing = missing

    def root_sort(root: Dict[str, Any]) -> Tuple[int, int, str]:
        root_elements = set(root.get("elements") or [])
        target = set(elements)
        exact = root_elements == target
        coas_exact = formula == "CoAs2" and root_elements == {"As", "Co"}
        abo3_family = "O" in target and len(target) == 3 and "ABO3" in str(root.get("name") or "")
        family_priority = 0 if coas_exact else 1 if abo3_family else 2
        return (family_priority, 0 if exact else len(root_elements), str(root.get("timestamp_utc") or root.get("run_id")))

    compatible.sort(key=root_sort)
    return compatible, best_missing or sorted(pairs)


def pot_root_family(root: Optional[Dict[str, Any]], elements: Sequence[str], formula: str) -> str:
    if not root:
        return "unknown"
    root_elements = set(root.get("elements") or [])
    target = set(elements)
    name = str(root.get("name") or "")
    if root_elements == target:
        return "exact"
    if "ABO3" in name and "O" in target and len(target) == 3:
        return "ABO3_family"
    if len(root_elements) > len(target):
        return "broad"
    return "unknown"


def root_specificity_score(family: str) -> int:
    return {"exact": 100, "ABO3_family": 80, "broad": 45, "unknown": 20}.get(family, 20)


def material_family_match(formula: str, elements: Sequence[str], family: str) -> bool:
    if formula == "CoAs2" and family == "exact":
        return True
    if family == "ABO3_family" and "O" in elements and len(elements) == 3:
        return True
    if family == "broad":
        return False
    return family == "exact"


def formula_commonness_score(formula: str, elements: Sequence[str], atoms: int) -> int:
    score = COMMON_FORMULA_BONUS.get(formula, 0)
    if "O" in elements:
        score += 18
    if "S" in elements:
        score += 10
    if "As" in elements:
        score += 8
    if all(element in DEMO_FRIENDLY_ELEMENTS for element in elements):
        score += 12
    if 2 <= len(elements) <= 3:
        score += 12
    if atoms <= 6:
        score += 10
    elif atoms <= 12:
        score += 4
    return min(100, score)


def exclusion_reasons_for(base: Dict[str, Any], compatible: List[Dict[str, Any]], family: str) -> List[str]:
    reasons = []
    if not base.get("has_exact_reduced_formula"):
        reasons.append("no_exact_crystaldb_reduced_formula")
    if not base.get("representative_structure_ids"):
        reasons.append("no_representative_structure_id")
    if base.get("number_of_elements", 0) > 4:
        reasons.append("too_many_elements_for_first_smoke_suite")
    if base.get("total_atoms_reduced_formula", 0) > 16:
        reasons.append("large_reduced_formula")
    if base.get("contains_radioactive_or_unwanted_elements"):
        reasons.append("contains_radioactive_or_unwanted_elements")
    if not base.get("has_robocrys_text"):
        reasons.append("no_robocrys_text")
    if not base.get("has_embedding_text_doc"):
        reasons.append("no_embedding_or_text_doc")
    if not base.get("has_fingerprint"):
        reasons.append("no_fingerprint")
    if not compatible:
        reasons.append("no_compatible_pot_root")
    if family == "broad":
        reasons.append("broad_pot_root_not_demo_specific")
    if not base.get("demo_export_possible"):
        reasons.append("no_export_path_even_in_demo_mode")
    return reasons


def score_candidate(entry: Dict[str, Any], pot_roots: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    formula = entry["formula"]
    elements = sorted(entry["elements"])
    atoms = total_atoms(formula)
    pairs = required_pairs(elements)
    compatible, missing_pairs = select_roots(elements, formula, pot_roots)
    selected = compatible[0] if compatible else None
    family = pot_root_family(selected, elements, formula)
    family_match = material_family_match(formula, elements, family)
    commonness = formula_commonness_score(formula, elements, atoms)
    contains_bad = bool(set(elements) & RADIOACTIVE_OR_UNWANTED)
    base = {
        "formula": formula,
        "crystaldb_count": entry["crystaldb_count"],
        "has_exact_reduced_formula": entry["crystaldb_count"] > 0,
        "representative_structure_ids": entry["representative_structure_ids"],
        "representative_material_ids": entry["representative_material_ids"],
        "has_robocrys_text": entry["has_robocrys_text_count"] > 0,
        "has_embedding_text_doc": entry["has_text_doc_count"] > 0 and entry["has_embedding_count"] > 0,
        "has_fingerprint": entry["has_fingerprint_count"] > 0,
        "export_allowed_count": entry["export_allowed_count"],
        "demo_export_possible": entry["cif_stored_count"] > 0,
        "formula_commonness_score": commonness,
        "number_of_elements": len(elements),
        "total_atoms_reduced_formula": atoms,
        "contains_radioactive_or_unwanted_elements": contains_bad,
        "elements": elements,
        "required_pairs": pairs,
        "compatible_pot_roots": [root["spp_root"] for root in compatible],
        "selected_pot_root": selected["spp_root"] if selected else None,
        "pot_root_family": family,
        "pot_pair_coverage_complete": bool(compatible),
        "missing_pairs": [] if compatible else missing_pairs,
        "candidate_roots_checked": len(pot_roots),
        "root_specificity_score": root_specificity_score(family),
        "material_family_match": family_match,
    }
    reasons = exclusion_reasons_for(base, compatible, family)
    confidence = 0
    confidence += 20 if base["has_exact_reduced_formula"] else 0
    confidence += min(15, entry["crystaldb_count"] * 5)
    confidence += 10 if base["has_robocrys_text"] else 0
    confidence += 10 if base["has_embedding_text_doc"] else 0
    confidence += 10 if base["has_fingerprint"] else 0
    confidence += 20 if compatible else 0
    confidence += min(10, base["root_specificity_score"] // 10)
    confidence += 5 if base["demo_export_possible"] else 0
    if contains_bad:
        confidence -= 35
    if len(elements) > 4:
        confidence -= 20
    if atoms > 16:
        confidence -= 12
    confidence = max(0, min(100, confidence))

    demo_quality = 0
    demo_quality += int(commonness * 0.65)
    demo_quality += 18 if formula in MANUALLY_VERIFIED else 0
    demo_quality += 12 if formula in COMMON_FORMULA_BONUS else 0
    demo_quality += 14 if family_match else 0
    demo_quality += 10 if family == "exact" else 6 if family == "ABO3_family" else 0
    demo_quality += 8 if 2 <= len(elements) <= 3 else 0
    demo_quality += 8 if atoms <= 8 else 3 if atoms <= 16 else 0
    demo_quality += min(8, entry["crystaldb_count"] * 3)
    if contains_bad:
        demo_quality -= 45
    if family == "broad" and formula not in MANUALLY_VERIFIED:
        demo_quality -= 8 if commonness >= 60 else 20
    if "no_compatible_pot_root" in reasons:
        demo_quality -= 35
    if "no_exact_crystaldb_reduced_formula" in reasons:
        demo_quality -= 40
    demo_quality = max(0, min(100, demo_quality))

    if not base["has_exact_reduced_formula"]:
        stage = "negative_control"
    elif not compatible:
        stage = "spp_block_candidate"
    elif confidence >= 80 and demo_quality >= 55 and not contains_bad and len(elements) <= 4:
        stage = "full_success_candidate"
    elif compatible:
        stage = "qlip_risk_candidate"
    else:
        stage = "retrieval_only_candidate"

    base.update(
        {
            "expected_stage": stage,
            "confidence_score_0_100": confidence,
            "demo_quality_score_0_100": demo_quality,
            "exclusion_reasons": reasons,
        }
    )
    return base


def missing_formula_candidate(formula: str, pot_roots: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    _, counts = parse_formula_counts(formula)
    elements = sorted(counts.keys())
    pairs = required_pairs(elements) if elements else []
    compatible, missing_pairs = select_roots(elements, formula, pot_roots) if elements else ([], [])
    selected = compatible[0] if compatible else None
    family = pot_root_family(selected, elements, formula)
    return {
        "formula": formula,
        "crystaldb_count": 0,
        "has_exact_reduced_formula": False,
        "representative_structure_ids": [],
        "representative_material_ids": [],
        "has_robocrys_text": False,
        "has_embedding_text_doc": False,
        "has_fingerprint": False,
        "export_allowed_count": 0,
        "demo_export_possible": False,
        "formula_commonness_score": formula_commonness_score(formula, elements, total_atoms(formula)) if elements else 0,
        "number_of_elements": len(elements),
        "total_atoms_reduced_formula": total_atoms(formula) if elements else 0,
        "contains_radioactive_or_unwanted_elements": bool(set(elements) & RADIOACTIVE_OR_UNWANTED),
        "elements": elements,
        "required_pairs": pairs,
        "compatible_pot_roots": [root["spp_root"] for root in compatible],
        "selected_pot_root": selected["spp_root"] if selected else None,
        "pot_root_family": family,
        "pot_pair_coverage_complete": bool(compatible),
        "missing_pairs": [] if compatible else missing_pairs,
        "candidate_roots_checked": len(pot_roots),
        "root_specificity_score": root_specificity_score(family),
        "material_family_match": False,
        "expected_stage": "negative_control",
        "confidence_score_0_100": 0,
        "demo_quality_score_0_100": 0,
        "exclusion_reasons": ["no_exact_crystaldb_reduced_formula", "no_representative_structure_id"],
    }


def prompt_for_complete(formula: str) -> str:
    family_hint = {
        "CaTiO3": "perovskite-like oxide",
        "BaTiO3": "perovskite-like oxide",
        "CoAs2": "safflorite-like arsenide",
        "Al2O3": "corundum-like oxide",
        "Fe2O3": "iron oxide",
        "CoO": "cobalt oxide",
        "CeO2": "ceria-like oxide",
    }.get(formula, "crystal")
    article = "an" if formula[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
    return (
        f"Generate {article} {formula} {family_hint} candidate using retrieved structural analogues, "
        "SPP-derived POT guidance, QLIP optimisation, and novelty checking."
    )


def prompt_for_partial(formula: str, reason: str) -> str:
    clean_reason = reason.rstrip(".")
    return (
        f"Attempt a {formula} workflow and stop truthfully when blocked: retrieve Crystal-DB analogues, "
        f"check SPP POT-root compatibility, then report why QLIP handoff should not proceed. Expected block: {clean_reason}."
    )


def expected_workflow_for(candidate: Dict[str, Any]) -> Dict[str, str]:
    if candidate["expected_stage"] == "full_success_candidate":
        return {
            "retrieval": "pass",
            "spp": "pass",
            "qlip_validate": "pass",
            "qlip_solve": "pass_or_risk",
            "novelty": "pass",
        }
    if candidate["expected_stage"] == "spp_block_candidate":
        return {
            "retrieval": "pass",
            "spp": "blocked_missing_pot_pairs",
            "qlip_validate": "not_run",
            "qlip_solve": "not_run",
            "novelty": "not_run_or_retrieval_only",
        }
    return {
        "retrieval": "blocked_or_clarify",
        "spp": "not_run",
        "qlip_validate": "not_run",
        "qlip_solve": "not_run",
        "novelty": "not_run",
    }


def test_record(candidate: Dict[str, Any], prompt: str, reason: str) -> Dict[str, Any]:
    return {
        "formula": candidate["formula"],
        "prompt": prompt,
        "confidence_score_0_100": candidate["confidence_score_0_100"],
        "demo_quality_score_0_100": candidate["demo_quality_score_0_100"],
        "reason": reason,
        "expected_workflow": expected_workflow_for(candidate),
        "evidence": {
            "crystaldb_count": candidate["crystaldb_count"],
            "representative_ids": candidate["representative_structure_ids"],
            "representative_material_ids": candidate["representative_material_ids"],
            "selected_pot_root": candidate["selected_pot_root"],
            "required_pairs": candidate["required_pairs"],
            "pot_root_family": candidate["pot_root_family"],
            "missing_pairs": candidate["missing_pairs"],
            "export_allowed_count": candidate["export_allowed_count"],
            "demo_export_possible": candidate["demo_export_possible"],
            "exclusion_reasons": candidate["exclusion_reasons"],
        },
    }


def run_expectation_fields(
    *,
    outcome: str,
    min_score: Optional[int] = None,
    error_codes: Optional[Sequence[str]] = None,
    failure_family: Optional[str] = None,
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {
        "expected_outcome": outcome,
        "expected_final_status": outcome,
    }
    if min_score is not None:
        fields["expected_min_overall_score"] = min_score
    if error_codes:
        fields["expected_error_codes"] = list(error_codes)
    if failure_family:
        fields["expected_failure_family"] = failure_family
    return fields


def choose_complete(candidates: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for formula in PREFERRED_COMPLETE:
        item = candidates.get(formula)
        if (
            item
            and formula in DEMONSTRATED_COMPLETE
            and item["expected_stage"] in {"full_success_candidate", "qlip_risk_candidate"}
        ):
            reason = "High-confidence concrete material with Crystal-DB evidence and complete compatible POT coverage."
            if item["pot_root_family"] == "ABO3_family":
                reason += " Uses the published ABO3-family root with complete required-pair coverage."
            if item["pot_root_family"] == "exact":
                reason += " Uses an exact/narrow published POT root."
            selected.append(test_record(item, prompt_for_complete(formula), reason))
    return selected


def choose_partials(candidates: Dict[str, Dict[str, Any]], pot_roots: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for formula in EXPECTED_PARTIAL + ["Al2O3", "Fe2O3"]:
        item = candidates.get(formula) or missing_formula_candidate(formula, pot_roots)
        if item["expected_stage"] == "full_success_candidate" and formula not in {"Al2O3", "Fe2O3"}:
            continue
        if not item["has_exact_reduced_formula"]:
            reason = "No exact reduced-formula Crystal-DB entry in the active DB."
        elif not item["pot_pair_coverage_complete"]:
            reason = "Crystal-DB has entries, but published POT roots are missing required pairs."
        else:
            reason = (
                "Candidate has static Crystal-DB/POT-like evidence, but no configured-run evidence yet proves "
                "that SPP emits a solve-compatible QLIP request_ref."
            )
        selected.append(test_record(item, prompt_for_partial(formula, reason), reason))
    return selected


def build_edge_tests() -> List[Dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "formula": item["formula"],
            "prompt": item["prompt"],
            "reason": item["reason"],
            "expected_outcome": item.get("expected_outcome", "blocked_or_partial"),
            "expected_error_codes": item.get("expected_error_codes", []),
            "expected_failure_family": item.get("expected_failure_family"),
            "expected_workflow": {
                "retrieval": "blocked_or_clarify",
                "spp": "not_run",
                "qlip_validate": "not_run",
                "qlip_solve": "not_run",
                "novelty": "not_run",
            },
        }
        for item in EDGE_CASES
    ]


def build_smoke_suite(
    complete: Sequence[Dict[str, Any]],
    partial: Sequence[Dict[str, Any]],
    edges: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    runs = []
    for item in complete[:5]:
        min_score = max(80, min(95, int(item["demo_quality_score_0_100"])))
        runs.append(
            {
                "id": f"{formula_id(item['formula'])}_expected_complete",
                "material_system": item["formula"],
                "goal": item["prompt"],
                **run_expectation_fields(outcome="completed", min_score=min_score),
            }
        )
    for item in partial:
        runs.append(
            {
                "id": f"{formula_id(item['formula'])}_expected_partial",
                "material_system": item["formula"],
                "goal": item["prompt"],
                **run_expectation_fields(
                    outcome="blocked_or_partial",
                    error_codes=EXPECTED_PARTIAL_ERROR_CODES.get(item["formula"], ["spp_request_ref_unavailable"]),
                    failure_family="missing_pot_or_request_ref",
                ),
            }
        )
    for item in edges[:2]:
        runs.append(
            {
                "id": item["id"],
                "material_system": item["formula"],
                "goal": item["prompt"],
                **run_expectation_fields(
                    outcome=item.get("expected_outcome", "blocked_or_partial"),
                    error_codes=item.get("expected_error_codes"),
                    failure_family=item.get("expected_failure_family"),
                ),
            }
        )
    return {
        "schema_version": "skill_loop.smoke_suite.v1",
        "suite_name": "material_capability_smoke_v1",
        "runs": runs,
    }


def build_markdown(payload: Dict[str, Any], smoke_suite_path: Path) -> str:
    lines = [
        "# Material Test Candidate Audit",
        "",
        "## 1. Executive summary",
        "",
        f"- Scanned DB: `{payload['inputs']['db_path']}`",
        f"- Scanned SPP roots: `{payload['inputs']['spp_runs_dir']}`",
        f"- Candidates scored: {payload['summary']['candidate_count']}",
        f"- Full-success candidates: {payload['summary']['full_success_candidate_count']}",
        f"- SPP-block candidates: {payload['summary']['spp_block_candidate_count']}",
        "",
        "This v2 audit is deliberately stricter than pair coverage. It scores exact reduced-formula presence, representative IDs, robocrys/text embedding/fingerprint evidence, export policy, formula sanity, element risk, POT-root specificity, and demo usefulness.",
        "",
        "## 2. Recommended final smoke suite",
        "",
    ]
    for idx, item in enumerate(payload["expected_complete_tests"], start=1):
        lines.append(f"{idx}. Expected complete: `{item['formula']}` - {item['prompt']}")
    for idx, item in enumerate(payload["expected_partial_tests"], start=1):
        lines.append(f"{idx}. Expected partial: `{item['formula']}` - {item['reason']}")
    for idx, item in enumerate(payload["edge_case_tests"], start=1):
        lines.append(f"{idx}. Edge case: `{item['formula']}` - {item['reason']}")

    def table(items: Sequence[Dict[str, Any]]) -> List[str]:
        out = [
            "| formula | confidence | demo quality | selected root family | representative IDs | reason |",
            "|---|---:|---:|---|---|---|",
        ]
        for item in items:
            ev = item.get("evidence") or {}
            reps = ", ".join(ev.get("representative_ids") or [])
            out.append(
                f"| {item['formula']} | {item.get('confidence_score_0_100', '')} | "
                f"{item.get('demo_quality_score_0_100', '')} | {ev.get('pot_root_family', '')} | "
                f"{reps} | {item['reason']} |"
            )
        return out

    lines.extend(["", "## 3. Expected-complete tests", "", *table(payload["expected_complete_tests"])])
    lines.extend(["", "## 4. Expected-partial tests", "", *table(payload["expected_partial_tests"])])
    lines.extend(["", "## 5. Edge cases", ""])
    for item in payload["edge_case_tests"]:
        lines.append(f"- `{item['formula']}`: {item['prompt']} Reason: {item['reason']}")
    lines.extend(["", "## 6. Excluded but tempting candidates", "", "| formula | reasons | note |", "|---|---|---|"])
    for item in payload["excluded_candidates"][:25]:
        lines.append(
            f"| {item['formula']} | {', '.join(item['exclusion_reasons'])} | "
            f"confidence={item['confidence_score_0_100']}, demo_quality={item['demo_quality_score_0_100']} |"
        )
    lines.extend(
        [
            "",
            "## 7. Why ZnS/LiCoO2 should remain negative/blocked for now",
            "",
            "`ZnS` and `LiCoO2` should not be used as expected-complete demos against `data\\phase6_mp_10k.db`: the audit found no exact reduced-formula Crystal-DB entries for either material. Because the workflow is Crystal-DB retrieval -> SPP handoff -> QLIP, they are blocked before a truthful QLIP handoff. They are useful negative controls until matching Crystal-DB entries and compatible published POT roots are available.",
            "",
            "## 8. Exact PowerShell smoke-suite command for Skill-Loop-CSP",
            "",
            "```powershell",
            "$suite = Get-Content C:\\Users\\brown\\Documents\\GitHub\\Crystal-DB\\artifacts\\skill_loop_smoke_suite.json | ConvertFrom-Json",
            "Set-Location C:\\Users\\brown\\Documents\\GitHub\\Skill-Loop-CSP",
            "foreach ($run in $suite.runs) {",
            "  python -m sok_llm_orchestrator.cli --config my_live_config.yaml --workspace test_workdir\\material_capability_smoke_v1 run --mode live --with-spp true --query $run.goal",
            "}",
            "```",
            "",
            f"Ready-to-run suite file: `{smoke_suite_path}`",
        ]
    )
    return "\n".join(lines) + "\n"


def build_payload(db_path: Path, spp_runs: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    evidence = load_crystaldb_evidence(db_path)
    roots = load_pot_roots(spp_runs)
    scored = {formula: score_candidate(entry, roots) for formula, entry in evidence.items()}
    complete = choose_complete(scored)
    partial = choose_partials(scored, roots)
    edges = build_edge_tests()
    complete_formulas = {item["formula"] for item in complete}
    partial_formulas = {item["formula"] for item in partial}
    excluded = [
        item
        for item in scored.values()
        if item["formula"] not in complete_formulas
        and item["formula"] not in partial_formulas
        and (
            item["exclusion_reasons"]
            or item["demo_quality_score_0_100"] < 55
            or item["expected_stage"] != "full_success_candidate"
        )
    ]
    for formula in ["TiO2", "ZnO", "ZnS", "LiCoO2", "Ba5Ga6", "Ac2O3", "AcCu3"]:
        if formula not in scored:
            excluded.append(missing_formula_candidate(formula, roots))
    excluded.sort(key=lambda item: (item["formula"] not in {"TiO2", "ZnO", "ZnS", "LiCoO2", "Ba5Ga6", "Ac2O3", "AcCu3"}, -item["demo_quality_score_0_100"], item["formula"]))

    payload = {
        "schema_version": "crystaldb.material_test_candidate_audit.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "db_path": str(db_path.resolve()),
            "spp_runs_dir": str(spp_runs.resolve()),
            "previous_audit_json": str((REPO_ROOT / "artifacts" / "material_capability_audit.json").resolve()),
        },
        "summary": {
            "candidate_count": len(scored),
            "full_success_candidate_count": sum(1 for item in scored.values() if item["expected_stage"] == "full_success_candidate"),
            "retrieval_only_candidate_count": sum(1 for item in scored.values() if item["expected_stage"] == "retrieval_only_candidate"),
            "spp_block_candidate_count": sum(1 for item in scored.values() if item["expected_stage"] == "spp_block_candidate"),
            "qlip_risk_candidate_count": sum(1 for item in scored.values() if item["expected_stage"] == "qlip_risk_candidate"),
            "negative_control_count": sum(1 for item in scored.values() if item["expected_stage"] == "negative_control"),
            "normal_export_allowed_formulas": sum(1 for item in scored.values() if item["export_allowed_count"] > 0),
            "demo_export_possible_formulas": sum(1 for item in scored.values() if item["demo_export_possible"]),
        },
        "expected_complete_tests": complete,
        "expected_partial_tests": partial,
        "edge_case_tests": edges,
        "excluded_candidates": excluded[:200],
    }
    return payload, build_smoke_suite(complete, partial, edges)


def write_outputs(payload: Dict[str, Any], suite: Dict[str, Any], json_out: Path, md_out: Path, suite_out: Path) -> None:
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    suite_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    suite_out.write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")
    md_out.write_text(build_markdown(payload, suite_out.resolve()), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--spp-runs", default=str(DEFAULT_SPP_RUNS))
    parser.add_argument("--json-out", default=str(JSON_OUT))
    parser.add_argument("--md-out", default=str(MD_OUT))
    parser.add_argument("--suite-out", default=str(SMOKE_SUITE_OUT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload, suite = build_payload(Path(args.db), Path(args.spp_runs))
    write_outputs(payload, suite, Path(args.json_out), Path(args.md_out), Path(args.suite_out))
    print(
        json.dumps(
            {
                "json_out": args.json_out,
                "md_out": args.md_out,
                "suite_out": args.suite_out,
                "expected_complete": [item["formula"] for item in payload["expected_complete_tests"]],
                "expected_partial": [item["formula"] for item in payload["expected_partial_tests"]],
                "edge_cases": [item["formula"] for item in payload["edge_case_tests"]],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
