"""Reusable family scaffold library (Paper_scaffolds_september Dataset C)."""

from __future__ import annotations

import pytest
from pymatgen.core import Composition
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.workflow.paper_scaffolds_library import (
    build_family_scaffold,
    resolve_policy,
)

_TARGETS = [
    ("CaO", "rocksalt", "Fm-3m"),
    ("AgBr", "rocksalt", "Fm-3m"),
    ("MgCr2O4", "spinel", "Fd-3m"),
    ("MgFe2O4", "spinel", "Fd-3m"),
    ("Co2SiO4", "spinel", "Fd-3m"),
    ("LiCoO2", "layered oxide", "R-3m"),
    ("NaFeO2", "layered oxide", "R-3m"),
    ("LiVO2", "layered oxide", "R-3m"),
    ("LiFePO4", "olivine phosphate", "Pnma"),
    ("Mg2SiO4", "olivine phosphate", "Pnma"),
    ("MgFeSiO4", "olivine phosphate", "Pnma"),
    ("NaMnPO4", "olivine phosphate", "Pnma"),
]


@pytest.mark.parametrize(("formula", "family", "space_group"), _TARGETS)
def test_scaffold_builds_valid_prototype(formula: str, family: str, space_group: str) -> None:
    scaffold_id, structure, orbits, prov = build_family_scaffold({"formula": formula, "family": family}, "variable")
    # prototype carries the family's higher-order topology
    detected = SpacegroupAnalyzer(structure, symprec=0.05).get_space_group_symbol()
    assert detected == space_group
    # orbits partition every site exactly once
    covered = sorted(i for o in orbits for i in o["site_indices"])
    assert covered == list(range(len(structure)))
    # exact composition is representable on the orbit partition
    comp = Composition(formula)
    scale = round(len(structure) / comp.num_atoms)
    need = {str(e): int(round(float(a) * scale)) for e, a in comp.get_el_amt_dict().items()}
    for sp, n in need.items():
        eligible = sum(len(o["site_indices"]) for o in orbits if sp in o["allowed_species"])
        assert eligible >= n
    assert prov["feasible_whole_orbit_state_count"] >= 1


def test_variable_mode_preserves_cation_dof_where_chemistry_allows() -> None:
    # mixed-cation compositions must expose >1 species on a cation orbit
    _, _, orbits, _ = build_family_scaffold({"formula": "MgFe2O4", "family": "spinel"}, "variable")
    cation_orbits = [o for o in orbits if o["orbit_id"].startswith(("tet", "oct"))]
    assert any(len(o["allowed_species"]) > 1 for o in cation_orbits)


def test_variable_mode_cation_dof_layered_and_olivine() -> None:
    _, _, orbits, _ = build_family_scaffold({"formula": "LiFePO4", "family": "olivine phosphate"}, "variable")
    m_orbits = [o for o in orbits if o["orbit_id"].startswith("m")]
    assert all(set(o["allowed_species"]) == {"Li", "Fe"} for o in m_orbits)
    _, _, orbits, _ = build_family_scaffold({"formula": "LiCoO2", "family": "layered oxide"}, "variable")
    cation = [o for o in orbits if o["orbit_id"] in {"alkali_3a", "tm_3b"}]
    assert all(set(o["allowed_species"]) == {"Li", "Co"} for o in cation)


def test_fixed_mode_pins_each_orbit_to_one_species() -> None:
    _, _, orbits, _ = build_family_scaffold({"formula": "MgFe2O4", "family": "spinel"}, "fixed")
    assert all(len(o["allowed_species"]) == 1 for o in orbits)


def test_unsupported_family_rejected() -> None:
    assert resolve_policy("garnet") is None
    with pytest.raises(ValueError):
        build_family_scaffold({"formula": "Y3Al5O12", "family": "garnet"}, "variable")


def test_infeasible_composition_rejected() -> None:
    with pytest.raises(ValueError):
        build_family_scaffold({"formula": "MgO", "family": "spinel"}, "variable")
