from __future__ import annotations

from inspect import signature

import pytest
from pymatgen.core import Composition
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.structures.prototype_scaffold import ideal_prototype_structure
from sok_llm_orchestrator.structures.variable_perovskite import (
    SCAFFOLD_ID,
    VariablePerovskiteCase,
    canonical_pair,
    enumerate_feasible_assignments,
    score_assignment,
    select_minimum_score,
    structure_for_assignment,
)


CASE = VariablePerovskiteCase("cspbbr3", "CsPbBr3", ("Cs", "Pb"), "Br", 5.87)


def test_existing_fixed_halide_scaffold_is_unchanged_and_new_id_is_isolated() -> None:
    fixed = ideal_prototype_structure("halide_perovskite", "CsPbBr3")
    assert [str(site.specie) for site in fixed] == ["Cs", "Pb", "Br", "Br", "Br"]
    assert SCAFFOLD_ID == "cubic_perovskite_variable_cation_v1"
    assert SCAFFOLD_ID != "halide_perovskite"


def test_variable_scaffold_enumerates_both_exact_formula_pm3m_closed_assignments() -> None:
    assignments = enumerate_feasible_assignments(CASE)
    assert {(x.a_site_species, x.b_site_species, x.x_site_species) for x in assignments} == {
        ("Cs", "Pb", "Br"), ("Pb", "Cs", "Br")
    }
    assert all(x.formula_valid and x.symmetry_valid and x.orbit_closure_valid for x in assignments)
    assert len({x.canonical_structure_hash for x in assignments}) == 2
    for assignment in assignments:
        structure = structure_for_assignment(CASE, assignment.a_site_species, assignment.b_site_species)
        assert structure.composition.reduced_composition == Composition("CsPbBr3").reduced_composition
        assert SpacegroupAnalyzer(structure, symprec=1e-3).get_space_group_symbol() == "Pm-3m"


def test_anion_and_cations_cannot_cross_orbit_classes() -> None:
    with pytest.raises(ValueError, match="exactly the two target cations"):
        structure_for_assignment(CASE, "Br", "Pb")
    with pytest.raises(ValueError, match="exactly the two target cations"):
        structure_for_assignment(CASE, "Cs", "Br")
    assert all(x.x_site_species == "Br" for x in enumerate_feasible_assignments(CASE))


def test_correct_objective_is_independently_recomputable() -> None:
    assignment = next(x for x in enumerate_feasible_assignments(CASE) if x.a_site_species == "Cs")
    curves = {
        canonical_pair("Cs", "Br"): [(0.0, 1.0), (10.0, 1.0)],
        canonical_pair("Pb", "Br"): [(0.0, 2.0), (10.0, 2.0)],
    }
    scored = score_assignment(CASE, assignment, curves)
    assert scored.score == pytest.approx(3 * 1.0 + 6 * 2.0)
    assert scored.score == pytest.approx(sum(x.weighted_contribution for x in scored.decomposition))
    assert scored.required_pair_coverage_percent == 100.0


def test_reference_information_is_not_a_solver_or_scaffold_input() -> None:
    assert "reference" not in signature(enumerate_feasible_assignments).parameters
    assert "reference" not in signature(score_assignment).parameters
    assert "reference" not in signature(structure_for_assignment).parameters


def test_label_swap_changes_only_objective_coefficient_identity() -> None:
    assignments = enumerate_feasible_assignments(CASE)
    curves = {
        canonical_pair("Cs", "Br"): [(0.0, 0.0), (10.0, 10.0)],
        canonical_pair("Pb", "Br"): [(0.0, 10.0), (10.0, 0.0)],
    }
    correct = [score_assignment(CASE, a, curves) for a in assignments]
    swapped = [score_assignment(CASE, a, curves, label_swapped=True) for a in assignments]
    assert select_minimum_score(correct).assignment_id != select_minimum_score(swapped).assignment_id
    for assignment, normal, adversarial in zip(assignments, correct, swapped):
        assert normal.assignment_id == adversarial.assignment_id == assignment.assignment_id
        assert [(x.distance, x.periodic_multiplicity, x.species_pair) for x in normal.decomposition] == [
            (x.distance, x.periodic_multiplicity, x.species_pair) for x in adversarial.decomposition
        ]
        assert [x.coefficient_pair for x in normal.decomposition] != [x.coefficient_pair for x in adversarial.decomposition]
