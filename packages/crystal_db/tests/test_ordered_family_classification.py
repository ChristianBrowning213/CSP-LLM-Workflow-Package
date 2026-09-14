from __future__ import annotations

from pymatgen.core import Lattice, Structure

from crystal_db.ordered_family_classification import classify_ordered_family


def pnma_structure(species: list, coordinates: list[list[float]]) -> Structure:
    return Structure.from_spacegroup(
        "Pnma",
        Lattice.orthorhombic(10.2, 6.0, 4.8),
        species,
        coordinates,
    )


def test_olivine_phosphate_and_silicate_prototypes_are_accepted_and_subtyped():
    phosphate = pnma_structure(
        ["Li", "Fe", "P", "O", "O"],
        [
            [0.1, 0.25, 0.1],
            [0, 0, 0],
            [0.4, 0.25, 0.6],
            [0.25, 0.1, 0.3],
            [0.35, 0.4, 0.2],
        ],
    )
    silicate = pnma_structure(
        ["Mg", "Si", "O", "O"],
        [[0.1, 0.1, 0.1], [0.4, 0.25, 0.6], [0.25, 0.1, 0.3], [0.35, 0.4, 0.2]],
    )

    phosphate_result = classify_ordered_family("OLIVINE", phosphate, [("phosphate", phosphate)])
    silicate_result = classify_ordered_family("OLIVINE", silicate, [("silicate", silicate)])

    assert phosphate_result["accepted"] is True
    assert phosphate_result["subtype"] == "OLIVINE_LIMPO4"
    assert silicate_result["accepted"] is True
    assert silicate_result["subtype"] == "OLIVINE_SILICATE"


def test_generic_pnma_and_non_olivine_abxo4_are_rejected_without_prototype_match():
    reference = pnma_structure(
        ["Li", "Fe", "P", "O", "O"],
        [
            [0.1, 0.25, 0.1],
            [0, 0, 0],
            [0.4, 0.25, 0.6],
            [0.25, 0.1, 0.3],
            [0.35, 0.4, 0.2],
        ],
    )
    false_positive = pnma_structure(
        ["Na", "Zn", "As", "O"],
        [[0.02, 0.25, 0.45], [0.33, 0.1, 0.12], [0.48, 0.25, 0.02], [0.05, 0.45, 0.4]],
    )

    result = classify_ordered_family("OLIVINE", false_positive, [("olivine", reference)])

    assert result["accepted"] is False
    assert result["decision_reason"] == "REJECT_NOT_FAMILY_PROTOTYPE"


def test_canonical_li_argyrodite_requires_structure_match_not_chemistry_alone():
    reference = Structure.from_spacegroup(
        "F-43m",
        Lattice.cubic(10),
        ["Li", "P", "S", "Cl"],
        [[0.12, 0.12, 0.12], [0, 0, 0], [0.25, 0.25, 0.25], [0.5, 0.5, 0.5]],
    )
    chemistry_only = Structure.from_spacegroup(
        "F-43m",
        Lattice.cubic(14),
        ["Li", "P", "S", "Cl"],
        [[0.31, 0.31, 0.31], [0.2, 0.2, 0.2], [0.42, 0.42, 0.42], [0.5, 0.5, 0.5]],
    )

    accepted = classify_ordered_family("ARGYRODITE", reference, [("li-parent", reference)])
    rejected = classify_ordered_family("ARGYRODITE", chemistry_only, [("li-parent", reference)])

    assert accepted["accepted"] is True
    assert accepted["subtype"] == "LI_ARGYRODITE"
    assert rejected["accepted"] is False


def test_disordered_argyrodite_is_rejected_before_family_matching():
    ordered = Structure.from_spacegroup(
        "F-43m",
        Lattice.cubic(10),
        ["Li", "P", "S", "Cl"],
        [[0.12, 0.12, 0.12], [0, 0, 0], [0.25, 0.25, 0.25], [0.5, 0.5, 0.5]],
    )
    disordered = ordered.copy()
    disordered.replace(0, {"Li": 0.5, "Ag": 0.5})

    result = classify_ordered_family("ARGYRODITE", disordered, [("li-parent", ordered)])

    assert result["accepted"] is False
    assert result["decision_reason"] == "REJECT_DISORDERED_SOURCE"
