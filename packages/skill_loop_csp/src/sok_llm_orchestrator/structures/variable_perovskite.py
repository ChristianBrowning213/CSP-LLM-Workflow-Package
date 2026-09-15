"""Isolated controlled variable-cation Pm-3m ABX3 search space.

This experimental scaffold does not replace the historical prototype registry.
It enumerates both allocations of two distinct target cations over the 1a and
1b orbits, while fixing the target anion on the 3c orbit.  Reference roles are
intentionally absent from every construction and scoring API.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable, Mapping, Sequence


SCAFFOLD_ID = "cubic_perovskite_variable_cation_v1"


@dataclass(frozen=True)
class VariablePerovskiteCase:
    case_id: str
    composition: str
    cation_species: tuple[str, str]
    anion_species: str
    lattice_a: float

    def __post_init__(self) -> None:
        if len(set(self.cation_species)) != 2:
            raise ValueError("variable-cation scaffold requires two distinct cations")
        if self.anion_species in self.cation_species:
            raise ValueError("the target anion cannot also be a cation candidate")
        if self.lattice_a <= 0:
            raise ValueError("lattice_a must be positive")


@dataclass(frozen=True)
class PerovskiteAssignment:
    assignment_id: str
    a_site_species: str
    b_site_species: str
    x_site_species: str
    formula_valid: bool
    symmetry_valid: bool
    orbit_closure_valid: bool
    canonical_structure_hash: str


@dataclass(frozen=True)
class PairContribution:
    species_pair: str
    coefficient_pair: str
    distance: float
    periodic_multiplicity: int
    pair_score: float
    weighted_contribution: float


@dataclass(frozen=True)
class AssignmentScore:
    assignment_id: str
    score: float | None
    required_pair_coverage_percent: float
    decomposition: tuple[PairContribution, ...]
    missing_coefficient_pairs: tuple[str, ...]
    objective_condition: str


def structure_for_assignment(case: VariablePerovskiteCase, a_species: str, b_species: str):
    """Construct a fixed-lattice primitive Pm-3m ABX3 structure."""
    if {a_species, b_species} != set(case.cation_species):
        raise ValueError("A/B sites must contain exactly the two target cations")
    from pymatgen.core import Lattice, Structure

    return Structure(
        Lattice.cubic(case.lattice_a),
        [a_species, b_species, case.anion_species, case.anion_species, case.anion_species],
        [
            (0.0, 0.0, 0.0),       # 1a
            (0.5, 0.5, 0.5),       # 1b
            (0.5, 0.5, 0.0),       # 3c orbit
            (0.5, 0.0, 0.5),
            (0.0, 0.5, 0.5),
        ],
    )


def enumerate_feasible_assignments(case: VariablePerovskiteCase) -> tuple[PerovskiteAssignment, ...]:
    """Enumerate the two formula-valid cation permutations; no objective used."""
    from pymatgen.core import Composition
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    c1, c2 = sorted(case.cation_species)
    assignments: list[PerovskiteAssignment] = []
    for index, (a_species, b_species) in enumerate(((c1, c2), (c2, c1)), start=1):
        structure = structure_for_assignment(case, a_species, b_species)
        analyzer = SpacegroupAnalyzer(structure, symprec=1e-3)
        formula_valid = (
            structure.composition.reduced_composition
            == Composition(case.composition).reduced_composition
        )
        symmetry_valid = analyzer.get_space_group_symbol() == "Pm-3m"
        assignments.append(
            PerovskiteAssignment(
                assignment_id=f"{case.case_id}-assignment-{index:02d}",
                a_site_species=a_species,
                b_site_species=b_species,
                x_site_species=case.anion_species,
                formula_valid=formula_valid,
                symmetry_valid=symmetry_valid,
                orbit_closure_valid=True,  # whole 1a, 1b and 3c orbits are occupied
                canonical_structure_hash=canonical_structure_hash(structure),
            )
        )
    return tuple(assignments)


def canonical_structure_hash(structure) -> str:
    payload = {
        "lattice": [round(float(value), 10) for row in structure.lattice.matrix for value in row],
        "sites": sorted(
            (
                str(site.specie),
                *[round(float(value) % 1.0, 10) for value in site.frac_coords],
            )
            for site in structure
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def score_assignment(
    case: VariablePerovskiteCase,
    assignment: PerovskiteAssignment,
    curves: Mapping[str, Sequence[tuple[float, float]]],
    *,
    label_swapped: bool = False,
) -> AssignmentScore:
    """Score cation-X terms, optionally swapping only cation-X curve identities.

    The fixed ABX3 cell contains three A-X contacts at a/sqrt(2) and six B-X
    contacts at a/2 under the periodic first coordination shell.  This compact
    decomposition is the controlled role-allocation objective; constant A-B and
    X-X terms cannot alter the ranking and are omitted.
    """
    other = {
        case.cation_species[0]: case.cation_species[1],
        case.cation_species[1]: case.cation_species[0],
    }
    terms = (
        (assignment.a_site_species, case.lattice_a / (2.0**0.5), 3),
        (assignment.b_site_species, case.lattice_a / 2.0, 6),
    )
    decomposition: list[PairContribution] = []
    missing: list[str] = []
    for actual_cation, distance, multiplicity in terms:
        coefficient_cation = other[actual_cation] if label_swapped else actual_cation
        actual_pair = canonical_pair(actual_cation, case.anion_species)
        coefficient_pair = canonical_pair(coefficient_cation, case.anion_species)
        curve = curves.get(coefficient_pair)
        if not curve:
            missing.append(coefficient_pair)
            continue
        value = interpolate(curve, distance)
        decomposition.append(
            PairContribution(
                species_pair=actual_pair,
                coefficient_pair=coefficient_pair,
                distance=distance,
                periodic_multiplicity=multiplicity,
                pair_score=value,
                weighted_contribution=value * multiplicity,
            )
        )
    required = 2
    covered = required - len(set(missing))
    score = sum(term.weighted_contribution for term in decomposition) if covered == required else None
    return AssignmentScore(
        assignment_id=assignment.assignment_id,
        score=score,
        required_pair_coverage_percent=100.0 * covered / required,
        decomposition=tuple(decomposition),
        missing_coefficient_pairs=tuple(sorted(set(missing))),
        objective_condition="LABEL_SWAPPED_SPP_CONTROL" if label_swapped else "CORRECT_SPP",
    )


def select_minimum_score(scores: Iterable[AssignmentScore]) -> AssignmentScore | None:
    complete = [score for score in scores if score.score is not None]
    return min(complete, key=lambda score: (float(score.score), score.assignment_id)) if complete else None


def canonical_pair(left: str, right: str) -> str:
    return "-".join(sorted((left, right), key=str.lower))


def interpolate(curve: Sequence[tuple[float, float]], distance: float) -> float:
    points = sorted((float(x), float(y)) for x, y in curve)
    if not points:
        raise ValueError("cannot interpolate an empty curve")
    if distance <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if distance <= x1:
            if abs(x1 - x0) < 1e-12:
                return y1
            fraction = (distance - x0) / (x1 - x0)
            return y0 + fraction * (y1 - y0)
    return points[-1][1]


__all__ = [
    "AssignmentScore", "PairContribution", "PerovskiteAssignment", "SCAFFOLD_ID",
    "VariablePerovskiteCase", "canonical_pair", "canonical_structure_hash",
    "enumerate_feasible_assignments", "score_assignment", "select_minimum_score",
    "structure_for_assignment",
]
