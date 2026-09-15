from __future__ import annotations

import numpy as np
import pyomo.environ as pyo
from ase import Atoms

from qlip.allocation import Allocation
from qlip.scaffolds.occupation import VACANCY_STATE, preflight_ordered_occupation


class _ZeroCost:
    include_diagonal_pair_terms = False

    def pair_cost_matrix(self, pair, positions):
        return np.zeros((len(positions), len(positions)), dtype=float)


def _orbit(orbit_id, indices, allowed, **extra):
    return {
        "orbit_id": orbit_id,
        "site_indices": indices,
        "allowed_species": allowed,
        "required_occupancy": True,
        **extra,
    }


def test_binary_si_p_ordered_occupation() -> None:
    result = preflight_ordered_occupation(
        "SiP",
        4,
        [_orbit("tet_a", [0, 1], ["Si", "P"]), _orbit("tet_b", [2, 3], ["Si", "P"])],
    )
    assert result.stoichiometry_representable
    assert result.representable_composition == {"P": 2, "Si": 2, VACANCY_STATE: 0}


def test_phosphate_only_fixed_framework() -> None:
    result = preflight_ordered_occupation(
        "NaZr2P3O12",
        18,
        [
            _orbit("na", [0], ["Na"], fixed_species="Na"),
            _orbit("zr", [1, 2], ["Zr"], fixed_species="Zr"),
            _orbit("p", [3, 4, 5], ["P"], fixed_species="P"),
            _orbit("o", list(range(6, 18)), ["O"], fixed_species="O"),
        ],
    )
    assert result.stoichiometry_representable
    assert result.formula_units == 1


def test_three_variable_species_are_supported() -> None:
    result = preflight_ordered_occupation(
        "LiNaK",
        6,
        [
            _orbit("a", [0, 1], ["Li", "Na", "K"]),
            _orbit("b", [2, 3], ["Li", "Na", "K"]),
            _orbit("c", [4, 5], ["Li", "Na", "K"]),
        ],
    )
    assert result.stoichiometry_representable
    assert result.representable_composition == {"K": 2, "Li": 2, "Na": 2, VACANCY_STATE: 0}


def test_explicit_vacancy_is_a_real_model_state() -> None:
    orbits = [
        _orbit("li", [0, 1], ["Li"], fixed_species="Li"),
        _orbit("o", [2], ["O"], fixed_species="O"),
        _orbit(
            "empty",
            [3],
            [VACANCY_STATE],
            required_occupancy=False,
            required_state="EMPTY",
            vacancy_allowed=True,
        ),
    ]
    result = preflight_ordered_occupation("Li2O", 4, orbits, vacancy_count=1)
    assert result.stoichiometry_representable
    allocation = Allocation(Atoms("Li2O"))
    allocation.positions = Atoms("H4", cell=[4.0, 4.0, 4.0], pbc=True)
    allocation.positions.set_scaled_positions([[0, 0, 0], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5]])
    allocation.cost = _ZeroCost()
    allocation.ordered_orbits = orbits
    allocation.explicit_vacancy_count = 1
    allocation.encode()
    assert hasattr(allocation.m, "vacancy")
    assert allocation.m.vacancy[3].value == 0
    assert not allocation.m.vacancy[3].fixed
    assert all(allocation.m.vacancy[index].fixed for index in (0, 1, 2))
    assert pyo.value(allocation.m.vacancy_count.upper) == 1
    solver = pyo.SolverFactory("gurobi")
    assert solver.available(exception_flag=False)
    solved = solver.solve(allocation.m, tee=False)
    assert solved.solver.termination_condition == pyo.TerminationCondition.optimal
    assert pyo.value(allocation.m.vacancy[3]) == 1
    assert sum(round(pyo.value(allocation.m.vacancy[index])) for index in range(4)) == 1


