"""Top-k enumeration for a fixed QLIP occupation search space."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable

import pyomo.environ as pyo
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter


TERMINATION_REASONS = {
    "K_REACHED", "FEASIBLE_SPACE_EXHAUSTED", "NO_ADDITIONAL_DISTINCT_STRUCTURE",
    "TIME_LIMIT", "INFEASIBLE", "ERROR",
}
DISTINCTNESS_POLICIES = {"ASSIGNMENT_DISTINCT", "HASH_DISTINCT", "STRUCTURE_DISTINCT"}


@dataclass(frozen=True)
class TopKResult:
    requested_k: int
    distinctness_policy: str
    assignment_unique_count: int
    canonical_hash_unique_count: int
    structurematcher_unique_count: int
    symmetry_equivalent_count: int
    feasible_assignments_seen: int
    solver_solutions_seen: int
    no_good_cuts_added: int
    exact_assignment_duplicates: int
    hash_unique_candidates: int
    structurematcher_unique_candidates: int
    symmetry_equivalents_rejected: int
    assignments_rejected_by_hash: int
    assignments_rejected_by_structurematcher: int
    assignments_rejected_as_symmetry_equivalent: int
    selected_candidates: tuple[dict[str, Any], ...]
    termination_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _assignment(allocation: Any) -> tuple[str, ...]:
    values: list[str] = []
    for site in allocation.m.Pos:
        occupied = [str(species) for species in allocation.m.Types if pyo.value(allocation.m.x[species, site]) > 0.5]
        vacancy = pyo.value(allocation.m.vacancy[site]) > 0.5
        if len(occupied) + int(vacancy) != 1:
            raise ValueError(f"site {site} does not decode to exactly one occupation state")
        values.append("VACANCY" if vacancy else occupied[0])
    return tuple(values)


def _default_structure(allocation: Any, assignment: tuple[str, ...]) -> Structure:
    cell = allocation.positions.cell.cellpar()
    lattice = Lattice.from_parameters(*[float(value) for value in cell])
    fractional = allocation.positions.get_scaled_positions(wrap=True)
    species = [state for state in assignment if state != "VACANCY"]
    coordinates = [fractional[index] for index, state in enumerate(assignment) if state != "VACANCY"]
    return Structure(lattice, species, coordinates).get_sorted_structure()


def enumerate_top_k(
    allocation: Any,
    requested_k: int,
    *,
    solver_name: str = "gurobi",
    structure_builder: Callable[[Any, tuple[str, ...]], Structure] | None = None,
    matcher: StructureMatcher | None = None,
    distinctness_policy: str = "STRUCTURE_DISTINCT",
) -> TopKResult:
    if requested_k <= 0:
        raise ValueError("requested_k must be positive")
    policy = str(distinctness_policy).upper()
    if policy not in DISTINCTNESS_POLICIES:
        raise ValueError(f"unknown top-k distinctness policy: {distinctness_policy}")
    solver = pyo.SolverFactory(solver_name)
    if solver is None or not solver.available(exception_flag=False):
        raise RuntimeError(f"{solver_name} solver is not available")
    if not hasattr(allocation.m, "top_k_no_good_cuts"):
        allocation.m.top_k_no_good_cuts = pyo.ConstraintList()
    build = structure_builder or _default_structure
    structure_matcher = matcher or StructureMatcher(
        ltol=0.2, stol=0.3, angle_tol=5.0,
        primitive_cell=True, scale=True, attempt_supercell=False,
    )
    assignments: set[tuple[str, ...]] = set()
    hashes: set[str] = set()
    unique_structures: list[Structure] = []
    accepted_hashes: set[str] = set()
    accepted: list[dict[str, Any]] = []
    solver_seen = exact_duplicates = symmetry_equivalent = no_goods = 0
    rejected_by_hash = rejected_by_matcher = 0
    termination = "ERROR"
    while len(accepted) < requested_k:
        solved = solver.solve(allocation.m, tee=False)
        condition = solved.solver.termination_condition
        if condition == pyo.TerminationCondition.infeasible:
            if solver_seen == 0:
                termination = "INFEASIBLE"
            elif policy != "ASSIGNMENT_DISTINCT" and (rejected_by_hash or rejected_by_matcher or exact_duplicates):
                termination = "NO_ADDITIONAL_DISTINCT_STRUCTURE"
            else:
                termination = "FEASIBLE_SPACE_EXHAUSTED"
            break
        if condition in {pyo.TerminationCondition.maxTimeLimit, pyo.TerminationCondition.maxIterations}:
            termination = "TIME_LIMIT"
            break
        if condition not in {pyo.TerminationCondition.optimal, pyo.TerminationCondition.feasible}:
            termination = "ERROR"
            break
        solver_seen += 1
        decoded = _assignment(allocation)
        assignment_hash = hashlib.sha256(json.dumps(decoded, separators=(",", ":")).encode("utf-8")).hexdigest()
        selected_variables = [
            allocation.m.vacancy[index] if state == "VACANCY" else allocation.m.x[state, index]
            for index, state in enumerate(decoded)
        ]
        allocation.m.top_k_no_good_cuts.add(sum(selected_variables) <= len(selected_variables) - 1)
        no_goods += 1
        if decoded in assignments:
            exact_duplicates += 1
            continue
        assignments.add(decoded)
        structure = build(allocation, decoded)
        cif_text = str(CifWriter(structure, symprec=None)) + "\n"
        cif_hash = hashlib.sha256(cif_text.encode("utf-8")).hexdigest()
        hashes.add(cif_hash)
        equivalent = any(structure_matcher.fit(structure, prior) for prior in unique_structures)
        if equivalent:
            symmetry_equivalent += 1
        else:
            unique_structures.append(structure)
        accept = True
        if policy == "HASH_DISTINCT" and cif_hash in accepted_hashes:
            rejected_by_hash += 1
            accept = False
        elif policy == "STRUCTURE_DISTINCT" and equivalent:
            rejected_by_matcher += 1
            accept = False
        if not accept:
            continue
        accepted_hashes.add(cif_hash)
        accepted.append(
            {
                "candidate_index": len(accepted),
                "assignment": decoded,
                "assignment_sha256": assignment_hash,
                "cif_sha256": cif_hash,
                "cif_text": cif_text,
                "objective": float(pyo.value(allocation.m.obj)),
            }
        )
    else:
        termination = "K_REACHED"
    if termination not in TERMINATION_REASONS:
        raise AssertionError(termination)
    return TopKResult(
        requested_k=requested_k,
        distinctness_policy=policy,
        assignment_unique_count=len(assignments),
        canonical_hash_unique_count=len(hashes),
        structurematcher_unique_count=len(unique_structures),
        symmetry_equivalent_count=symmetry_equivalent,
        feasible_assignments_seen=len(assignments),
        solver_solutions_seen=solver_seen,
        no_good_cuts_added=no_goods,
        exact_assignment_duplicates=exact_duplicates,
        hash_unique_candidates=len(hashes),
        structurematcher_unique_candidates=len(unique_structures),
        symmetry_equivalents_rejected=rejected_by_matcher,
        assignments_rejected_by_hash=rejected_by_hash,
        assignments_rejected_by_structurematcher=rejected_by_matcher,
        assignments_rejected_as_symmetry_equivalent=rejected_by_matcher,
        selected_candidates=tuple(accepted),
        termination_reason=termination,
    )
