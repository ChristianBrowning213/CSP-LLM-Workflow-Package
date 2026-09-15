"""Select and hash-freeze the unseen scaffold-v2 holdout before generation."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

from pymatgen.core import Composition
from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sok_llm_orchestrator.workflow.paper_scaffolds_library_v2 import build_family_scaffold_alternatives  # noqa: E402


CRYSTAL_DB = REPO.parent / "Crystal-DB"
OUT = REPO / "artifacts" / "Paper_scaffolds_september" / "scaffold_v2" / "final_holdout"
METHOD_FREEZE = REPO / "artifacts" / "Paper_scaffolds_september" / "scaffold_v2" / "V2_METHOD_FREEZE.json"
DATABASES = {
    "ROCKSALT": CRYSTAL_DB / "artifacts/Paper_scaffolds_september/specialist_corpora/families/ROCKSALT/PAPER_SCAFFOLDS_ROCKSALT_V1/crystaldb.sqlite",
    "SPINEL": CRYSTAL_DB / "artifacts/Paper_scaffolds_september/specialist_corpora/families/SPINEL/PAPER_SCAFFOLDS_SPINEL_V1/crystaldb.sqlite",
    "LAYERED_O3": CRYSTAL_DB / "artifacts/Paper_scaffolds_september/specialist_corpora/families/LAYERED_OXIDE/PAPER_SCAFFOLDS_LAYERED_OXIDE_V1/crystaldb.sqlite",
    "OLIVINE": CRYSTAL_DB / "artifacts/Paper_scaffolds_september/specialist_corpora/olivine_v2/PAPER_SCAFFOLDS_OLIVINE_ORDERED_V2.sqlite",
}
FAMILY_TEXT = {"ROCKSALT": "rocksalt", "SPINEL": "spinel", "LAYERED_O3": "layered oxide", "OLIVINE": "olivine"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_formula(value: str) -> str | None:
    try:
        return Composition(value).reduced_formula
    except Exception:
        return None


def prior_formulas() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    output_root = REPO / "outputs" / "Paper_scaffolds_september"
    for path in output_root.rglob("structured_task.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("formula")
        except (OSError, json.JSONDecodeError):
            continue
        formula = canonical_formula(str(value or ""))
        if formula:
            found.setdefault(formula, set()).add(str(path.relative_to(REPO)))
    artifact_root = REPO / "artifacts" / "Paper_scaffolds_september"
    for path in artifact_root.rglob("*.csv"):
        lowered = path.name.lower()
        if "pool" in lowered or "corpus" in lowered:
            continue
        if not any(part in path.as_posix() for part in ("final_audit", "result_D_generalisation", "scaffold_development")):
            continue
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    value = row.get("formula") or row.get("target_formula") or row.get("composition")
                    formula = canonical_formula(str(value or ""))
                    if formula:
                        found.setdefault(formula, set()).add(str(path.relative_to(REPO)))
        except (OSError, UnicodeError, csv.Error):
            continue
    for path in (REPO / "tests").glob("test_paper_scaffolds*.py"):
        for token in re.findall(r'["\']([A-Z][A-Za-z0-9()]+)["\']', path.read_text(encoding="utf-8")):
            formula = canonical_formula(token)
            if formula:
                found.setdefault(formula, set()).add(str(path.relative_to(REPO)))
    return found


def valid_shape(policy: str, formula: str, space_group: str) -> bool:
    composition = Composition(formula).reduced_composition
    counts = sorted(round(float(value)) for value in composition.get_el_amt_dict().values())
    elements = {str(element) for element in composition.elements}
    if policy == "ROCKSALT":
        framework_anions = elements & {"O", "S", "Se", "Te", "N", "F", "Cl", "Br", "I"}
        return len(elements) == 2 and counts == [1, 1] and len(framework_anions) == 1
    if policy == "SPINEL":
        return elements.__contains__("O") and len(elements) == 3 and counts == [1, 2, 4]
    if policy == "LAYERED_O3":
        return space_group == "R-3m" and "O" in elements and bool(elements & {"Li", "Na"}) and len(elements) == 3 and counts == [1, 1, 2]
    if policy == "OLIVINE":
        return "O" in elements and len(elements) in {3, 4} and counts in ([1, 2, 4], [1, 1, 1, 4])
    return False


def candidates(prior: dict[str, set[str]]) -> list[dict[str, Any]]:
    rows = []
    for policy, database in DATABASES.items():
        if not database.is_file():
            raise FileNotFoundError(database)
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        query = """
            SELECT s.structure_id, s.reduced_formula, m.space_group, s.cif_text,
                   p.source, p.source_id, a.topology_tier, a.family_assignment
            FROM structures s
            JOIN metadata m ON m.structure_id=s.structure_id
            JOIN provenance p ON p.structure_id=s.structure_id
            LEFT JOIN structure_annotations a ON a.structure_id=s.structure_id
            ORDER BY s.reduced_formula, s.structure_id
        """
        seen = set()
        for structure_id, raw_formula, space_group, cif_text, source, source_id, tier, assignment in connection.execute(query):
            formula = canonical_formula(str(raw_formula))
            if not formula or formula in seen:
                continue
            seen.add(formula)
            if policy == "LAYERED_O3":
                structure = Structure.from_str(str(cif_text), fmt="cif")
                space_group = SpacegroupAnalyzer(structure, symprec=0.05, angle_tolerance=5).get_space_group_symbol()
            excluded = formula in prior
            reason = ";".join(sorted(prior.get(formula, set()))) if excluded else ""
            shape_ok = valid_shape(policy, formula, str(space_group or ""))
            former_count = len(set(Composition(formula).get_el_amt_dict()) & {"B", "Si", "Ge", "P", "As", "V"})
            representable = shape_ok and (policy != "OLIVINE" or former_count == 1)
            alternatives = {"ROCKSALT": 3, "SPINEL": 9, "LAYERED_O3": 9, "OLIVINE": 3}[policy] if representable else 0
            per_geometry = 1 if policy == "ROCKSALT" or len(Composition(formula).elements) == 3 else 2
            if policy == "SPINEL":
                per_geometry = 3
            elif policy == "LAYERED_O3":
                per_geometry = 2
            states = alternatives * per_geometry
            error = "" if representable else "formula/site-role preflight rejected"
            rows.append({
                "policy": policy, "formula": formula, "structure_id": structure_id,
                "source": source, "source_id": source_id, "space_group": space_group,
                "topology_tier": tier, "family_assignment": assignment,
                "database_path": str(database), "database_sha256": sha(database),
                "previously_used": excluded, "exclusion_evidence": reason,
                "shape_eligible": shape_ok, "v2_representable": representable,
                "geometry_alternatives": alternatives, "total_realisations": states,
                "representability_error": error,
            })
        connection.close()
    return rows


def diverse_select(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    remaining = list(rows)
    selected: list[dict[str, Any]] = []
    used_elements: set[str] = set()
    while remaining and len(selected) < count:
        def rank(row: dict[str, Any]) -> tuple[float, int, str]:
            elements = {str(element) for element in Composition(row["formula"]).elements}
            if not selected:
                distance = 1.0
            else:
                distance = min(1.0 - len(elements & {str(e) for e in Composition(item["formula"]).elements}) / len(elements | {str(e) for e in Composition(item["formula"]).elements}) for item in selected)
            return distance, len(elements - used_elements), hashlib.sha256(row["formula"].encode()).hexdigest()
        winner = max(remaining, key=rank)
        selected.append(winner)
        used_elements.update(str(element) for element in Composition(winner["formula"]).elements)
        remaining.remove(winner)
    return selected


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if not METHOD_FREEZE.is_file():
        raise FileNotFoundError("v2 must be frozen before holdout selection")
    OUT.mkdir(parents=True, exist_ok=True)
    final_path = OUT / "V2_HOLDOUT.csv"
    if final_path.exists():
        raise FileExistsError(f"holdout is already selected: {final_path}")
    prior = prior_formulas()
    pool = candidates(prior)
    selected = []
    for policy in DATABASES:
        eligible = [row for row in pool if row["policy"] == policy and not row["previously_used"] and row["shape_eligible"] and row["v2_representable"]]
        chosen = diverse_select(eligible, min(10, len(eligible)))
        if not chosen:
            raise RuntimeError(f"{policy} has no eligible unseen formulas")
        for index, row in enumerate(chosen, 1):
            verified = build_family_scaffold_alternatives({"formula": row["formula"], "family": FAMILY_TEXT[policy], "topology_subclass": "O3" if policy == "LAYERED_O3" else None})
            if len(verified) != row["geometry_alternatives"] or sum(item.feasible_state_count for item in verified) != row["total_realisations"]:
                raise RuntimeError(f"analytical representability mismatch for {policy}/{row['formula']}")
            selected.append({"row_id": f"V2H_{policy}_{index:02d}", **row, "target_reference_id": row["structure_id"], "exclude_target_reference": True})
    pool_path = OUT / "V2_HOLDOUT_SELECTION_POOL.csv"
    write_csv(pool_path, pool)
    write_csv(final_path, selected)
    freeze = {
        "schema_version": "paper_scaffolds_v2_holdout_freeze.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "method_freeze_sha256": sha(METHOD_FREEZE),
        "selection_pool_sha256": sha(pool_path),
        "holdout_sha256": sha(final_path),
        "selection_before_generation": True,
        "row_count": len(selected),
        "rows_per_policy": {policy: sum(row["policy"] == policy for row in selected) for policy in DATABASES},
        "no_replacements": True,
        "exclusion_formula_count": len(prior),
        "selection_rule": "eligible accepted ordered, exact formula unseen, frozen v2 representable; greedy max-min elemental Jaccard diversity with deterministic SHA tie-break",
    }
    freeze_path = OUT / "V2_HOLDOUT_FREEZE.json"
    freeze_path.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = ["# V2 unseen holdout selection", "", f"Selected and frozen **{len(selected)}** rows before generation: 10 each for ROCKSALT, SPINEL, and OLIVINE, plus every remaining eligible unseen LAYERED_O3 row (3). The accepted layered corpus contains only 3 unused R-3m/O3 formulas after prior frozen exclusions.", "", "Exact target structure IDs are retained solely to enforce retrieval exclusion and topology-subclass selection; target CIF coordinates/lattices are not exposed to scaffold construction. No replacements are permitted.", "", "| row | policy | formula | source structure | space group | v2 realisations |", "|---|---|---|---|---|---:|"]
    report.extend(f"| {row['row_id']} | {row['policy']} | {row['formula']} | {row['structure_id']} | {row['space_group']} | {row['total_realisations']} |" for row in selected)
    (OUT / "V2_HOLDOUT_SELECTION_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(freeze, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
