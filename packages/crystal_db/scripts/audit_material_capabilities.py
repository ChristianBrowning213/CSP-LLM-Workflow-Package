#!/usr/bin/env python3
"""Audit Crystal-DB material systems against published SPP POT roots.

This script is intentionally read-only for databases and SPP artifacts. It
summarizes which concrete Crystal-DB formulas have both database coverage and
complete published POT-pair coverage for a Crystal-DB -> SPP -> QLIP workflow.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import reduce
from math import gcd
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "phase6_mp_10k.db"
DEFAULT_SPP_RUNS = Path(r"C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP\QLIP_Outputs\SPP\runs")
DEFAULT_JSON_OUT = REPO_ROOT / "artifacts" / "material_capability_audit.json"
DEFAULT_MD_OUT = REPO_ROOT / "docs" / "material_capability_audit.md"

KNOWN_FAMILY_PRIORITY = {
    "CoAs2": 0,
    "TiO2": 1,
    "CaTiO3": 2,
    "ZnO": 3,
}

EXPECTED_COMPLETE_TARGETS = ["CoAs2", "CaTiO3", "TiO2", "ZnO"]
EXPECTED_PARTIAL_TARGETS = ["ZnS", "LiCoO2"]
EDGE_CASE_TARGETS = ["ABO3", "UnobtainiumO2"]

FORMULA_TOKEN_RE = re.compile(r"([A-Z][a-z]?)([0-9]*\.?[0-9]*)")


def parse_formula_counts(formula: str) -> Tuple[List[str], Counter]:
    """Parse simple formula strings such as 'CaTiO3' or 'Ca1 Ti1 O3'."""
    counts: Counter = Counter()
    order: List[str] = []
    for element, raw_count in FORMULA_TOKEN_RE.findall(formula or ""):
        if element not in counts:
            order.append(element)
        if raw_count in ("", "1", "1.0"):
            value = 1
        else:
            try:
                value = int(float(raw_count))
            except ValueError:
                value = 1
        counts[element] += value
    return order, counts


def canonical_formula(formula: str) -> str:
    order, counts = parse_formula_counts(formula)
    if not order:
        return (formula or "").replace(" ", "")
    divisor = reduce(gcd, [int(counts[element]) for element in order], 0)
    if divisor <= 0:
        divisor = 1
    parts = []
    for element in order:
        count = int(counts[element]) // divisor
        parts.append(element if count == 1 else f"{element}{count}")
    return "".join(parts)


def elements_from_formula_or_csv(formula: str, elements_csv: Optional[str]) -> List[str]:
    if elements_csv:
        values = [item for item in elements_csv.strip(",").split(",") if item]
        if values:
            return sorted(set(values))
    _, counts = parse_formula_counts(formula)
    return sorted(counts.keys())


def required_pairs(elements: Sequence[str]) -> List[str]:
    values = sorted(set(elements))
    return [f"{a}-{b}" for a, b in itertools.combinations_with_replacement(values, 2)]


def pair_name(a: str, b: str) -> str:
    x, y = sorted([str(a), str(b)])
    return f"{x}-{y}"


def load_crystaldb_materials(db_path: Path) -> Dict[str, Dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Crystal-DB SQLite database not found: {db_path}")
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT m.formula, m.elements_csv, COUNT(*) AS count, "
        "SUM(CASE WHEN s.cif_text IS NOT NULL THEN 1 ELSE 0 END) AS cif_stored_count, "
        "SUM(CASE WHEN COALESCE(p.allow_export, 0) != 0 THEN 1 ELSE 0 END) AS export_allowed_count "
        "FROM metadata m "
        "JOIN structures s ON s.structure_id = m.structure_id "
        "LEFT JOIN provenance p ON p.structure_id = m.structure_id "
        "WHERE m.formula IS NOT NULL AND TRIM(m.formula) != '' "
        "GROUP BY m.formula, m.elements_csv"
    ).fetchall()
    conn.close()

    materials: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        formula = canonical_formula(row["formula"])
        if not formula:
            continue
        elements = elements_from_formula_or_csv(row["formula"], row["elements_csv"])
        entry = materials.setdefault(
            formula,
            {
                "formula": formula,
                "elements": elements,
                "crystaldb_count": 0,
                "cif_stored_count": 0,
                "export_allowed_count": 0,
            },
        )
        entry["elements"] = sorted(set(entry["elements"]) | set(elements))
        entry["crystaldb_count"] += int(row["count"] or 0)
        entry["cif_stored_count"] += int(row["cif_stored_count"] or 0)
        entry["export_allowed_count"] += int(row["export_allowed_count"] or 0)
    return materials


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def compat_passed(run_dir: Path) -> Tuple[bool, Optional[int], Optional[int]]:
    meta = read_json(run_dir / "publish_meta.json") or {}
    compat = ((meta.get("checks") or {}).get("compat") or {})
    failed = compat.get("failed")
    passed = compat.get("passed")
    if failed is not None:
        return int(failed) == 0, int(passed or 0), int(failed or 0)
    report = run_dir / "compat_report.txt"
    if report.exists():
        text = report.read_text(encoding="utf-8", errors="replace")
        match_passed = re.search(r"Passed:\s*(\d+)", text)
        match_failed = re.search(r"Failed:\s*(\d+)", text)
        failed_value = int(match_failed.group(1)) if match_failed else None
        passed_value = int(match_passed.group(1)) if match_passed else None
        if failed_value is not None:
            return failed_value == 0, passed_value, failed_value
    return False, None, None


def load_pot_roots(spp_runs_dir: Path) -> List[Dict[str, Any]]:
    if not spp_runs_dir.exists():
        raise FileNotFoundError(f"SPP runs directory not found: {spp_runs_dir}")
    roots: List[Dict[str, Any]] = []
    for run_dir in sorted(path for path in spp_runs_dir.iterdir() if path.is_dir()):
        root = run_dir / "spp_root"
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            manifest_path = run_dir / "manifest.json"
        manifest = read_json(manifest_path)
        if not manifest:
            continue
        pairs_payload = manifest.get("pairs") or []
        pairs: Set[str] = set()
        for item in pairs_payload:
            if not isinstance(item, dict):
                continue
            a = item.get("A")
            b = item.get("B")
            if a and b:
                pairs.add(pair_name(str(a), str(b)))
        passed_ok, compat_passed_count, compat_failed_count = compat_passed(run_dir)
        publish_meta = read_json(run_dir / "publish_meta.json") or {}
        roots.append(
            {
                "run_id": run_dir.name,
                "name": manifest.get("name") or publish_meta.get("name") or run_dir.name,
                "spp_root": str(root.resolve()),
                "manifest_path": str(manifest_path.resolve()),
                "pair_count": len(pairs),
                "pairs": sorted(pairs),
                "elements": sorted({part for pair in pairs for part in pair.split("-")}),
                "compat_passed": bool(passed_ok),
                "compat_passed_count": compat_passed_count,
                "compat_failed_count": compat_failed_count,
                "num_structures": manifest.get("num_structures"),
                "timestamp_utc": publish_meta.get("timestamp_utc"),
            }
        )
    return roots


def root_score(root: Dict[str, Any], elements: Sequence[str], formula: str) -> Tuple[int, int, str]:
    root_elements = set(root.get("elements") or [])
    target_elements = set(elements)
    exact = int(root_elements == target_elements)
    broad_penalty = len(root_elements) - len(target_elements)
    known_bonus = -10 if formula in KNOWN_FAMILY_PRIORITY and set(elements).issubset(root_elements) else 0
    return (-exact + known_bonus, broad_penalty, str(root.get("timestamp_utc") or root.get("run_id") or ""))


def classify_material(material: Dict[str, Any], pot_roots: List[Dict[str, Any]]) -> Dict[str, Any]:
    elements = sorted(material["elements"])
    pairs = required_pairs(elements)
    pair_set = set(pairs)
    compatible = []
    partial_missing: Dict[str, List[str]] = {}
    for root in pot_roots:
        root_pairs = set(root.get("pairs") or [])
        missing = sorted(pair_set - root_pairs)
        if root.get("compat_passed") and not missing:
            compatible.append(root)
        elif root.get("compat_passed"):
            partial_missing[root["run_id"]] = missing

    compatible.sort(key=lambda root: root_score(root, elements, material["formula"]))
    best = compatible[0] if compatible else None
    missing_pairs = [] if best else min(partial_missing.values(), key=len) if partial_missing else pairs
    if material["crystaldb_count"] <= 0:
        status = "blocked_no_crystaldb_entries"
    elif best:
        status = "likely_complete"
    elif pot_roots:
        status = "blocked_missing_pot_root"
    else:
        status = "unknown"

    notes = []
    if material.get("cif_stored_count", 0) <= 0:
        notes.append("No stored CIF text found for this formula in the selected database.")
    if material.get("export_allowed_count", 0) <= 0:
        notes.append("No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.")
    if best and len(best.get("elements") or []) > len(elements):
        notes.append("Best POT root is broad; pair coverage is complete but not composition-specific.")

    return {
        "formula": material["formula"],
        "has_crystaldb_entries": material["crystaldb_count"] > 0,
        "crystaldb_count": material["crystaldb_count"],
        "cif_stored_count": material.get("cif_stored_count", 0),
        "export_allowed_count": material.get("export_allowed_count", 0),
        "elements": elements,
        "required_pairs": pairs,
        "compatible_pot_roots": [root["spp_root"] for root in compatible],
        "best_pot_root": best["spp_root"] if best else None,
        "pot_pair_coverage_complete": bool(best),
        "missing_pairs": missing_pairs,
        "expected_workflow_status": status,
        "notes": notes,
    }


def rank_material(item: Dict[str, Any]) -> Tuple[int, int, int, int, str]:
    formula = item["formula"]
    known = KNOWN_FAMILY_PRIORITY.get(formula, 1000)
    complete = 0 if item["expected_workflow_status"] == "likely_complete" else 1
    simplicity = len(item.get("elements") or [])
    return (complete, known, simplicity, -int(item.get("crystaldb_count") or 0), formula)


def smoke_rank_material(item: Dict[str, Any]) -> Tuple[int, int, int, str]:
    formula = item["formula"]
    known = KNOWN_FAMILY_PRIORITY.get(formula, 1000)
    # Prefer concrete multi-element systems for workflow smoke tests.
    unary_penalty = 1 if len(item.get("elements") or []) < 2 else 0
    return (known, unary_penalty, -int(item.get("crystaldb_count") or 0), formula)


def blocked_rank(item: Dict[str, Any]) -> Tuple[int, int, str]:
    return (len(item.get("elements") or []), -int(item.get("crystaldb_count") or 0), item["formula"])


def prompt_for(formula: str, status: str, reason: str) -> Dict[str, str]:
    if status == "edge":
        prompt = reason
    else:
        prompt = (
            f"Generate a {formula} candidate using retrieved Crystal-DB analogues, "
            "SPP POT guidance, QLIP optimisation, and novelty checking."
        )
    return {"formula": formula, "prompt": prompt, "reason": reason}


def build_smoke_tests(materials_by_formula: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    tests: List[Dict[str, str]] = []
    for formula in EXPECTED_COMPLETE_TARGETS:
        item = materials_by_formula.get(formula)
        if item and item["expected_workflow_status"] == "likely_complete":
            tests.append(
                prompt_for(
                    formula,
                    "complete",
                    "Crystal-DB entries and complete published POT-pair coverage are available.",
                )
            )
    likely = [
        item
        for item in materials_by_formula.values()
        if item["expected_workflow_status"] == "likely_complete" and len(item.get("elements") or []) >= 2
    ]
    likely.sort(key=smoke_rank_material)
    for item in likely:
        if len([test for test in tests if test["formula"] == item["formula"]]) == 0 and len(tests) < 6:
            tests.append(
                prompt_for(
                    item["formula"],
                    "complete",
                    "Additional complete concrete formula with Crystal-DB entries and complete POT-pair coverage.",
                )
            )
    for formula in EXPECTED_PARTIAL_TARGETS:
        item = materials_by_formula.get(formula)
        if item and item["expected_workflow_status"] != "likely_complete":
            tests.append(
                prompt_for(
                    formula,
                    "partial",
                    "Crystal-DB has entries but no complete compatible published POT root is available.",
                )
            )
        elif not item:
            tests.append(
                prompt_for(
                    formula,
                    "partial",
                    "No exact reduced-formula Crystal-DB entries were found in the selected database; do not hand off to QLIP.",
                )
            )
    blocked = [
        item
        for item in materials_by_formula.values()
        if item["expected_workflow_status"] == "blocked_missing_pot_root" and len(item.get("elements") or []) >= 2
    ]
    blocked.sort(key=blocked_rank)
    for item in blocked:
        if len([test for test in tests if test["formula"] == item["formula"]]) == 0 and len(tests) < 10:
            tests.append(
                prompt_for(
                    item["formula"],
                    "partial",
                    "Crystal-DB has entries, but published POT-pair coverage is incomplete.",
                )
            )
    tests.append(
        prompt_for(
            "ABO3",
            "edge",
            "Ask for a generic ABO3 perovskite prototype without concrete A/B elements; expected behavior is to require a concrete composition before QLIP.",
        )
    )
    tests.append(
        prompt_for(
            "UnobtainiumO2",
            "edge",
            "Ask for UnobtainiumO2; expected behavior is blocked_no_crystaldb_entries and no POT-root handoff.",
        )
    )
    return tests[:12]


def top_table(items: Sequence[Dict[str, Any]], limit: int, status: Optional[str] = None) -> List[Dict[str, Any]]:
    selected = [item for item in items if status is None or item["expected_workflow_status"] == status]
    if status == "blocked_missing_pot_root":
        selected.sort(key=blocked_rank)
    else:
        selected.sort(key=rank_material)
    return selected[:limit]


def build_markdown(payload: Dict[str, Any]) -> str:
    materials = payload["materials"]
    roots = payload["pot_roots"]
    likely = top_table(materials, 25, "likely_complete")
    blocked = top_table(materials, 25, "blocked_missing_pot_root")

    def material_rows(rows: Sequence[Dict[str, Any]]) -> List[str]:
        out = ["| formula | elements | count | best_pot_root | missing_pairs | notes |", "|---|---|---:|---|---|---|"]
        for item in rows:
            root_name = Path(item["best_pot_root"]).parent.name if item.get("best_pot_root") else ""
            missing = ", ".join(item.get("missing_pairs") or [])
            notes = "; ".join(item.get("notes") or [])
            out.append(
                f"| {item['formula']} | {', '.join(item['elements'])} | {item['crystaldb_count']} | "
                f"{root_name} | {missing} | {notes} |"
            )
        return out

    lines = [
        "# Material Capability Audit",
        "",
        "## 1. Executive summary",
        "",
        f"Scanned Crystal-DB database: `{payload['inputs']['db_path']}`.",
        f"Scanned SPP runs directory: `{payload['inputs']['spp_runs_dir']}`.",
        "",
        f"- Unique concrete formulas in Crystal-DB: {payload['summary']['formula_count']}",
        f"- Likely end-to-end complete formulas: {payload['summary']['likely_complete_count']}",
        f"- Blocked by missing POT-root coverage: {payload['summary']['blocked_missing_pot_root_count']}",
        "",
        "A formula is marked `likely_complete` only when Crystal-DB has at least one entry and at least one published, compatibility-passing SPP root contains every unordered self/cross pair required by the formula element set.",
        "",
        "## 2. Likely end-to-end supported materials",
        "",
        *material_rows(likely),
        "",
        "## 3. Blocked materials and why",
        "",
        *material_rows(blocked),
        "",
        "## 4. Recommended smoke-test suite",
        "",
    ]
    for idx, test in enumerate(payload["recommended_smoke_tests"], start=1):
        lines.append(f"{idx}. `{test['formula']}`: {test['prompt']}")
        lines.append(f"   Reason: {test['reason']}")
    lines.extend(
        [
            "",
            "## 5. POT-root coverage summary",
            "",
            "| run_id | name | pairs | compat | elements_sample |",
            "|---|---|---:|---|---|",
        ]
    )
    for root in roots:
        sample = ", ".join((root.get("elements") or [])[:12])
        if len(root.get("elements") or []) > 12:
            sample += ", ..."
        lines.append(
            f"| {root['run_id']} | {root['name']} | {root['pair_count']} | "
            f"{root['compat_passed_count']} passed / {root['compat_failed_count']} failed | {sample} |"
        )
    lines.extend(
        [
            "",
            "## 6. Crystal-DB coverage summary",
            "",
            f"- Database structures represented in formula groups: {payload['summary']['structure_count']}",
            f"- Export-allowed entries represented in formula groups: {payload['summary']['export_allowed_entry_count']}",
            f"- Stored-CIF entries represented in formula groups: {payload['summary']['cif_stored_entry_count']}",
            "",
            "Top formulas by Crystal-DB count:",
            "",
            "| formula | elements | count | status |",
            "|---|---|---:|---|",
        ]
    )
    by_count = sorted(materials, key=lambda item: (-item["crystaldb_count"], item["formula"]))[:20]
    for item in by_count:
        lines.append(
            f"| {item['formula']} | {', '.join(item['elements'])} | {item['crystaldb_count']} | {item['expected_workflow_status']} |"
        )
    lines.extend(
        [
            "",
            "## 7. Next data-generation targets",
            "",
            "- Generate/publish narrow POT roots for high-priority blocked binaries and ternaries found in Crystal-DB.",
            "- Generate concrete roots for requested smoke-test systems that are currently unsupported, especially `ZnS` and `LiCoO2` if they remain product test cases.",
            "- Keep generic prototypes such as `ABO3` out of QLIP handoff until concrete A/B/O elements are selected.",
            "- Add a CI smoke matrix that uses only formulas marked `likely_complete` in this artifact.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_payload(db_path: Path, spp_runs_dir: Path) -> Dict[str, Any]:
    crystal_materials = load_crystaldb_materials(db_path)
    pot_roots = load_pot_roots(spp_runs_dir)
    materials = [classify_material(item, pot_roots) for item in crystal_materials.values()]
    materials.sort(key=rank_material)
    materials_by_formula = {item["formula"]: item for item in materials}
    requested_checks = []
    for formula in EXPECTED_COMPLETE_TARGETS + EXPECTED_PARTIAL_TARGETS + EDGE_CASE_TARGETS:
        if formula == "ABO3":
            requested_checks.append(
                {
                    "formula": formula,
                    "present_in_crystaldb": False,
                    "expected_workflow_status": "blocked_no_concrete_composition",
                    "notes": ["Prototype formula; concrete A/B elements are required before POT-root matching."],
                }
            )
            continue
        item = materials_by_formula.get(formula)
        if item:
            requested_checks.append(
                {
                    "formula": formula,
                    "present_in_crystaldb": True,
                    "expected_workflow_status": item["expected_workflow_status"],
                    "crystaldb_count": item["crystaldb_count"],
                    "elements": item["elements"],
                    "missing_pairs": item["missing_pairs"],
                    "best_pot_root": item["best_pot_root"],
                    "notes": item["notes"],
                }
            )
        else:
            requested_checks.append(
                {
                    "formula": formula,
                    "present_in_crystaldb": False,
                    "expected_workflow_status": "blocked_no_crystaldb_entries",
                    "notes": ["No exact reduced-formula entries in the selected Crystal-DB database."],
                }
            )
    summary = {
        "formula_count": len(materials),
        "structure_count": sum(item["crystaldb_count"] for item in materials),
        "cif_stored_entry_count": sum(item.get("cif_stored_count", 0) for item in materials),
        "export_allowed_entry_count": sum(item.get("export_allowed_count", 0) for item in materials),
        "likely_complete_count": sum(1 for item in materials if item["expected_workflow_status"] == "likely_complete"),
        "blocked_missing_pot_root_count": sum(
            1 for item in materials if item["expected_workflow_status"] == "blocked_missing_pot_root"
        ),
        "blocked_no_crystaldb_entries_count": 0,
        "pot_root_count": len(pot_roots),
    }
    return {
        "schema_version": "crystaldb.material_capability_audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "db_path": str(db_path.resolve()),
            "spp_runs_dir": str(spp_runs_dir.resolve()),
        },
        "summary": summary,
        "materials": materials,
        "recommended_smoke_tests": build_smoke_tests(materials_by_formula),
        "requested_system_checks": requested_checks,
        "pot_roots": [
            {key: value for key, value in root.items() if key != "pairs"}
            for root in pot_roots
        ],
    }


def write_outputs(payload: Dict[str, Any], json_out: Path, md_out: Path) -> None:
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    md_out.write_text(build_markdown(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Crystal-DB SQLite database to inspect read-only.")
    parser.add_argument("--spp-runs", default=str(DEFAULT_SPP_RUNS), help="SPP-Maker published runs directory.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT), help="JSON artifact path.")
    parser.add_argument("--md-out", default=str(DEFAULT_MD_OUT), help="Markdown report path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_payload(Path(args.db), Path(args.spp_runs))
    write_outputs(payload, Path(args.json_out), Path(args.md_out))
    print(
        json.dumps(
            {
                "json_out": args.json_out,
                "md_out": args.md_out,
                "formula_count": payload["summary"]["formula_count"],
                "likely_complete_count": payload["summary"]["likely_complete_count"],
                "blocked_missing_pot_root_count": payload["summary"]["blocked_missing_pot_root_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
