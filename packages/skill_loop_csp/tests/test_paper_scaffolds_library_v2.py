from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pymatgen.core import Composition

from sok_llm_orchestrator.workflow.paper_scaffolds_library_v2 import (
    SCAFFOLD_LIBRARY_VERSION,
    build_family_scaffold_alternatives,
    select_objective_minimum,
)


V1_PATH = Path("src/sok_llm_orchestrator/workflow/paper_scaffolds_library.py")
V1_SHA256 = "0fb5ab282fa5e6d672841daceaa4ddd25e148b8b4c907c821322fe6341757043"


def test_v1_source_remains_frozen() -> None:
    assert hashlib.sha256(V1_PATH.read_bytes()).hexdigest() == V1_SHA256


@pytest.mark.parametrize(
    ("formula", "family", "minimum_states"),
    [("CaO", "rocksalt", 1), ("MgFe2O4", "spinel", 3), ("LiCoO2", "layered oxide", 2), ("LiFePO4", "olivine", 2)],
)
def test_v2_is_deterministic_ordered_exact_and_topology_partitioned(formula, family, minimum_states):
    first = build_family_scaffold_alternatives({"formula": formula, "family": family})
    second = build_family_scaffold_alternatives({"formula": formula, "family": family})
    assert [item.canonical_hash() for item in first] == [item.canonical_hash() for item in second]
    assert all(item.provenance["scaffold_library_version"] == SCAFFOLD_LIBRARY_VERSION for item in first)
    for item in first:
        covered = [index for orbit in item.ordered_orbits for index in orbit["site_indices"]]
        assert sorted(covered) == list(range(len(item.structure)))
        assert len(covered) == len(set(covered))
        assert all(orbit["required_occupancy"] for orbit in item.ordered_orbits)
        assert all(not orbit["vacancy_allowed"] for orbit in item.ordered_orbits)
        assert all(not orbit["allow_partial_occupation"] for orbit in item.ordered_orbits)
        assert item.feasible_state_count >= minimum_states
        scale = len(item.structure) / Composition(formula).num_atoms
        assert scale == round(scale)


def test_spinel_has_normal_and_two_ordered_inverse_compatible_states() -> None:
    alternatives = build_family_scaffold_alternatives({"formula": "MgFe2O4", "family": "spinel"})
    assert len(alternatives) == 9
    assert {item.feasible_state_count for item in alternatives} == {3}
    assert all([len(orbit["site_indices"]) for orbit in item.ordered_orbits[:3]] == [8, 8, 8] for item in alternatives)


def test_frozen_olivine_vanadate_subclass_uses_v_as_tetrahedral_former() -> None:
    alternatives = build_family_scaffold_alternatives({"formula": "LiMnVO4", "family": "olivine"})
    assert len(alternatives) == 3
    assert {item.feasible_state_count for item in alternatives} == {2}
    for item in alternatives:
        tetrahedral = next(orbit for orbit in item.ordered_orbits if orbit["orbit_id"] == "t_4c")
        assert tetrahedral["fixed_species"] == "V"


def test_geometry_uses_leakage_filtered_evidence_and_never_target_coordinates() -> None:
    records = [
        {"structure_id": "target", "formula": "CaO", "vpa_A3_per_atom": 99},
        {"structure_id": "a", "formula": "MgO", "vpa_A3_per_atom": 12},
        {"structure_id": "b", "formula": "NaCl", "vpa_A3_per_atom": 20},
        {"structure_id": "c", "formula": "AgBr", "vpa_A3_per_atom": 30},
    ]
    alternatives = build_family_scaffold_alternatives({"formula": "CaO", "family": "rocksalt"}, evidence_records=records)
    assert [item.provenance["vpa_A3_per_atom"] for item in alternatives] == [12, 20, 30]
    assert all(not item.provenance["target_coordinates_consumed"] for item in alternatives)
    assert all(not item.provenance["target_lattice_consumed"] for item in alternatives)
    assert all("target" not in item.provenance["cell_evidence"]["evidence_record_ids"] for item in alternatives)


def test_unsupported_subclass_and_invalid_compositions_fail_clearly() -> None:
    with pytest.raises(ValueError, match="no supported topology"):
        build_family_scaffold_alternatives({"formula": "Na2MnO2", "family": "layered oxide", "topology_subclass": "P2"})
    with pytest.raises(ValueError, match="exactly two cation"):
        build_family_scaffold_alternatives({"formula": "MgO", "family": "spinel"})


def test_objective_selection_requires_solver_scorer_equality() -> None:
    rows = [
        {"alternative_id": "b", "solver_status": "OPTIMAL", "solver_objective": 2.0, "independent_objective": 2.0},
        {"alternative_id": "a", "solver_status": "OPTIMAL", "solver_objective": 1.0, "independent_objective": 1.0},
    ]
    assert select_objective_minimum(rows)["alternative_id"] == "a"
    rows[0]["independent_objective"] = 3.0
    with pytest.raises(ValueError, match="solver/scorer disagreement"):
        select_objective_minimum(rows)
