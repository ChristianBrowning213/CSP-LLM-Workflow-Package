from __future__ import annotations

from pymatgen.core import Lattice, Structure
from pymatgen.core.periodic_table import DummySpecies

from crystal_db.ordered_validation import is_fully_ordered_structure


def structure_with_species(species) -> Structure:
    return Structure(Lattice.cubic(5), [species], [[0, 0, 0]])


def test_fully_occupied_ordered_structures_pass():
    lifepo4 = Structure(
        Lattice.orthorhombic(10.3, 6.0, 4.7),
        ["Li", "Fe", "P", "O"],
        [[0, 0, 0], [0.25, 0.25, 0.25], [0.5, 0.5, 0.5], [0.75, 0.75, 0.75]],
    )
    li6ps5cl = Structure(
        Lattice.cubic(10),
        ["Li", "P", "S", "Cl"],
        [[0, 0, 0], [0.25, 0.25, 0.25], [0.5, 0.5, 0.5], [0.75, 0.75, 0.75]],
    )

    assert is_fully_ordered_structure(lifepo4)["ordered"] is True
    assert is_fully_ordered_structure(li6ps5cl)["ordered"] is True


def test_mixed_species_site_is_rejected_even_when_total_occupancy_is_one():
    result = is_fully_ordered_structure(structure_with_species({"Cl": 0.5, "Br": 0.5}))

    assert result["ordered"] is False
    assert result["offending_sites"][0]["reason"] == "MIXED_SPECIES_SITE"


def test_partial_and_point_eight_occupancies_are_rejected():
    for occupancy in (0.99, 0.8):
        result = is_fully_ordered_structure(structure_with_species({"Li": occupancy}))

        assert result["ordered"] is False
        assert result["offending_sites"][0]["reason"] == "PARTIAL_OCCUPANCY"


def test_dummy_species_is_rejected():
    result = is_fully_ordered_structure(structure_with_species(DummySpecies("Xx")))

    assert result["ordered"] is False
    assert result["offending_sites"][0]["reason"] == "DUMMY_SPECIES"
