"""Auditable NONE/LOOSE/HARD search-space selection for row experiments."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pymatgen.core import Composition, Lattice, Structure

from sok_llm_orchestrator.workflow.cell_strategy import ResolvedCell


NATIVE_GRID_DENSITY = 8
NATIVE_LATTICE = {
    "a": 3.9, "b": 3.9, "c": 3.9,
    "alpha": 90.0, "beta": 90.0, "gamma": 90.0, "units": "angstrom",
}


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ScaffoldSelection:
    mode: str
    scaffold_dir: str
    scaffold_id: str
    scaffold_hash: str
    structure: Structure | None
    orbits: tuple[dict[str, Any], ...]
    candidate_site_count: int
    symmetry_orbit_count: int
    species_fixed_orbit_count: int
    variable_orbit_count: int
    feasible_state_count: int | None
    allocation_variable_count: int
    native_sites: dict[str, Any] | None = None
    native_template: dict[str, Any] | None = None
    native_constraints: tuple[dict[str, Any], ...] = ()
    cell_provenance: dict[str, Any] | None = None

    def provenance(self) -> dict[str, Any]:
        payload = {
            "scaffold_mode": self.mode,
            "scaffold_dir": self.scaffold_dir,
            "scaffold_id": self.scaffold_id,
            "scaffold_hash": self.scaffold_hash,
            "candidate_site_count": self.candidate_site_count,
            "symmetry_orbit_count": self.symmetry_orbit_count,
            "species_fixed_orbit_count": self.species_fixed_orbit_count,
            "variable_orbit_count": self.variable_orbit_count,
            "feasible_state_count": self.feasible_state_count,
            "allocation_variable_count": self.allocation_variable_count,
        }
        if self.cell_provenance is not None:
            payload["cell_provenance"] = self.cell_provenance
        return payload


def native_selection(formula: str, *, resolved_cell: ResolvedCell | None = None) -> ScaffoldSelection:
    """Mirror QLIP's base CLI defaults: cubic 3.9 A and an 8^3 uniform grid.

    ``resolved_cell`` is None for the frozen default (byte-identical to the
    original behavior).  When provided (via cell_strategy.resolve_native_cell)
    it supplies an alternative cubic lattice edge length for the
    composition_scaled/retrieval_derived cell_mode conditions; the uniform
    grid density and the proximity.atomic_radii constraint are unchanged.
    """
    species = sorted(Composition(formula).get_el_amt_dict(), key=str.lower)
    if resolved_cell is None:
        lattice = dict(NATIVE_LATTICE)
        density = NATIVE_GRID_DENSITY
    else:
        lattice = resolved_cell.lattice_dict()
        density = resolved_cell.grid_density
    sites = {"mode": "uniform_grid", "uniform_grid": {"density": density}}
    template = {"name": "cubic", "lattice": lattice}
    constraints = ({"id": "proximity.atomic_radii", "params": {"scale": 1.0}},)
    payload = {
        "mechanism": "qlip.base.uniform_grid",
        "formula": formula, "template": template, "sites": sites,
        "ordered_orbits": [], "constraints": constraints,
    }
    if resolved_cell is not None:
        payload["cell_mode"] = resolved_cell.cell_mode
    count = density ** 3
    scaffold_id = "qlip_native_uniform_grid" if resolved_cell is None else f"qlip_native_uniform_grid_{resolved_cell.cell_mode}"
    return ScaffoldSelection(
        mode="none", scaffold_dir="", scaffold_id=scaffold_id,
        scaffold_hash=canonical_hash(payload), structure=None, orbits=(),
        candidate_site_count=count, symmetry_orbit_count=0,
        species_fixed_orbit_count=0, variable_orbit_count=0,
        feasible_state_count=None, allocation_variable_count=count * len(species),
        native_sites=sites, native_template=template, native_constraints=constraints,
        cell_provenance=(resolved_cell.to_dict() if resolved_cell is not None else None),
    )


def _target_counts(formula: str, site_count: int) -> dict[str, int]:
    composition = Composition(formula)
    scale = site_count / float(composition.num_atoms)
    rounded = round(scale)
    if rounded <= 0 or abs(scale - rounded) > 1e-9:
        raise ValueError(f"{formula} cannot be scaled exactly onto {site_count} scaffold sites")
    return {str(element): int(round(float(amount) * rounded)) for element, amount in composition.items()}


def count_orbit_assignments(formula: str, site_count: int, orbits: list[dict[str, Any]]) -> int:
    """Count symmetry-closed, exact-composition occupation states by dynamic programming."""
    target = _target_counts(formula, site_count)
    species = tuple(sorted(target, key=str.lower))
    states: dict[tuple[int, ...], int] = {(0,) * len(species): 1}
    for orbit in orbits:
        multiplicity = len(orbit["site_indices"])
        allowed = [str(orbit["fixed_species"])] if orbit.get("fixed_species") else [
            str(value) for value in orbit.get("allowed_species", []) if str(value) != "VACANCY"
        ]
        if orbit.get("vacancy_allowed") and not orbit.get("required_occupancy", True):
            allowed.append("VACANCY")
        next_states: dict[tuple[int, ...], int] = {}
        for counts, ways in states.items():
            for choice in allowed:
                updated = list(counts)
                if choice != "VACANCY":
                    if choice not in target:
                        continue
                    index = species.index(choice)
                    updated[index] += multiplicity
                    if updated[index] > target[choice]:
                        continue
                key = tuple(updated)
                next_states[key] = next_states.get(key, 0) + ways
        states = next_states
    return states.get(tuple(target[value] for value in species), 0)


def _load_descriptor(scaffold_dir: Path) -> tuple[Path, dict[str, Any]]:
    root = Path(scaffold_dir).resolve()
    descriptor = root / "registry.json"
    if not descriptor.is_file():
        raise FileNotFoundError(f"scaffold registry descriptor missing: {descriptor}")
    payload = json.loads(descriptor.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "nasicon_scaffold_ablation_registry.v1":
        raise ValueError(f"unsupported scaffold registry schema: {descriptor}")
    if payload.get("mode") not in {"loose", "hard"}:
        raise ValueError(f"scaffold registry mode must be loose or hard: {descriptor}")
    return descriptor, payload


def load_selection(
    task: dict[str, Any], scaffold_dir: Path | None, *, resolved_cell: ResolvedCell | None = None
) -> ScaffoldSelection:
    if scaffold_dir is None:
        return native_selection(str(task["formula"]), resolved_cell=resolved_cell)
    descriptor, registry = _load_descriptor(Path(scaffold_dir))
    target = (registry.get("targets") or {}).get(str(task["formula"]))
    if not isinstance(target, dict):
        raise KeyError(f"{task['formula']} is not registered in {descriptor}")
    from qlip.paper_diversity.smoke_preparation import task_orbits
    from qlip.scaffolds import get_scaffold, validate_scaffold

    record = get_scaffold(str(target["scaffold_id"]))
    if not validate_scaffold(record).valid:
        raise ValueError(f"registered QLIP scaffold failed validation: {record.scaffold_id}")
    if record.source_cif_sha256 != str(target["source_cif_sha256"]):
        raise ValueError(f"registered QLIP scaffold hash changed: {record.scaffold_id}")
    structure = Structure.from_file(record.source_cif_path)
    hard_orbits = task_orbits({"target_formula": str(task["formula"])}, record)
    mode = str(registry["mode"])
    if mode == "hard":
        orbits = hard_orbits
    else:
        target_species = sorted(Composition(str(task["formula"])).get_el_amt_dict(), key=str.lower)
        orbits = []
        for source in hard_orbits:
            orbit = copy.deepcopy(source)
            orbit.pop("fixed_species", None)
            orbit["allowed_species"] = list(target_species)
            orbit["required_occupancy"] = not bool(orbit.get("vacancy_allowed", False))
            orbit["occupation_mode"] = "VARIABLE_FULL_ORBIT"
            orbits.append(orbit)
    feasible = count_orbit_assignments(str(task["formula"]), len(structure), orbits)
    fixed = sum(bool(orbit.get("fixed_species")) for orbit in orbits)
    variable = len(orbits) - fixed
    semantic_payload = {
        "registry": registry, "formula": task["formula"],
        "source_cif_sha256": record.source_cif_sha256,
        "lattice": structure.lattice.matrix.tolist(),
        "fractional_candidate_sites": structure.frac_coords.tolist(), "ordered_orbits": orbits,
    }
    return ScaffoldSelection(
        mode=mode, scaffold_dir=str(descriptor.parent), scaffold_id=record.scaffold_id,
        scaffold_hash=canonical_hash(semantic_payload), structure=structure,
        orbits=tuple(orbits), candidate_site_count=len(structure),
        symmetry_orbit_count=len(orbits), species_fixed_orbit_count=fixed,
        variable_orbit_count=variable, feasible_state_count=feasible,
        allocation_variable_count=sum(len(orbit.get("allowed_species", [])) for orbit in orbits),
    )

