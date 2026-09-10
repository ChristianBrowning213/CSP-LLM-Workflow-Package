"""Reusable preparation logic for frozen NASICON paper-diversity tasks."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from ase.formula import Formula
from pymatgen.core import Composition

from qlip.core.chemistry import preflight_charge
from qlip.scaffolds import get_scaffold
from qlip.scaffolds.occupation import preflight_ordered_occupation


DEFAULT_SCAFFOLDS = {
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
TOPOLOGY_OCTAHEDRAL_CATIONS = {"Zr", "V", "Ti", "Cr", "Sc"}
TOPOLOGY_TETRAHEDRAL_CATIONS = {"Si", "P"}


def resolve_skill_loop_root(project_root: str | Path | None = None) -> Path:
    """Resolve an explicitly configured external frozen-task root."""
    if project_root is None:
        raise ValueError("project_root is required; sibling source repositories are not discovered")
    candidate = Path(project_root).expanduser().resolve()
    manifest = candidate / "benchmarks" / "paper_diversity_v2" / "EXP4_NASICON_32_TASKS.csv"
    if not manifest.is_file():
        raise FileNotFoundError(f"Frozen E4 task manifest not found beneath configured project root: {manifest}")
    return candidate


def load_frozen_e4_tasks(project_root: str | Path | None = None) -> dict[str, dict[str, str]]:
    root = resolve_skill_loop_root(project_root)
    path = root / "benchmarks" / "paper_diversity_v2" / "EXP4_NASICON_32_TASKS.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or any(not row.get("task_id") for row in rows):
        raise ValueError(f"Frozen E4 task manifest is empty or malformed: {path}")
    return {row["task_id"]: row for row in rows}


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def structured_intent_hash(task: dict[str, str]) -> str:
    return canonical_hash({key: value for key, value in task.items() if key not in {"natural_language_request", "short_request_label"}})


def explicit_charge_assumptions(formula: str) -> dict[str, Any]:
    counts = {str(species): int(count) for species, count in Formula(formula).count().items()}
    states = {
        species: 1 if species in MOBILE_IONS else -2 if species == "O" else 5 if species == "P" else 4
        for species in counts if species in MOBILE_IONS | {"O", "P", "Si"}
    }
    unknown = sorted(set(counts) - set(states))
    if len(unknown) != 1:
        raise ValueError(f"Expected one framework-centre oxidation state for {formula}: {unknown}")
    framework = unknown[0]
    remainder = -sum(counts[species] * states[species] for species in states)
    if remainder % counts[framework]:
        raise ValueError(f"Non-integral inferred oxidation state for {formula}")
    states[framework] = remainder // counts[framework]
    chemistry = {
        "formula": formula, "charge_policy": "EXPLICIT_REQUIRED", "oxidation_states": states,
        "compensation_operation": "none",
        "assumptions_source": "formal charge balance: alkali +1, O -2, P +5, Si +4; sole octahedral framework state inferred",
    }
    result = preflight_charge(chemistry)
    if not result.accepted or result.charge_sum != 0 or not result.charge_neutral:
        raise ValueError(f"Charge preflight failed: {result.to_dict()}")
    return {"chemistry": chemistry, "result": result.to_dict()}


def formula_species(formula: str) -> set[str]:
    return {str(symbol) for symbol in Formula(formula).count()}


def task_orbits(task: dict[str, str], scaffold: Any) -> list[dict[str, Any]]:
    """Apply chemistry-generic coordination-role allowlists to a scaffold."""
    target_species = formula_species(task["target_formula"])
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


def topology_capability(task: dict[str, str], policy: str) -> tuple[bool, list[str]]:
    species = formula_species(task["target_formula"])
    octahedral = species - MOBILE_IONS - TETRAHEDRAL_CATIONS - {"O"}
    unsupported = sorted((octahedral - TOPOLOGY_OCTAHEDRAL_CATIONS) | ((species & TETRAHEDRAL_CATIONS) - TOPOLOGY_TETRAHEDRAL_CATIONS))
    available = policy == "nasicon_ordered_coordination_single_component_rank3_proxy_v1" and not unsupported
    return available, unsupported


def preflight_task(task: dict[str, str], all_targets_out_formulas: set[str], *, scaffold_id: str | None = None) -> dict[str, Any]:
    scaffold = get_scaffold(scaffold_id or DEFAULT_SCAFFOLDS[task["task_id"]])
    orbits = task_orbits(task, scaffold)
    occupation = preflight_ordered_occupation(task["target_formula"], len(scaffold.fractional_candidate_sites), orbits)
    requested_space_groups = {value.strip() for value in task["allowed_space_groups"].split(";") if value.strip() and value.strip().lower() != "none"}
    space_group_match = scaffold.source_space_group in requested_space_groups
    topology_available, unsupported_species = topology_capability(task, scaffold.topology_policy)
    leakage_count = int(Composition(task["target_formula"]).reduced_formula in all_targets_out_formulas)
    search_space = {
        "target_formula": task["target_formula"], "allowed_space_groups": sorted(requested_space_groups),
        "scaffold_id": scaffold.scaffold_id, "scaffold_version": scaffold.scaffold_version,
        "scaffold_source_hash": scaffold.source_cif_sha256, "ordered_orbits": orbits,
        "vacancy_policy": "NO_VACANCIES", "charge_policy": "FORMULA_EXACT_NEUTRALITY_PREFLIGHT",
        "topology_policy": scaffold.topology_policy,
    }
    blockers: list[str] = []
    if not occupation.stoichiometry_representable: blockers.append("ORBIT_MULTIPLICITY_NOT_REPRESENTABLE")
    if not space_group_match: blockers.append("TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH")
    if not topology_available: blockers.append("TOPOLOGY_POLICY_CHEMISTRY_UNSUPPORTED")
    if leakage_count: blockers.append("EXACT_TARGET_RETRIEVAL_LEAKAGE")
    return {
        "task_id": task["task_id"], "target_formula": task["target_formula"], "target_space_group": task["allowed_space_groups"],
        "scaffold_id": scaffold.scaffold_id, "scaffold_version": scaffold.scaffold_version,
        "scaffold_source_id": scaffold.source_structure_id, "scaffold_source_path": scaffold.source_cif_path,
        "scaffold_source_sha256": scaffold.source_cif_sha256, "source_space_group": scaffold.source_space_group,
        "space_group_match": space_group_match,
        "orbit_multiplicities": json.dumps(scaffold.orbit_multiplicities, sort_keys=True, separators=(",", ":")),
        "occupation_evidence": json.dumps(occupation.to_dict(), sort_keys=True, separators=(",", ":")),
        "integer_occupation_feasible": occupation.stoichiometry_representable, "fractional_occupation_used": False,
        "topology_policy": scaffold.topology_policy, "topology_policy_available": topology_available,
        "topology_unsupported_species": ";".join(unsupported_species), "retrieval_database": "nasicon_specialist_all_targets_out_v3",
        "exact_target_leakage_count": leakage_count, "search_space_sha256": canonical_hash(search_space),
        "preflight_status": "READY_FOR_SMOKE" if not blockers else "BLOCKED_PREFLIGHT", "blockers": ";".join(blockers),
    }
