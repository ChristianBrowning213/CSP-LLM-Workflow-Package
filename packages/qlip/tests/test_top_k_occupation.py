from __future__ import annotations

import numpy as np
from ase import Atoms
from pymatgen.core import Lattice, Structure

from qlip.allocation import Allocation
from qlip.scaffolds.topk import enumerate_top_k


class _ZeroCost:
    include_diagonal_pair_terms = False

    def pair_cost_matrix(self, pair, positions):
        return np.zeros((len(positions), len(positions)), dtype=float)


def _allocation() -> Allocation:
    allocation = Allocation(Atoms("LiNa"))
    allocation.positions = Atoms("H2", cell=[4.0, 4.0, 4.0], pbc=True)
    allocation.positions.set_scaled_positions([[0, 0, 0], [0.25, 0.25, 0.25]])
    allocation.cost = _ZeroCost()
    allocation.ordered_orbits = [
        {"orbit_id": "a", "site_indices": [0], "allowed_species": ["Li", "Na"], "required_occupancy": True},
        {"orbit_id": "b", "site_indices": [1], "allowed_species": ["Li", "Na"], "required_occupancy": True},
    ]
    allocation.encode()
    return allocation


def _structure_distinct_builder(allocation, assignment):
    separation = 0.08 if assignment[0] == "Li" else 0.45
    return Structure(Lattice.cubic(4), ["Li", "Na"], [[0, 0, 0], [separation] * 3])


def test_assignment_distinct_counts_two_real_occupation_vectors() -> None:
    result = enumerate_top_k(_allocation(), 2, distinctness_policy="ASSIGNMENT_DISTINCT")
    assert result.distinctness_policy == "ASSIGNMENT_DISTINCT"
    assert result.requested_k == 2
    assert result.assignment_unique_count == 2
    assert result.termination_reason == "K_REACHED"
    assert result.no_good_cuts_added == 2


def test_structure_equivalent_assignments_do_not_reach_structure_k() -> None:
    result = enumerate_top_k(_allocation(), 2, distinctness_policy="STRUCTURE_DISTINCT")
    assert result.solver_solutions_seen == 2
    assert result.assignment_unique_count == 2
    assert result.structurematcher_unique_count == 1
    assert result.symmetry_equivalent_count == 1
    assert result.assignments_rejected_by_structurematcher == 1
    assert result.termination_reason == "NO_ADDITIONAL_DISTINCT_STRUCTURE"


def test_genuinely_structure_distinct_candidates_reach_k() -> None:
    result = enumerate_top_k(
        _allocation(), 2,
        distinctness_policy="STRUCTURE_DISTINCT",
        structure_builder=_structure_distinct_builder,
    )
    assert result.distinctness_policy == "STRUCTURE_DISTINCT"
    assert result.structurematcher_unique_count == 2
    assert result.termination_reason == "K_REACHED"


def test_k_exceeds_structure_distinct_feasible_space() -> None:
    result = enumerate_top_k(_allocation(), 3, distinctness_policy="STRUCTURE_DISTINCT")
    assert result.requested_k > result.structurematcher_unique_count
    assert result.assignment_unique_count == 2
    assert result.no_good_cuts_added == 2
    assert result.termination_reason == "NO_ADDITIONAL_DISTINCT_STRUCTURE"


def test_hash_distinct_counts_canonical_hashes_even_when_structures_match() -> None:
    hash_result = enumerate_top_k(_allocation(), 2, distinctness_policy="HASH_DISTINCT")
    structure_result = enumerate_top_k(_allocation(), 2, distinctness_policy="STRUCTURE_DISTINCT")
    assert hash_result.canonical_hash_unique_count == 2
    assert hash_result.structurematcher_unique_count == 1
    assert hash_result.termination_reason == "K_REACHED"
    assert structure_result.canonical_hash_unique_count == 2
    assert structure_result.structurematcher_unique_count == 1
    assert structure_result.termination_reason == "NO_ADDITIONAL_DISTINCT_STRUCTURE"


def test_hash_duplicate_is_excluded_and_no_good_cut_still_added() -> None:
    constant = Structure(Lattice.cubic(4), ["Li", "Na"], [[0, 0, 0], [0.2, 0.2, 0.2]])
    result = enumerate_top_k(
        _allocation(), 2,
        distinctness_policy="HASH_DISTINCT",
        structure_builder=lambda allocation, assignment: constant,
    )
    assert result.assignment_unique_count == 2
    assert result.canonical_hash_unique_count == 1
    assert result.assignments_rejected_by_hash == 1
    assert result.no_good_cuts_added == 2
    assert result.termination_reason == "NO_ADDITIONAL_DISTINCT_STRUCTURE"
