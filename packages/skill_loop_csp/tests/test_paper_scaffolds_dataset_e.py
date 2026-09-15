from __future__ import annotations

from collections import Counter

import pytest

from sok_llm_orchestrator.workflow.dataset_e_validation import (
    load_development_references,
    validate_dataset_e_topology,
)
from sok_llm_orchestrator.workflow.paper_scaffolds_dataset_e import (
    build_dataset_e_alternatives,
)


@pytest.mark.parametrize(
    ("subtype", "formula", "site_count"),
    [
        ("NASICON_R3_PHOSPHATE", "Na3Ti2P3O12", 40),
        ("RP_N1", "Sr2TiO4", 7),
        ("RP_N2", "Sr3Ti2O7", 12),
        ("GARNET_IA3D", "Y3Al5O12", 80),
        ("GARNET_I41ACD", "Li7La3Hf2O12", 96),
        ("ARGYRODITE_F43M", "Li6PS5Cl", 13),
        ("ARGYRODITE_PNA21", "Ag8GeS6", 60),
        ("ARGYRODITE_CC", "Li6AsS5I", 26),
    ],
)
def test_development_chemistries_are_exact_and_ordered(subtype, formula, site_count):
    alternatives = build_dataset_e_alternatives(
        {"formula": formula, "family": subtype.split("_")[0], "topology_subclass": subtype}
    )
    assert alternatives
    for item in alternatives:
        assert len(item.structure) == site_count
        assert item.structure.composition.reduced_composition == item.structure.composition.__class__(
            formula
        ).reduced_composition
        assert item.structure.is_ordered
        assert item.feasible_state_count == 1
        covered = [index for orbit in item.ordered_orbits for index in orbit["site_indices"]]
        assert Counter(covered) == Counter(range(site_count))
        assert item.provenance["target_coordinates_consumed"] is False
        assert item.provenance["target_lattice_consumed"] is False


def test_role_mismatch_is_not_silently_mapped():
    with pytest.raises(ValueError, match="no development-derived"):
        build_dataset_e_alternatives(
            {"formula": "Li6PCl5S", "family": "ARGYRODITE", "topology_subclass": "ARGYRODITE_F43M"}
        )


@pytest.mark.parametrize(
    ("subtype", "formula"),
    [
        ("NASICON_R3_PHOSPHATE", "Na6 V4 P6 O24"),
        ("RP_N2", "Eu3 V2 O7"),
        ("RP_N1", "La2 Cu1 O4"),
        ("GARNET_IA3D", "Lu12 Al20 O48"),
        ("GARNET_I41ACD", "Li28 Nd12 Zr8 O48"),
        ("ARGYRODITE_CC", "Cu12 P2 S10 Br2"),
        ("ARGYRODITE_PNA21", "Ag32 Sn4 S24"),
    ],
)
def test_corpus_style_final_formula_is_representable(subtype, formula):
    assert build_dataset_e_alternatives(
        {"formula": formula, "family": subtype.split("_")[0], "topology_subclass": subtype}
    )


@pytest.mark.parametrize(
    "subtype",
    [
        "NASICON_R3_PHOSPHATE",
        "RP_N1",
        "RP_N2",
        "GARNET_IA3D",
        "GARNET_I41ACD",
        "ARGYRODITE_F43M",
        "ARGYRODITE_PNA21",
        "ARGYRODITE_CC",
    ],
)
def test_validator_accepts_its_frozen_development_reference(subtype):
    _, structure = load_development_references(subtype)[0]
    result = validate_dataset_e_topology(structure, subtype)
    assert result["status"] == "PASS"
    assert result["ordered"] is True
    assert result["match_count"] >= 1


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("RP_N1", "RP_N2"),
        ("GARNET_IA3D", "GARNET_I41ACD"),
        ("ARGYRODITE_F43M", "ARGYRODITE_PNA21"),
        ("ARGYRODITE_PNA21", "ARGYRODITE_CC"),
        ("NASICON_R3_PHOSPHATE", "GARNET_IA3D"),
    ],
)
def test_validator_rejects_cross_topology_reference(left, right):
    _, structure = load_development_references(left)[0]
    assert validate_dataset_e_topology(structure, right)["status"] == "FAIL"
