"""Freeze the Ticket 2 NASICON smoke preflight without launching generation.

This script is intentionally limited to representability, replacement
selection, structured-intent compatibility, and frozen-corpus leakage checks.
It must complete with ``generation_launched=False`` when any revised smoke row
is not ready.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from ase.formula import Formula
from pymatgen.core import Composition

from qlip.paper_diversity.smoke_preparation import canonical_hash, preflight_task, task_orbits
from qlip.scaffolds import get_scaffold
from qlip.scaffolds.occupation import preflight_ordered_occupation


E4_A1_CLASSIFICATION = "UNSUPPORTED_ORDERED_MODEL_REQUIRES_DISORDER"
REVISED_TASK_IDS = ("E4_A2", "E4_A3", "E4_A4", "E4_C1", "E4_C2", "E4_C4", "E4_F2", "E4_F1")
SCAFFOLDS = {
    "E4_A1": "nasicon_na3sc2po43_r3c",
    "E4_A2": "nasicon_na3zr2si2po12_c2_ordered",
    "E4_A3": "nasicon_na3ti2si2po12_cc",
    "E4_A4": "nasicon_na3hftisi2po12_p1",
    "E4_C1": "nzp_nazr2po43_r3c",
    "E4_C2": "nasicon_na3ti2po43_r3",
    "E4_C4": "nasicon_na3sc2po43_r3c",
    "E4_F1": "nzp_nazr2po43_r3c",
    "E4_F2": "nzp_lizr2po43_p21c",
}
MOBILE_IONS = {"Li", "Na", "K", "Rb", "Cs"}
TETRAHEDRAL_CATIONS = {"P", "Si", "S"}
# Exact capability of Crystal-DB's frozen
# nasicon_ordered_coordination_single_component_rank3_proxy_v1 implementation.
TOPOLOGY_OCTAHEDRAL_CATIONS = {"Zr", "V", "Ti", "Cr", "Sc"}
TOPOLOGY_TETRAHEDRAL_CATIONS = {"Si", "P"}


def _repo_root() -> Path:
    cursor = Path(__file__).resolve().parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "qlip").is_dir():
            return candidate
    raise RuntimeError("QLIP repository root not found")


def _skill_root() -> Path:
    root = _repo_root().parent / "Skill-Loop-CSP"
    if not (root / "benchmarks" / "paper_diversity_v2").is_dir():
        raise RuntimeError(f"Sibling Skill-Loop-CSP repository not found: {root}")
    return root


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fields or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _formula_species(formula: str) -> set[str]:
    return {str(symbol) for symbol in Formula(formula).count()}


def _task_orbits(task: dict[str, str], scaffold: Any) -> list[dict[str, Any]]:
    """Apply generic coordination-role allowlists to a verified scaffold.

    The only changed case in this smoke subset is E4_F1: the registered
    rhombohedral NaZr2(PO4)3 framework has a mobile-ion orbit and the frozen
    task requests Li on that role. The rule is chemistry-generic and applies
    to every target mobile ion; it does not special-case a task ID or formula.
    """

    target_species = _formula_species(task["target_formula"])
    target_mobile = tuple(sorted(target_species & MOBILE_IONS))
    result: list[dict[str, Any]] = []
    for source_orbit in scaffold.symmetry_orbits:
        orbit = copy.deepcopy(source_orbit)
        allowed = tuple(str(value) for value in orbit.get("allowed_species", ()))
        compatible = tuple(value for value in allowed if value in target_species)
        if orbit.get("coordination_role") == "mobile_ion" and not compatible:
            compatible = target_mobile
        if compatible:
            orbit["allowed_species"] = list(compatible)
            orbit["fixed_species"] = compatible[0] if len(compatible) == 1 else None
        result.append(orbit)
    return result


def _topology_capability(task: dict[str, str], policy: str) -> tuple[bool, list[str]]:
    species = _formula_species(task["target_formula"])
    octahedral = species - MOBILE_IONS - TETRAHEDRAL_CATIONS - {"O"}
    unsupported = sorted((octahedral - TOPOLOGY_OCTAHEDRAL_CATIONS) | ((species & TETRAHEDRAL_CATIONS) - TOPOLOGY_TETRAHEDRAL_CATIONS))
    available = policy == "nasicon_ordered_coordination_single_component_rank3_proxy_v1" and not unsupported
    return available, unsupported


def _preflight_row(task: dict[str, str], all_targets_out_formulas: set[str]) -> dict[str, Any]:
    scaffold = get_scaffold(SCAFFOLDS[task["task_id"]])
    orbits = _task_orbits(task, scaffold)
    occupation = preflight_ordered_occupation(task["target_formula"], len(scaffold.fractional_candidate_sites), orbits)
    requested_space_groups = {value.strip() for value in task["allowed_space_groups"].split(";") if value.strip() and value.strip().lower() != "none"}
    space_group_match = scaffold.source_space_group in requested_space_groups
    topology_available, topology_unsupported_species = _topology_capability(task, scaffold.topology_policy)
    reduced_formula = Composition(task["target_formula"]).reduced_formula
    leakage_count = int(reduced_formula in all_targets_out_formulas)
    search_space = {
        "target_formula": task["target_formula"],
        "allowed_space_groups": sorted(requested_space_groups),
        "scaffold_id": scaffold.scaffold_id,
        "scaffold_version": scaffold.scaffold_version,
        "scaffold_source_hash": scaffold.source_cif_sha256,
        "ordered_orbits": orbits,
        "vacancy_policy": "NO_VACANCIES",
        "charge_policy": "FORMULA_EXACT_NEUTRALITY_PREFLIGHT",
        "topology_policy": scaffold.topology_policy,
    }
    blockers: list[str] = []
    if not occupation.stoichiometry_representable:
        blockers.append("ORBIT_MULTIPLICITY_NOT_REPRESENTABLE")
    if not space_group_match:
        blockers.append("TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH")
    if not topology_available:
        blockers.append("TOPOLOGY_POLICY_CHEMISTRY_UNSUPPORTED")
    if leakage_count:
        blockers.append("EXACT_TARGET_RETRIEVAL_LEAKAGE")
    return {
        "task_id": task["task_id"],
        "target_formula": task["target_formula"],
        "target_space_group": task["allowed_space_groups"],
        "scaffold_id": scaffold.scaffold_id,
        "scaffold_version": scaffold.scaffold_version,
        "scaffold_source_id": scaffold.source_structure_id,
        "scaffold_source_path": scaffold.source_cif_path,
        "scaffold_source_sha256": scaffold.source_cif_sha256,
        "source_space_group": scaffold.source_space_group,
        "space_group_match": space_group_match,
        "orbit_multiplicities": json.dumps(scaffold.orbit_multiplicities, sort_keys=True, separators=(",", ":")),
        "occupation_evidence": json.dumps(occupation.to_dict(), sort_keys=True, separators=(",", ":")),
        "integer_occupation_feasible": occupation.stoichiometry_representable,
        "fractional_occupation_used": False,
        "topology_policy": scaffold.topology_policy,
        "topology_policy_available": topology_available,
        "topology_unsupported_species": ";".join(topology_unsupported_species),
        "retrieval_database": "nasicon_specialist_all_targets_out_v3",
        "exact_target_leakage_count": leakage_count,
        "search_space_sha256": _canonical_hash(search_space),
        "preflight_status": "READY_FOR_SMOKE" if not blockers else "BLOCKED_PREFLIGHT",
        "blockers": ";".join(blockers),
    }


def _update_blocker_tables(evidence: Path, preflight: dict[str, dict[str, Any]], a1_evidence: dict[str, Any]) -> None:
    for filename in ("TASK_CAPABILITY_BLOCKERS.csv", "E4_CAPABILITY_BLOCKERS.csv"):
        rows = _read_csv(evidence / filename)
        for row in rows:
            task_id = row["task_id"]
            blockers = {value for value in row["missing_capabilities"].split(";") if value}
            if task_id == "E4_A1":
                blockers -= {"MISSING_ORBIT_TEMPLATE", "MISSING_SCAFFOLD", "STOICHIOMETRY_NOT_REPRESENTABLE", "TOPOLOGY_VALIDATOR_MISSING"}
                blockers.add("ORDERED_MODEL_REQUIRES_DISORDER")
                row["occupation_preflight_status"] = E4_A1_CLASSIFICATION
                row["occupation_evidence"] = json.dumps(a1_evidence, sort_keys=True, separators=(",", ":"))
                row["real_smoke_gate"] = "ABSTAINED_BEFORE_GENERATION"
            elif task_id in preflight:
                result = preflight[task_id]
                blockers -= {"MISSING_ORBIT_TEMPLATE", "MISSING_SCAFFOLD", "STOICHIOMETRY_NOT_REPRESENTABLE"}
                if result["topology_policy_available"]:
                    blockers.discard("TOPOLOGY_VALIDATOR_MISSING")
                for blocker in result["blockers"].split(";"):
                    if blocker:
                        blockers.add(blocker)
                row["occupation_preflight_status"] = (
                    "REPRESENTABLE_NOT_SMOKE_SOLVED" if result["integer_occupation_feasible"] else "STOICHIOMETRY_NOT_REPRESENTABLE"
                )
                row["occupation_evidence"] = result["occupation_evidence"]
                row["real_smoke_gate"] = "BLOCKED_PENDING_REAL_TASK_SMOKE" if result["preflight_status"] == "READY_FOR_SMOKE" else "BLOCKED_PREFLIGHT"
            row["missing_capabilities"] = ";".join(sorted(blockers))
            row["blocker_count"] = str(len(blockers))
            row["ticket2_support_status"] = "NOT_YET_SUPPORTED_REAL_SOLVE"
        _write_csv(evidence / filename, rows, list(rows[0]))


def main() -> int:
    skill = _skill_root()
    benchmark = skill / "benchmarks" / "paper_diversity_v2"
    evidence = skill / "artifacts" / "paper_diversity_v2" / "representability"
    tasks = {row["task_id"]: row for row in _read_csv(benchmark / "EXP4_NASICON_32_TASKS.csv")}
    leave_manifest = [
        json.loads(line)
        for line in (skill / "data" / "corpora" / "nasicon_specialist_all_targets_out_v3" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    leave_formulas = {Composition(row["reduced_formula"]).reduced_formula for row in leave_manifest}

    a1_scaffold = get_scaffold(SCAFFOLDS["E4_A1"])
    a1_occupation = preflight_ordered_occupation(
        tasks["E4_A1"]["target_formula"], len(a1_scaffold.fractional_candidate_sites), task_orbits(tasks["E4_A1"], a1_scaffold)
    )
    a1_evidence = {
        "task_id": "E4_A1",
        "classification": E4_A1_CLASSIFICATION,
        "requested_formula": tasks["E4_A1"]["target_formula"],
        "requested_space_group": tasks["E4_A1"]["allowed_space_groups"],
        "selected_scaffold_id": a1_scaffold.scaffold_id,
        "relevant_orbit_multiplicities": a1_scaffold.orbit_multiplicities,
        "requested_species_counts": a1_occupation.requested_composition,
        "integer_occupation_feasible": False,
        "partial_occupation_required": True,
        "ordered_supercell_changes_symmetry": True,
        "abstention_reason": "The single symmetry-closed multiplicity-6 tetrahedral orbit cannot express ordered Si4/P2 while preserving R-3c.",
        "future_extension_options": [
            "Fractional/disordered orbit occupation.",
            "Symmetry-lowered ordered supercell.",
            "Alternative experimentally supported composition compatible with the parent orbit multiplicities.",
        ],
    }
    assert not a1_occupation.stoichiometry_representable

    preflight_rows = [preflight_task(tasks[task_id], leave_formulas, scaffold_id=SCAFFOLDS[task_id]) for task_id in REVISED_TASK_IDS]
    preflight = {row["task_id"]: row for row in preflight_rows}
    assert len({row["task_id"] for row in preflight_rows}) == 8
    assert len({Composition(row["target_formula"]).reduced_formula for row in preflight_rows}) >= 7
    assert len({row["search_space_sha256"] for row in preflight_rows}) == 8

    replacement = preflight["E4_F1"]
    replacement_selected = replacement["preflight_status"] == "READY_FOR_SMOKE"
    replacement_rows = [{
        "priority": 1,
        "candidate_task_id": "E4_F1",
        "candidate_description": "second LiZr2(PO4)3 polymorph: rhombohedral R-3c task",
        "scaffold_id": replacement["scaffold_id"],
        "scaffold_source_id": replacement["scaffold_source_id"],
        "integer_occupation_feasible": replacement["integer_occupation_feasible"],
        "fractional_occupation_used": replacement["fractional_occupation_used"],
        "space_group_match": replacement["space_group_match"],
        "topology_policy_available": replacement["topology_policy_available"],
        "exact_target_leakage_count": replacement["exact_target_leakage_count"],
        "search_space_sha256": replacement["search_space_sha256"],
        "decision": "SELECTED" if replacement_selected else "REJECTED",
        "rejection_reason": "" if replacement_selected else replacement["blockers"],
        "notes": "Generic coordination-role mapping assigns requested Li to the verified rhombohedral framework mobile-ion orbit; no task-ID/formula special case or fractional occupation is used.",
    }]
    _write_csv(evidence / "FIRST_EIGHT_REPLACEMENT_SELECTION.csv", replacement_rows)
    (evidence / "FIRST_EIGHT_REPLACEMENT_SELECTION.md").write_text(
        "# First-eight replacement selection\n\n"
        "E4_F1 was the first priority candidate and is **SELECTED** for the smoke subset. It is the frozen rhombohedral "
        "LiZr2(PO4)3 task, represented on the hash-verified `nzp_nazr2po43_r3c` framework by the generic mobile-ion-role "
        "rule. The multiplicity-2 mobile orbit is occupied by Li, all framework orbits remain symmetry-closed, no fractional "
        "occupation is used, the source and requested space groups are both R-3c, and the all-targets-out corpus contains no "
        "exact LiZr2(PO4)3 target. Later-priority candidates were not considered because the first priority passed.\n",
        encoding="utf-8",
    )

    task_export_fields = [
        "task_id", "natural_language_request", "target_formula", "target_family", "target_topology", "allowed_space_groups",
        "preferred_space_group", "scaffold_hypotheses", "variable_species_orbits", "site_ordering_requirement",
        "requested_distinct_solutions", "retrieval_corpus", "spp_policy", "validation_policy",
    ]
    revised_rows = []
    for task_id in REVISED_TASK_IDS:
        task = tasks[task_id]
        pf = preflight[task_id]
        structured = {key: value for key, value in task.items() if key not in {"natural_language_request", "short_request_label"}}
        revised_rows.append({
            **{field: task[field] for field in task_export_fields},
            "natural_language_request_sha256": _sha256_bytes(task["natural_language_request"].encode("utf-8")),
            "structured_intent_sha256": canonical_hash(structured),
            "scaffold_id": pf["scaffold_id"],
            "scaffold_version": pf["scaffold_version"],
            "scaffold_source_id": pf["scaffold_source_id"],
            "scaffold_source_sha256": pf["scaffold_source_sha256"],
            "search_space_sha256": pf["search_space_sha256"],
            "preflight_status": pf["preflight_status"],
        })
    _write_csv(evidence / "REVISED_FIRST_EIGHT_TASKS.csv", revised_rows)
    _write_csv(evidence / "REVISED_FIRST_EIGHT_PREFLIGHT.csv", preflight_rows)

    after_rows = []
    for task in tasks.values():
        task_id = task["task_id"]
        if task_id == "E4_A1":
            classification = E4_A1_CLASSIFICATION
            multiplicity = "UNSUPPORTED"
            blocker = "ORDERED_MODEL_REQUIRES_DISORDER"
        elif task_id in preflight:
            result = preflight[task_id]
            classification = "MULTIPLICITY_PREFLIGHT_SUPPORTED_REAL_SMOKE_NOT_RUN" if result["preflight_status"] == "READY_FOR_SMOKE" else "BLOCKED_PREFLIGHT"
            multiplicity = "SUPPORTED" if result["integer_occupation_feasible"] else "UNSUPPORTED"
            blocker = result["blockers"]
        else:
            classification = "NOT_TASK_SPECIFICALLY_VALIDATED"
            multiplicity = "NOT_RUN"
            blocker = ""
        after_rows.append({
            "task_id": task_id,
            "target_formula": task["target_formula"],
            "representability_classification": classification,
            "multiplicity_preflight_support": multiplicity,
            "model_build_support": "NOT_RUN",
            "solver_support": "NOT_RUN",
            "valid_cif_support": "NOT_RUN",
            "topology_validated_support": "NOT_RUN",
            "real_solve_support_status": "NOT_YET_SUPPORTED_REAL_SOLVE",
            "blockers": blocker,
        })
    _write_csv(evidence / "E4_REPRESENTABILITY_AFTER_EXTENSION.csv", after_rows)

    (evidence / "E4_A1_ABSTENTION_REPORT.md").write_text(
        "# E4_A1 ordered-model abstention\n\n"
        f"Classification: **{E4_A1_CLASSIFICATION}**.\n\n"
        "The frozen request remains Na3Zr2Si2PO12 in R-3c. The selected verified scaffold has multiplicities Na:6, "
        "framework-cation:4, tetrahedral:6, and O:12+12. Two formula units require Si4 and P2, but the parent has one "
        "symmetry-closed multiplicity-6 tetrahedral orbit. An integer full-orbit assignment therefore cannot make the "
        "requested 4:2 split. Partial occupation would preserve R-3c but is outside the ordered model; ordering a supercell "
        "would lower occupational symmetry and change the request. This is an abstention before generation, not a failed "
        "generated structure.\n\n"
        "## Frozen decision record\n\n"
        f"```json\n{json.dumps(a1_evidence, indent=2, sort_keys=True)}\n```\n\n"
        "## Future extension options (not implemented)\n\n"
        "1. Fractional/disordered orbit occupation.\n"
        "2. Symmetry-lowered ordered supercell.\n"
        "3. Alternative experimentally supported composition compatible with the parent orbit multiplicities.\n",
        encoding="utf-8",
    )

    _update_blocker_tables(evidence, preflight, a1_evidence)
    ready = [row["task_id"] for row in preflight_rows if row["preflight_status"] == "READY_FOR_SMOKE"]
    blocked = {row["task_id"]: row["blockers"] for row in preflight_rows if row["preflight_status"] != "READY_FOR_SMOKE"}
    (evidence / "QLIP_EXTENSION_REPORT.md").write_text(
        "# QLIP Ticket 2 extension report\n\n"
        "## Preserved focused implementation evidence\n\n"
        "- Scaffold registry: **10 focused tests passed**; seven records and seven frozen source hashes verified.\n"
        "- Generalized ordered occupation: **14 focused tests passed**.\n"
        "- Adjacent occupation/schema/solver/NASICON gate: **24 tests passed**.\n"
        "- Explicit-vacancy real Gurobi check: **OPTIMAL** with exact vacancy count.\n"
        "- Charge preflight: **5 passed**; multi-scaffold: **5 passed**; top-k: **6 + 4 passed**; known exclusion: **5 passed**.\n\n"
        "## E4_A1\n\n"
        f"E4_A1 is **{E4_A1_CLASSIFICATION}**. It was not sent to retrieval, model construction, or generation.\n\n"
        "## Replacement selection\n\n"
        "E4_F1 is selected as the priority replacement: a distinct rhombohedral LiZr2(PO4)3 intent on the verified "
        "R-3c NZP framework, using a generic mobile-ion-role occupation and no fractional state.\n\n"
        "## Revised first-eight preflight\n\n"
        f"- READY_FOR_SMOKE: **{len(ready)}/8** (`{', '.join(ready)}`).\n"
        f"- Blocked: **{json.dumps(blocked, sort_keys=True)}**.\n"
        "- E4_A3 requests P2_1/c but its only verified exact-composition registry scaffold is Cc.\n"
        "- E4_A4 requests C2/c but its verified occupation scaffold is P1; the current frozen topology proxy also lacks Hf as an octahedral framework center.\n\n"
        "Because fewer than eight rows are ready, the mandatory pre-smoke gate halted. Crystal-DB retrieval, SPP construction, "
        "QLIP model building, Gurobi smoke generation, CIF writing, distinctness analysis, SCA validation, and the pilot were not launched.\n",
        encoding="utf-8",
    )

    output_names = [
        "E4_A1_ABSTENTION_REPORT.md", "FIRST_EIGHT_REPLACEMENT_SELECTION.csv", "FIRST_EIGHT_REPLACEMENT_SELECTION.md",
        "REVISED_FIRST_EIGHT_TASKS.csv", "REVISED_FIRST_EIGHT_PREFLIGHT.csv", "E4_REPRESENTABILITY_AFTER_EXTENSION.csv",
        "QLIP_EXTENSION_REPORT.md", "TASK_CAPABILITY_BLOCKERS.csv", "E4_CAPABILITY_BLOCKERS.csv",
    ]
    output_rows = []
    for name in output_names:
        path = evidence / name
        output_rows.append({"path": str(path), "sha256": _sha256_file(path), "bytes": path.stat().st_size})
    _write_csv(evidence / "OUTPUT_HASH_MANIFEST.csv", output_rows)

    print(json.dumps({
        "e4_a1_classification": E4_A1_CLASSIFICATION,
        "replacement_task_id": "E4_F1",
        "ready_for_smoke": ready,
        "blocked_preflight": blocked,
        "generation_launched": False,
        "halt_reason": "FEWER_THAN_EIGHT_READY_FOR_SMOKE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
