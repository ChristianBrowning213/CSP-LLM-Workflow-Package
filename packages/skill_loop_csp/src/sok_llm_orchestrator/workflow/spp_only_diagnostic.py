"""Pure helpers for the non-paper native QLIP/SPP feasibility diagnostic.

The helpers deliberately preserve QLIP's frozen 3.9 A, 8x8x8 candidate
domain and exact SPP pair-energy convention.  They do not load a scaffold or
reference occupation.  Production result rows remain inputs, never outputs.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from ase import Atoms
from ase.formula import Formula
from pymatgen.core import Composition, Lattice, Structure

from qlip.data.registry import default_registry
from qlip.interactions.spp import SPPCollection, canonical_pair_key, periodic_spp_sum


GRID_DENSITY = 8
CELL_A = 3.9
OUTER_SCALE = 10.0
REGULATOR_WEIGHT = 2.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def native_fractional_grid(density: int = GRID_DENSITY) -> np.ndarray:
    """Return QLIP ``grids.uniform`` coordinates in the identical order."""
    return np.asarray(list(np.ndindex(density, density, density)), dtype=float) / float(density)


def formula_counts(formula: str) -> dict[str, int]:
    return {str(key): int(value) for key, value in Formula(formula).count().items()}


def required_pairs(formula: str) -> list[tuple[str, str]]:
    species = list(formula_counts(formula))
    return [tuple(sorted(pair)) for pair in itertools.combinations_with_replacement(species, 2)]


def pair_name(pair: tuple[str, str]) -> str:
    return "-".join(sorted(pair, key=str.lower))


def assignment_is_native(
    formula: str, assignment: dict[str, list[int]], *, site_count: int = GRID_DENSITY ** 3
) -> bool:
    """Check exact composition, site-domain membership, and exclusivity only."""
    counts = formula_counts(formula)
    if set(assignment) != set(counts):
        return False
    occupied: list[int] = []
    for species, expected in counts.items():
        values = [int(value) for value in assignment[species]]
        if len(values) != expected or any(value < 0 or value >= site_count for value in values):
            return False
        occupied.extend(values)
    return len(occupied) == len(set(occupied))


def deterministic_assignments(formula: str, count: int = 10, seed: int = 20260819) -> list[dict[str, list[int]]]:
    """Construct composition-exact assignments without any reference coordinates."""
    rng = random.Random(f"{seed}:{formula}")
    counts = formula_counts(formula)
    total = sum(counts.values())
    rows: list[dict[str, list[int]]] = []
    seen: set[tuple[tuple[str, tuple[int, ...]], ...]] = set()
    while len(rows) < count:
        sites = rng.sample(range(GRID_DENSITY ** 3), total)
        rng.shuffle(sites)
        cursor = 0
        assignment: dict[str, list[int]] = {}
        for species, amount in counts.items():
            assignment[species] = sorted(sites[cursor : cursor + amount])
            cursor += amount
        key = tuple((species, tuple(values)) for species, values in assignment.items())
        if key not in seen:
            seen.add(key)
            rows.append(assignment)
    return rows


def assignment_payload(assignment: dict[str, list[int]]) -> str:
    return json.dumps(assignment, sort_keys=True, separators=(",", ":"))


def assignment_to_structure(formula: str, assignment: dict[str, list[int]]) -> Structure:
    if not assignment_is_native(formula, assignment):
        raise ValueError("assignment violates native composition/domain/exclusivity")
    grid = native_fractional_grid()
    species: list[str] = []
    coords: list[list[float]] = []
    for symbol in formula_counts(formula):
        for site in assignment[symbol]:
            species.append(symbol)
            coords.append(grid[int(site)].tolist())
    return Structure(Lattice.cubic(CELL_A), species, coords)


def load_effective_spp(trace: dict[str, Any]) -> tuple[SPPCollection, SPPCollection, SPPCollection]:
    """Load the exact request, regulator, and solver-effective collections."""
    pairs = [tuple(str(value).split("-", 1)) for value in trace["required_pairs"]]
    request = SPPCollection(trace["request_spp_root"], cutoff=11.0, missing_pair_policy="fallback")
    request.load(pairs)
    regulator = SPPCollection(trace["regulator_root"], cutoff=11.0, missing_pair_policy="block")
    regulator.load(pairs)
    combined = SPPCollection(
        trace["request_spp_root"], cutoff=11.0, missing_pair_policy="fallback",
        regularisation_spp_dir=trace["regulator_root"], regularisation_weight=REGULATOR_WEIGHT,
    )
    combined.load(pairs)
    return request, regulator, combined


def score_assignment(
    formula: str,
    assignment: dict[str, list[int]],
    request: SPPCollection,
    regulator: SPPCollection,
) -> dict[str, float]:
    structure = assignment_to_structure(formula, assignment)
    atoms = structure.to_ase_atoms()
    symbols = atoms.get_chemical_symbols()
    positions = atoms.positions
    cell = atoms.cell.array
    request_value = float(request.score(symbols, positions, cell, pbc=True))
    regulator_value = float(regulator.score(symbols, positions, cell, pbc=True))
    total = OUTER_SCALE * (request_value + REGULATOR_WEIGHT * regulator_value)
    return {
        "request_component": OUTER_SCALE * request_value,
        "regulator_component": OUTER_SCALE * REGULATOR_WEIGHT * regulator_value,
        "total_effective_objective": total,
    }


@dataclass(frozen=True)
class PeriodicKernel:
    values: dict[tuple[str, str], np.ndarray]

    def score(self, assignment: dict[str, list[int]]) -> float:
        entries = [(species, site) for species, sites in assignment.items() for site in sites]
        total = 0.0
        for species, _site in entries:
            total += float(self.values[canonical_pair_key(species, species)][0, 0, 0])
        for left in range(len(entries)):
            species_i, site_i = entries[left]
            ix, iy, iz = np.unravel_index(site_i, (GRID_DENSITY,) * 3)
            for right in range(left + 1, len(entries)):
                species_j, site_j = entries[right]
                jx, jy, jz = np.unravel_index(site_j, (GRID_DENSITY,) * 3)
                delta = ((jx - ix) % GRID_DENSITY, (jy - iy) % GRID_DENSITY, (jz - iz) % GRID_DENSITY)
                total += float(self.values[canonical_pair_key(species_i, species_j)][delta])
        return OUTER_SCALE * total


def build_periodic_kernel(formula: str, combined: SPPCollection) -> PeriodicKernel:
    """Compile exact QLIP periodic coefficients using grid translation symmetry."""
    cell = np.eye(3) * CELL_A
    origin = np.zeros(3)
    values: dict[tuple[str, str], np.ndarray] = {}
    for pair in required_pairs(formula):
        key = canonical_pair_key(*pair)
        primary = combined.spps.get(key)
        regularizer = combined.regularisation_spps.get(key)
        array = np.zeros((GRID_DENSITY,) * 3, dtype=float)
        for delta in np.ndindex((GRID_DENSITY,) * 3):
            frac = np.asarray(delta, dtype=float) / GRID_DENSITY
            value = 0.0
            if primary is not None:
                value += periodic_spp_sum(origin, frac, cell, primary, cutoff=combined.cutoff)
            if regularizer is not None:
                value += REGULATOR_WEIGHT * periodic_spp_sum(origin, frac, cell, regularizer, cutoff=combined.cutoff)
            array[delta] = value
        values[key] = array
    return PeriodicKernel(values)


def optimize_assignment(
    formula: str,
    kernel: PeriodicKernel,
    *,
    seed: int = 20260819,
    restarts: int = 6,
    steps: int = 3000,
) -> tuple[dict[str, list[int]], float, dict[str, Any]]:
    """Find a native-domain incumbent with the exact SPP objective.

    This is intentionally labelled a heuristic incumbent, never an optimal
    Gurobi result. It only removes ``proximity.atomic_radii`` and introduces no
    coordinates, occupations, or chemistry from a target/reference structure.
    """
    rng = random.Random(f"{seed}:{formula}:optimise")
    starts = deterministic_assignments(formula, restarts, seed=seed)
    best_assignment: dict[str, list[int]] | None = None
    best_score = math.inf
    accepted = 0
    evaluated = 0
    for restart, start in enumerate(starts):
        current = {species: list(sites) for species, sites in start.items()}
        current_score = kernel.score(current)
        species_order = list(current)
        for step in range(steps):
            proposal = {species: list(sites) for species, sites in current.items()}
            occupied = {site for sites in proposal.values() for site in sites}
            if rng.random() < 0.72:
                species = rng.choice(species_order)
                index = rng.randrange(len(proposal[species]))
                vacant = rng.randrange(GRID_DENSITY ** 3)
                while vacant in occupied:
                    vacant = rng.randrange(GRID_DENSITY ** 3)
                proposal[species][index] = vacant
                proposal[species].sort()
            else:
                left, right = rng.sample(species_order, 2)
                li, ri = rng.randrange(len(proposal[left])), rng.randrange(len(proposal[right]))
                proposal[left][li], proposal[right][ri] = proposal[right][ri], proposal[left][li]
                proposal[left].sort(); proposal[right].sort()
            proposed_score = kernel.score(proposal)
            evaluated += 1
            fraction = step / max(steps - 1, 1)
            temperature = max(1e-6, abs(current_score) * (0.015 * (1.0 - fraction) + 0.0001))
            if proposed_score < current_score or rng.random() < math.exp(min(0.0, (current_score - proposed_score) / temperature)):
                current, current_score = proposal, proposed_score
                accepted += 1
            if current_score < best_score:
                best_assignment = {species: list(sites) for species, sites in current.items()}
                best_score = current_score
    assert best_assignment is not None
    return best_assignment, best_score, {
        "backend": "exact_qlip_spp_objective_simulated_annealing",
        "status": "FEASIBLE_HEURISTIC_INCUMBENT",
        "optimality_claimed": False,
        "restarts": restarts,
        "steps_per_restart": steps,
        "evaluated_moves": evaluated,
        "accepted_moves": accepted,
        "reference_or_target_occupation_used": False,
        "scaffold_loaded": False,
    }


@lru_cache(maxsize=1)
def native_distance_matrix() -> np.ndarray:
    frac = native_fractional_grid()
    delta = frac[:, None, :] - frac[None, :, :]
    delta -= np.rint(delta)
    return np.linalg.norm(delta * CELL_A, axis=2)


@lru_cache(maxsize=None)
def same_species_capacity(species: str) -> dict[str, Any]:
    """Solve the exact same-species independent-set implied by AtomicRadii."""
    import gurobipy as gp

    radius = float(default_registry().atomic_radius_map()[species])
    threshold = 2.0 * radius
    distances = native_distance_matrix()
    model = gp.Model(f"native_{species}_capacity")
    model.Params.OutputFlag = 0
    values = model.addVars(GRID_DENSITY ** 3, vtype=gp.GRB.BINARY, name="occupied")
    conflict_count = 0
    for i in range(GRID_DENSITY ** 3):
        for j in range(i + 1, GRID_DENSITY ** 3):
            if float(distances[i, j]) < threshold:
                model.addConstr(values[i] + values[j] <= 1)
                conflict_count += 1
    model.setObjective(gp.quicksum(values[i] for i in range(GRID_DENSITY ** 3)), gp.GRB.MAXIMIZE)
    model.optimize()
    return {
        "species": species,
        "atomic_radius_A": radius,
        "same_species_exclusion_A": threshold,
        "maximum_minimum_image_distance_A": float(distances.max()),
        "conflict_edge_count": conflict_count,
        "maximum_compatible_sites": int(round(model.ObjVal)),
        "solver_status": int(model.Status),
        "solver": "Gurobi maximum independent set",
        "rule": "qlip.constraints.proximity.AtomicRadii: distance < r_i+r_j => x_i+x_j<=1",
    }


def feasibility_ladder_rows(formula: str, production_status: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the real NONE constraint ladder and an exact blocker certificate."""
    counts = formula_counts(formula)
    culprit = "Na" if counts.get("Na", 0) >= 3 else "Zr"
    certificate = same_species_capacity(culprit)
    required = counts[culprit]
    certificate["required_count"] = required
    certificate["contradiction"] = required > certificate["maximum_compatible_sites"]
    if not certificate["contradiction"]:
        raise RuntimeError(f"same-species certificate did not prove infeasibility for {formula}")
    variables = GRID_DENSITY ** 3 * len(counts)
    common = {"formula": formula, "candidate_sites": GRID_DENSITY ** 3, "binary_variables": variables}
    rows = [
        {**common, "level": "LEVEL_0", "constraint_categories_active": "exact_composition;site_exclusivity", "feasible": "YES", "solver_feasibility_status": "CONSTRUCTIVE_FEASIBLE"},
        {**common, "level": "LEVEL_1", "constraint_categories_active": "exact_composition;site_exclusivity;native_uniform_grid_domain", "feasible": "YES", "solver_feasibility_status": "CONSTRUCTIVE_FEASIBLE"},
        {**common, "level": "LEVEL_2", "constraint_categories_active": "exact_composition;site_exclusivity;native_uniform_grid_domain;proximity.atomic_radii(scale=1.0)", "feasible": "NO", "solver_feasibility_status": f"{production_status};INDEPENDENT_CONFLICT_CERTIFICATE"},
        {**common, "level": "LEVEL_3", "constraint_categories_active": "LEVEL_2;no_native_symmetry_constraints_present", "feasible": "NO", "solver_feasibility_status": "INHERITED_LEVEL_2_INFEASIBLE"},
        {**common, "level": "LEVEL_4", "constraint_categories_active": "LEVEL_3;no_remaining_production_feasibility_constraints", "feasible": "NO", "solver_feasibility_status": "INHERITED_LEVEL_2_INFEASIBLE"},
        {**common, "level": "LEVEL_FULL", "constraint_categories_active": "exact frozen production NONE configuration", "feasible": "NO", "solver_feasibility_status": production_status},
    ]
    return rows, certificate


