from __future__ import annotations

import numpy as np
from ase import Atoms
from pymatgen.io.cif import CifWriter

from qlip.allocation import Allocation
from qlip.scaffolds.exclusion import (
    add_reference_assignment_exclusion,
    resolve_reference_assignment,
    solve_after_reference_exclusion,
)
from qlip.scaffolds.topk import _default_structure


class _ZeroCost:
    include_diagonal_pair_terms = False

    def pair_cost_matrix(self, pair, positions):
        return np.zeros((len(positions), len(positions)), dtype=float)


def _allocation():
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


def test_explicit_reference_assignment_adds_only_one_exact_no_good_cut() -> None:
    allocation = _allocation()
    result = add_reference_assignment_exclusion(allocation, reference_assignment=["Li", "Na"])
    assert result.reference_assignment_resolved
    assert result.excluded_assignment == ("Li", "Na")
    assert result.exclusion_constraint_added
    assert len(allocation.m.reference_assignment_exclusions) == 1
    solved = solve_after_reference_exclusion(allocation, result)
    assert solved.alternative_found
    assert solved.alternative_structure_match_to_reference is True


def test_orbit_species_map_resolves_full_assignment() -> None:
    allocation = _allocation()
    assignment, source = resolve_reference_assignment(
        allocation, excluded_orbit_species_map={"a": "Li", "b": "Na"},
    )
    assert assignment == ("Li", "Na")
    assert source == "excluded_orbit_species_map"


def test_reference_cif_maps_to_candidate_sites(tmp_path) -> None:
    allocation = _allocation()
    reference = _default_structure(allocation, ("Li", "Na"))
    path = tmp_path / "reference.cif"
    path.write_text(str(CifWriter(reference, symprec=None)) + "\n", encoding="utf-8")
    assignment, source = resolve_reference_assignment(allocation, reference_cif=path)
    assert assignment == ("Li", "Na")
    assert source == "reference_cif"


def test_incomplete_orbit_map_returns_structured_non_added_result() -> None:
    allocation = _allocation()
    result = add_reference_assignment_exclusion(allocation, excluded_orbit_species_map={"a": "Li"})
    assert not result.reference_assignment_resolved
    assert not result.exclusion_constraint_added
    assert "missing orbit" in (result.rejection_reason or "")


def test_exclusion_result_makes_no_novelty_claim() -> None:
    payload = add_reference_assignment_exclusion(_allocation(), reference_assignment=["Li", "Na"]).to_dict()
    assert "novel" not in payload
    assert set(payload) >= {
        "reference_assignment_resolved", "excluded_assignment", "exclusion_constraint_added",
        "alternative_found", "alternative_structure_match_to_reference",
    }