def test_vacancy_enabled_orbit_has_active_species_plus_vacancy_closure() -> None:
    orbits = [
        _orbit(
            "mobile",
            [0, 1],
            ["Li", VACANCY_STATE],
            required_occupancy=False,
            vacancy_allowed=True,
            allow_partial_occupation=True,
        )
    ]
    allocation = Allocation(Atoms("Li"))
    allocation.positions = Atoms("H2", cell=[4.0, 4.0, 4.0], pbc=True)
    allocation.cost = _ZeroCost()
    allocation.ordered_orbits = orbits
    allocation.explicit_vacancy_count = 1
    allocation.encode()
    assert all(not allocation.m.vacancy[index].fixed for index in (0, 1))
    assert allocation.vacancy_state_diagnostics["vacancy_enabled_site_indices"] == [0, 1]
    for index in (0, 1):
        allocation.m.x["Li", index].set_value(index == 0)
        allocation.m.vacancy[index].set_value(index == 1)
        assert pyo.value(allocation.m.excl[index].body) == 1


def test_vacancy_forbidden_on_specific_orbit_is_fixed_zero() -> None:
    allocation = Allocation(Atoms("LiO"))
    allocation.positions = Atoms("H2", cell=[4.0, 4.0, 4.0], pbc=True)
    allocation.cost = _ZeroCost()
    allocation.ordered_orbits = [
        _orbit("li", [0], ["Li"], fixed_species="Li"),
        _orbit("o", [1], ["O"], fixed_species="O"),
    ]
    allocation.encode()
    assert allocation.m.vacancy[0].fixed and pyo.value(allocation.m.vacancy[0]) == 0
    assert allocation.m.vacancy[1].fixed and pyo.value(allocation.m.vacancy[1]) == 0
    assert allocation.vacancy_state_diagnostics["vacancy_fixed_zero_site_indices"] == [0, 1]


def test_forbidden_species_on_every_orbit_is_rejected() -> None:
    result = preflight_ordered_occupation(
        "LiNa",
        2,
        [_orbit("a", [0], ["Li"]), _orbit("b", [1], ["Li"])],
    )
    assert not result.stoichiometry_representable
    assert "allowlists" in (result.rejection_reason or "")


def test_impossible_orbit_multiplicity_is_rejected() -> None:
    result = preflight_ordered_occupation(
        "LiNa",
        4,
        [_orbit("triple", [0, 1, 2], ["Li", "Na"]), _orbit("single", [3], ["Li", "Na"])],
    )
    assert not result.stoichiometry_representable
    assert result.orbit_multiplicity_equations


def test_impossible_vacancy_and_stoichiometry_is_rejected_structurally() -> None:
    result = preflight_ordered_occupation(
        "Li2O",
        5,
        [
            _orbit("li", [0, 1], ["Li"], fixed_species="Li"),
            _orbit("o", [2], ["O"], fixed_species="O"),
            _orbit("empty_pair", [3, 4], [VACANCY_STATE], required_occupancy=False, required_state="EMPTY", vacancy_allowed=True),
        ],
        vacancy_count=1,
    )
    assert not result.stoichiometry_representable
    assert result.rejection_reason


def test_fixed_and_variable_orbits_mix_without_formula_specific_code() -> None:
    result = preflight_ordered_occupation(
        "LiNaK",
        6,
        [
            _orbit("fixed_li", [0, 1], ["Li"], fixed_species="Li"),
            _orbit("mobile_a", [2, 3], ["Na", "K"]),
            _orbit("mobile_b", [4, 5], ["Na", "K"]),
        ],
    )
    assert result.stoichiometry_representable
    assert result.selected_state_by_orbit is not None
    assert result.selected_state_by_orbit["fixed_li"] == {"Li": 2}


def test_mixed_fixed_and_variable_model_serializes_disabled_vacancies() -> None:
    allocation = Allocation(Atoms("Li2Na2K2"))
    allocation.positions = Atoms("H6", cell=[6.0, 6.0, 6.0], pbc=True)
    allocation.cost = _ZeroCost()
    allocation.ordered_orbits = [
        _orbit("fixed_li", [0, 1], ["Li"], fixed_species="Li"),
        _orbit("mobile_a", [2, 3], ["Na", "K"]),
        _orbit("mobile_b", [4, 5], ["Na", "K"]),
    ]
    allocation.encode()
    diagnostics = allocation.vacancy_state_diagnostics
    assert diagnostics["representation"] == "uniform_indexed_binary"
    assert diagnostics["vacancy_enabled_site_indices"] == []
    assert diagnostics["vacancy_fixed_zero_site_indices"] == list(range(6))
    assert all(allocation.m.vacancy[index].fixed for index in range(6))