def effective_curve_rows(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Materialize weighted request+regulator curves from exact solver POTs."""
    rows: list[dict[str, Any]] = []
    for record in trace["request_pair_results"]:
        request_points: dict[float, float] = {}
        regulator_points: dict[float, float] = {}
        request_path = Path(record["request_pot_path"]) if record.get("request_pot_path") else None
        regulator_path = Path(record["regulator_pot_path"])
        if request_path and request_path.is_file() and record["request_pair_status"] == "REQUEST_USABLE":
            r, u = SPPCollection._read_pot(request_path)
            request_points = dict(zip(map(float, r), map(float, u)))
        rr, ru = SPPCollection._read_pot(regulator_path)
        regulator_points = dict(zip(map(float, rr), map(float, ru)))
        xs = sorted(set(request_points) | set(regulator_points))
        if not xs:
            continue
        request_x = np.asarray(sorted(request_points), dtype=float)
        request_y = np.asarray([request_points[x] for x in request_x], dtype=float)
        regulator_x = np.asarray(sorted(regulator_points), dtype=float)
        regulator_y = np.asarray([regulator_points[x] for x in regulator_x], dtype=float)
        for x in xs:
            request_value = float(np.interp(x, request_x, request_y)) if request_points else 0.0
            regulator_value = float(np.interp(x, regulator_x, regulator_y))
            rows.append({
                "species_pair": record["species_pair"], "distance_A": x,
                "request_component": OUTER_SCALE * request_value,
                "regulator_component": OUTER_SCALE * REGULATOR_WEIGHT * regulator_value,
                "total_effective_guidance": OUTER_SCALE * (request_value + REGULATOR_WEIGHT * regulator_value),
                "guidance_mode": record["guidance_mode"],
                "request_pot_path": str(request_path or ""), "request_pot_sha256": record.get("request_pot_hash", ""),
                "regulator_pot_path": str(regulator_path), "regulator_pot_sha256": record.get("regulator_pot_hash", ""),
                "outer_scale": OUTER_SCALE, "regulator_weight": REGULATOR_WEIGHT,
            })
    return rows
