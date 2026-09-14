from pymatgen.core import Lattice, Structure

from crystal_db.family_classification import (
    classify_layered_battery_oxide,
    classify_spinel_oxide,
)


def layered_licoo2() -> Structure:
    return Structure.from_spacegroup(
        "R-3m",
        Lattice.hexagonal(2.82, 14.05),
        ["Li", "Co", "O"],
        [[0, 0, 0], [0, 0, 0.5], [0, 0, 0.24]],
    )


def spinel_mgal2o4() -> Structure:
    return Structure.from_spacegroup(
        "Fd-3m",
        Lattice.cubic(8.08),
        ["Mg", "Al", "O"],
        [[0.5, 0.5, 0.5], [0.125, 0.125, 0.125], [0.36, 0.36, 0.36]],
    )


def test_valid_layered_candidate_is_accepted():
    decision = classify_layered_battery_oxide(
        layered_licoo2(),
        working_ion="Li",
        robocrys_description=(
            "LiCoO2 is Caswellsilverite structured. Co is bonded to six O atoms "
            "to form edge-sharing CoO6 octahedra."
        ),
    )
    assert decision.accepted


def test_obvious_spinel_is_rejected_from_layered():
    decision = classify_layered_battery_oxide(
        spinel_mgal2o4(),
        working_ion="Li",
        robocrys_description="This is a spinel structure.",
    )
    assert not decision.accepted
    assert "WRONG_WORKING_ION" in decision.reason_codes or "WRONG_FAMILY" in decision.reason_codes


def test_valid_spinel_is_accepted():
    decision = classify_spinel_oxide(
        spinel_mgal2o4(), robocrys_description="MgAl2O4 adopts the normal spinel structure."
    )
    assert decision.accepted


def test_ab2o4_is_not_accepted_from_formula_and_space_group_alone():
    structure = Structure.from_spacegroup(
        "Fd-3m",
        Lattice.cubic(8.08),
        ["Mg", "Al", "O"],
        [[0.5, 0.5, 0.5], [0.125, 0.125, 0.125], [0.261, 0.261, 0.261]],
    )
    decision = classify_spinel_oxide(structure, robocrys_description="An oxide crystal.")
    assert not decision.accepted
    assert "CLASSIFICATION_UNCERTAIN" in decision.reason_codes
    assert decision.evidence["formula_compatible"]
    assert decision.evidence["space_group_227_signal"]


def test_disordered_candidate_is_rejected():
    structure = layered_licoo2()
    structure.replace(0, {"Li": 0.5, "Na": 0.5})
    decision = classify_layered_battery_oxide(
        structure, working_ion="Li", robocrys_description="A layered oxide."
    )
    assert decision.reason_codes == ("DISORDERED",)


def test_oversized_candidate_is_rejected():
    structure = layered_licoo2() * (3, 3, 3)
    decision = classify_layered_battery_oxide(
        structure,
        working_ion="Li",
        robocrys_description="A layered oxide.",
        max_primitive_sites=3,
    )
    assert decision.reason_codes == ("TOO_LARGE",)
