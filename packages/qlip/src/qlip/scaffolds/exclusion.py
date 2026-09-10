"""Resolve and exclude one known occupation assignment exactly."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pyomo.environ as pyo
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Structure

from .topk import _assignment, _default_structure


@dataclass(frozen=True)
class AssignmentExclusionResult:
    reference_assignment_resolved: bool
    excluded_assignment: tuple[str, ...] | None
    exclusion_constraint_added: bool
    alternative_found: bool | None
    alternative_structure_match_to_reference: bool | None
    source_kind: str | None
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _from_orbit_map(allocation: Any, values: Mapping[str, str]) -> tuple[str, ...]:
    assignment: list[str | None] = [None] * len(allocation.positions)
    known = {str(orbit["orbit_id"]): orbit for orbit in allocation.ordered_orbits}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ValueError(f"unknown orbit IDs in excluded map: {unknown}")
    for orbit_id, orbit in known.items():
        if orbit_id not in values:
            raise ValueError(f"excluded orbit map is missing orbit {orbit_id}")
        state = str(values[orbit_id])
        for index in orbit["site_indices"]:
            assignment[int(index)] = state
    if any(value is None for value in assignment):
        raise ValueError("ordered orbits do not cover the full assignment")
    return tuple(str(value) for value in assignment)


def _from_cif(allocation: Any, reference_cif: str | Path, tolerance: float = 1e-5) -> tuple[str, ...]:
    structure = Structure.from_file(reference_cif)
    candidate = np.asarray(allocation.positions.get_scaled_positions(wrap=True), dtype=float)
    assignment = ["VACANCY"] * len(candidate)
    used: set[int] = set()
    for site in structure:
        delta = ((candidate - np.asarray(site.frac_coords) + 0.5) % 1.0) - 0.5
        distances = np.linalg.norm(delta, axis=1)
        index = int(np.argmin(distances))
        if float(distances[index]) > tolerance or index in used:
            raise ValueError("reference CIF sites do not map one-to-one onto candidate fractional sites")
        assignment[index] = site.specie.symbol
        used.add(index)
    return tuple(assignment)


def resolve_reference_assignment(
    allocation: Any,
    *,
    reference_cif: str | Path | None = None,
    reference_assignment: Iterable[str] | None = None,
    excluded_orbit_species_map: Mapping[str, str] | None = None,
) -> tuple[tuple[str, ...], str]:
    supplied = sum(value is not None for value in (reference_cif, reference_assignment, excluded_orbit_species_map))
    if supplied != 1:
        raise ValueError("supply exactly one of reference_cif, reference_assignment, or excluded_orbit_species_map")
    if reference_assignment is not None:
        assignment = tuple(str(value) for value in reference_assignment)
        source_kind = "reference_assignment"
    elif excluded_orbit_species_map is not None:
        assignment = _from_orbit_map(allocation, excluded_orbit_species_map)
        source_kind = "excluded_orbit_species_map"
    else:
        assignment = _from_cif(allocation, Path(reference_cif))
        source_kind = "reference_cif"
    if len(assignment) != len(allocation.positions):
        raise ValueError("reference assignment length does not match candidate-site count")
    known_species = {str(value) for value in allocation.types}
    unknown = sorted(set(assignment) - known_species - {"VACANCY"})
    if unknown:
        raise ValueError(f"reference assignment contains unknown states: {unknown}")
    return assignment, source_kind


def add_reference_assignment_exclusion(
    allocation: Any,
    *,
    reference_cif: str | Path | None = None,
    reference_assignment: Iterable[str] | None = None,
    excluded_orbit_species_map: Mapping[str, str] | None = None,
) -> AssignmentExclusionResult:
    try:
        assignment, source_kind = resolve_reference_assignment(
            allocation,
            reference_cif=reference_cif,
            reference_assignment=reference_assignment,
            excluded_orbit_species_map=excluded_orbit_species_map,
        )
        if not hasattr(allocation.m, "reference_assignment_exclusions"):
            allocation.m.reference_assignment_exclusions = pyo.ConstraintList()
        selected = [
            allocation.m.vacancy[index] if state == "VACANCY" else allocation.m.x[state, index]
            for index, state in enumerate(assignment)
        ]
        allocation.m.reference_assignment_exclusions.add(sum(selected) <= len(selected) - 1)
        return AssignmentExclusionResult(True, assignment, True, None, None, source_kind)
    except Exception as exc:  # noqa: BLE001
        return AssignmentExclusionResult(False, None, False, None, None, None, f"{type(exc).__name__}: {exc}")


def solve_after_reference_exclusion(
    allocation: Any,
    exclusion: AssignmentExclusionResult,
    *,
    solver_name: str = "gurobi",
) -> AssignmentExclusionResult:
    if not exclusion.exclusion_constraint_added or exclusion.excluded_assignment is None:
        return exclusion
    solver = pyo.SolverFactory(solver_name)
    if solver is None or not solver.available(exception_flag=False):
        raise RuntimeError(f"{solver_name} solver is not available")
    solved = solver.solve(allocation.m, tee=False)
    if solved.solver.termination_condition not in {pyo.TerminationCondition.optimal, pyo.TerminationCondition.feasible}:
        return replace(exclusion, alternative_found=False, alternative_structure_match_to_reference=None)
    alternative = _assignment(allocation)
    reference_structure = _default_structure(allocation, exclusion.excluded_assignment)
    alternative_structure = _default_structure(allocation, alternative)
    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5.0, primitive_cell=True, scale=True, attempt_supercell=False)
    return replace(
        exclusion,
        alternative_found=True,
        alternative_structure_match_to_reference=bool(matcher.fit(reference_structure, alternative_structure)),
    )
