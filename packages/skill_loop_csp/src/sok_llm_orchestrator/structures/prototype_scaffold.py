from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MissingSymmetryMate:
    species: str
    source_index: int
    operation_index: int
    expected_frac_coords: tuple[float, float, float]


@dataclass(frozen=True)
class SymmetryClosureReport:
    closed: bool
    space_group_number: int
    site_count: int
    missing_count: int
    missing_mates: tuple[MissingSymmetryMate, ...]


@dataclass(frozen=True)
class ScaffoldDefinition:
    key: str
    formula: str
    family: str
    space_group: str
    space_group_number: int
    crystal_system: str
    lattice: tuple[str, tuple[float, ...]]
    asymmetric_unit: tuple[tuple[str, tuple[float, float, float]], ...]
    source_note: str
    orbit_definitions: tuple[tuple[Any, ...], ...] = ()


@dataclass(frozen=True)
class ScaffoldSite:
    site_id: str
    orbit_id: str
    species: str
    frac_coords: tuple[float, float, float]


@dataclass(frozen=True)
class ScaffoldOrbit:
    orbit_id: str
    wyckoff_label: str | None
    allowed_species: tuple[str, ...]
    preferred_species: str
    multiplicity: int
    fractional_coordinates: tuple[tuple[float, float, float], ...]
    target_space_group: str
    target_space_group_number: int
    crystal_system: str


@dataclass(frozen=True)
class PrototypeScaffoldSolution:
    formula: str
    family: str
    target_space_group: str
    target_space_group_number: int
    crystal_system: str
    orbits: tuple[ScaffoldOrbit, ...]
    sites: tuple[ScaffoldSite, ...]
    symmetry_closed: bool
    variable_orbit_selection: bool = False
    selected_species_by_orbit: dict[str, str] | None = None
    selected_candidate_id: str | None = None
    objective_value: float | None = None
    spp_scoring_status: str | None = None
    spp_source: str | None = None
    spp_source_type: str | None = None
    spp_pot_dir: str | None = None
    spp_fallback_reason: str | None = None
    selected_pair_score_breakdown: list[dict[str, Any]] | None = None
    solver_backend: str | None = None
    formula_satisfied: bool | None = None


_IDEALIZED_SOURCE_NOTE = (
    "Idealized prototype scaffold using standard Wyckoff representatives; "
    "validated by pymatgen SpacegroupAnalyzer in focused tests."
)

_VARIABLE_ORBIT_SUPPORTED_FORMULAS = {
    "BaTiO3",
    "CaTiO3",
    "SrTiO3",
    "NiO",
    "MgO",
    "TiN",
    "CeO2",
    "ZrO2",
    "ThO2",
    "CsPbBr3",
    "CsSnBr3",
    "CsPbCl3",
    "CsSnI3",
    "CsPbI3",
}
_VARIABLE_PEROVSKITE_A_SITE_SPECIES = ("Ba", "Ca", "Sr")
_VARIABLE_HALIDE_PEROVSKITE_A_SITE_SPECIES = ("Cs",)
_VARIABLE_HALIDE_PEROVSKITE_B_SITE_SPECIES = ("Pb", "Sn")
_VARIABLE_HALIDE_PEROVSKITE_X_SITE_SPECIES = ("Br", "Cl", "I")
_VARIABLE_ROCKSALT_CATION_SPECIES = ("Ni", "Mg", "Ti")
_VARIABLE_ROCKSALT_ANION_SPECIES = ("O", "N")
_VARIABLE_FLUORITE_CATION_SPECIES = ("Ce", "Zr", "Th")
_VARIABLE_ORBIT_SELECTOR_BACKEND = "enumeration_backed_qlip_style_selector"
_VARIABLE_ORBIT_SPP_MODE = "prototype_orbit_variable_spp_qlip"


_SCAFFOLDS: dict[str, ScaffoldDefinition] = {
    "perovskite": ScaffoldDefinition(
        key="perovskite",
        formula="BaTiO3",
        family="perovskite",
        space_group="Pm-3m",
        space_group_number=221,
        crystal_system="cubic",
        lattice=("cubic", (4.0,)),
        asymmetric_unit=(
            ("Ba", (0.0, 0.0, 0.0)),
            ("Ti", (0.5, 0.5, 0.5)),
            ("O", (0.5, 0.5, 0.0)),
            ("O", (0.5, 0.0, 0.5)),
            ("O", (0.0, 0.5, 0.5)),
        ),
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=(
            ("ba_1a", "1a", "Ba", ("Ba",), (0.0, 0.0, 0.0)),
            ("ti_1b", "1b", "Ti", ("Ti",), (0.5, 0.5, 0.5)),
            ("o_3c", "3c", "O", ("O",), (0.5, 0.5, 0.0)),
        ),
    ),
    "halide_perovskite": ScaffoldDefinition(
        key="halide_perovskite",
        formula="CsPbBr3",
        family="halide perovskite",
        space_group="Pm-3m",
        space_group_number=221,
        crystal_system="cubic",
        lattice=("cubic", (5.87,)),
        asymmetric_unit=(
            ("Cs", (0.0, 0.0, 0.0)),
            ("Pb", (0.5, 0.5, 0.5)),
            ("Br", (0.5, 0.5, 0.0)),
            ("Br", (0.5, 0.0, 0.5)),
            ("Br", (0.0, 0.5, 0.5)),
        ),
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=(
            ("cs_1a", "1a", "Cs", ("Cs",), (0.0, 0.0, 0.0)),
            ("pb_1b", "1b", "Pb", ("Pb",), (0.5, 0.5, 0.5)),
            ("br_3c", "3c", "Br", ("Br",), (0.5, 0.5, 0.0)),
        ),
    ),
    "spinel": ScaffoldDefinition(
        key="spinel",
        formula="ZnFe2O4",
        family="spinel",
        space_group="Fd-3m",
        space_group_number=227,
        crystal_system="cubic",
        lattice=("cubic", (8.44,)),
        asymmetric_unit=(
            ("Zn", (0.0, 0.0, 0.0)),
            ("Fe", (0.625, 0.625, 0.625)),
            ("O", (0.386, 0.386, 0.386)),
        ),
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=(
            ("zn_8a", "8a", "Zn", ("Zn",), (0.0, 0.0, 0.0)),
            ("fe_16d", "16d", "Fe", ("Fe",), (0.625, 0.625, 0.625)),
            ("o_32e", "32e", "O", ("O",), (0.386, 0.386, 0.386)),
        ),
    ),
    "rocksalt": ScaffoldDefinition(
        key="rocksalt",
        formula="NiO",
        family="rocksalt",
        space_group="Fm-3m",
        space_group_number=225,
        crystal_system="cubic",
        lattice=("cubic", (4.17,)),
        asymmetric_unit=(
            ("Ni", (0.0, 0.0, 0.0)),
            ("O", (0.5, 0.5, 0.5)),
        ),
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=(
            ("ni_4a", "4a", "Ni", ("Ni",), (0.0, 0.0, 0.0)),
            ("o_4b", "4b", "O", ("O",), (0.5, 0.5, 0.5)),
        ),
    ),
    "fluorite": ScaffoldDefinition(
        key="fluorite",
        formula="CeO2",
        family="fluorite",
        space_group="Fm-3m",
        space_group_number=225,
        crystal_system="cubic",
        lattice=("cubic", (5.41,)),
        asymmetric_unit=(
            ("Ce", (0.0, 0.0, 0.0)),
            ("O", (0.25, 0.25, 0.25)),
        ),
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=(
            ("ce_4a", "4a", "Ce", ("Ce",), (0.0, 0.0, 0.0)),
            ("o_8c", "8c", "O", ("O",), (0.25, 0.25, 0.25)),
        ),
    ),
    "pyrite": ScaffoldDefinition(
        key="pyrite",
        formula="FeS2",
        family="pyrite",
        space_group="Pa-3",
        space_group_number=205,
        crystal_system="cubic",
        lattice=("cubic", (5.42,)),
        asymmetric_unit=(
            ("Fe", (0.0, 0.0, 0.0)),
            ("S", (0.385, 0.385, 0.385)),
        ),
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=(
            ("fe_4a", "4a", "Fe", ("Fe",), (0.0, 0.0, 0.0)),
            ("s_8c", "8c", "S", ("S",), (0.385, 0.385, 0.385)),
        ),
    ),
    "layered_oxide": ScaffoldDefinition(
        key="layered_oxide",
        formula="LiCoO2",
        family="layered oxide",
        space_group="R-3m",
        space_group_number=166,
        crystal_system="trigonal",
        lattice=("hexagonal", (2.815, 14.05)),
        asymmetric_unit=(
            ("Li", (0.0, 0.0, 0.0)),
            ("Co", (0.0, 0.0, 0.5)),
            ("O", (0.0, 0.0, 0.241)),
        ),
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=(
            ("li_3a", "3a", "Li", ("Li",), (0.0, 0.0, 0.0)),
            ("co_3b", "3b", "Co", ("Co",), (0.0, 0.0, 0.5)),
            ("o_6c", "6c", "O", ("O",), (0.0, 0.0, 0.241)),
        ),
    ),
    "olivine_phosphate": ScaffoldDefinition(
        key="olivine_phosphate",
        formula="LiFePO4",
        family="olivine phosphate",
        space_group="Pnma",
        space_group_number=62,
        crystal_system="orthorhombic",
        lattice=("orthorhombic", (10.33, 6.01, 4.69)),
        asymmetric_unit=(
            ("Li", (0.0, 0.0, 0.0)),
            ("Fe", (0.282, 0.25, 0.974)),
            ("P", (0.094, 0.25, 0.418)),
            ("O", (0.097, 0.25, 0.742)),
            ("O", (0.454, 0.25, 0.207)),
            ("O", (0.166, 0.046, 0.284)),
        ),
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=(
            ("li_4a", "4a", "Li", ("Li",), (0.0, 0.0, 0.0)),
            ("fe_4c", "4c", "Fe", ("Fe",), (0.282, 0.25, 0.974)),
            ("p_4c", "4c", "P", ("P",), (0.094, 0.25, 0.418)),
            ("o1_4c", "4c", "O", ("O",), (0.097, 0.25, 0.742)),
            ("o2_4c", "4c", "O", ("O",), (0.454, 0.25, 0.207)),
            ("o3_8d", "8d", "O", ("O",), (0.166, 0.046, 0.284)),
        ),
    ),
    "argyrodite": ScaffoldDefinition(
        key="argyrodite",
        formula="Li6PS5Cl",
        family="argyrodite",
        space_group="F-43m",
        space_group_number=216,
        crystal_system="cubic",
        lattice=("cubic", (9.85,)),
        asymmetric_unit=(
            ("P", (0.5, 0.5, 0.5)),
            ("S", (0.0, 0.0, 0.0)),
            ("S", (0.625, 0.625, 0.625)),
            ("Cl", (0.75, 0.75, 0.75)),
            ("Li", (0.25, 0.25, 0.05)),
        ),
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=(
            ("p_4b", "4b", "P", ("P",), (0.5, 0.5, 0.5)),
            ("s1_4a", "4a", "S", ("S",), (0.0, 0.0, 0.0)),
            ("s2_16e", "16e", "S", ("S",), (0.625, 0.625, 0.625)),
            ("cl_4d", "4d", "Cl", ("Cl",), (0.75, 0.75, 0.75)),
            ("li_24g", "24g", "Li", ("Li",), (0.25, 0.25, 0.05)),
        ),
    ),
    "nitride": ScaffoldDefinition(
        key="nitride",
        formula="TiN",
        family="nitride",
        space_group="Fm-3m",
        space_group_number=225,
        crystal_system="cubic",
        lattice=("cubic", (4.24,)),
        asymmetric_unit=(
            ("Ti", (0.0, 0.0, 0.0)),
            ("N", (0.5, 0.5, 0.5)),
        ),
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=(
            ("ti_4a", "4a", "Ti", ("Ti",), (0.0, 0.0, 0.0)),
            ("n_4b", "4b", "N", ("N",), (0.5, 0.5, 0.5)),
        ),
    ),
}


def _variant_scaffold(
    *,
    key: str,
    base_key: str,
    formula: str,
    family: str | None = None,
    lattice: tuple[str, tuple[float, ...]] | None = None,
    asymmetric_unit: tuple[tuple[str, tuple[float, float, float]], ...],
    orbit_definitions: tuple[tuple[Any, ...], ...],
) -> ScaffoldDefinition:
    base = _SCAFFOLDS[base_key]
    return ScaffoldDefinition(
        key=key,
        formula=formula,
        family=family or base.family,
        space_group=base.space_group,
        space_group_number=base.space_group_number,
        crystal_system=base.crystal_system,
        lattice=lattice or base.lattice,
        asymmetric_unit=asymmetric_unit,
        source_note=_IDEALIZED_SOURCE_NOTE,
        orbit_definitions=orbit_definitions,
    )


_SCAFFOLDS.update(
    {
        "halide_perovskite_cspbcl3": _variant_scaffold(
            key="halide_perovskite_cspbcl3",
            base_key="halide_perovskite",
            formula="CsPbCl3",
            lattice=("cubic", (5.6,)),
            asymmetric_unit=(
                ("Cs", (0.0, 0.0, 0.0)),
                ("Pb", (0.5, 0.5, 0.5)),
                ("Cl", (0.5, 0.5, 0.0)),
                ("Cl", (0.5, 0.0, 0.5)),
                ("Cl", (0.0, 0.5, 0.5)),
            ),
            orbit_definitions=(
                ("cs_1a", "1a", "Cs", ("Cs",), (0.0, 0.0, 0.0)),
                ("pb_1b", "1b", "Pb", ("Pb",), (0.5, 0.5, 0.5)),
                ("cl_3c", "3c", "Cl", ("Cl",), (0.5, 0.5, 0.0)),
            ),
        ),
        "halide_perovskite_cssnbr3": _variant_scaffold(
            key="halide_perovskite_cssnbr3",
            base_key="halide_perovskite",
            formula="CsSnBr3",
            asymmetric_unit=(
                ("Cs", (0.0, 0.0, 0.0)),
                ("Sn", (0.5, 0.5, 0.5)),
                ("Br", (0.5, 0.5, 0.0)),
                ("Br", (0.5, 0.0, 0.5)),
                ("Br", (0.0, 0.5, 0.5)),
            ),
            orbit_definitions=(
                ("cs_1a", "1a", "Cs", ("Cs",), (0.0, 0.0, 0.0)),
                ("sn_1b", "1b", "Sn", ("Sn",), (0.5, 0.5, 0.5)),
                ("br_3c", "3c", "Br", ("Br",), (0.5, 0.5, 0.0)),
            ),
        ),
        "halide_perovskite_cssni3": _variant_scaffold(
            key="halide_perovskite_cssni3",
            base_key="halide_perovskite",
            formula="CsSnI3",
            lattice=("cubic", (6.2,)),
            asymmetric_unit=(
                ("Cs", (0.0, 0.0, 0.0)),
                ("Sn", (0.5, 0.5, 0.5)),
                ("I", (0.5, 0.5, 0.0)),
                ("I", (0.5, 0.0, 0.5)),
                ("I", (0.0, 0.5, 0.5)),
            ),
            orbit_definitions=(
                ("cs_1a", "1a", "Cs", ("Cs",), (0.0, 0.0, 0.0)),
                ("sn_1b", "1b", "Sn", ("Sn",), (0.5, 0.5, 0.5)),
                ("i_3c", "3c", "I", ("I",), (0.5, 0.5, 0.0)),
            ),
        ),
        "halide_perovskite_cspbi3": _variant_scaffold(
            key="halide_perovskite_cspbi3",
            base_key="halide_perovskite",
            formula="CsPbI3",
            lattice=("cubic", (6.3,)),
            asymmetric_unit=(
                ("Cs", (0.0, 0.0, 0.0)),
                ("Pb", (0.5, 0.5, 0.5)),
                ("I", (0.5, 0.5, 0.0)),
                ("I", (0.5, 0.0, 0.5)),
                ("I", (0.0, 0.5, 0.5)),
            ),
            orbit_definitions=(
                ("cs_1a", "1a", "Cs", ("Cs",), (0.0, 0.0, 0.0)),
                ("pb_1b", "1b", "Pb", ("Pb",), (0.5, 0.5, 0.5)),
                ("i_3c", "3c", "I", ("I",), (0.5, 0.5, 0.0)),
            ),
        ),
        "spinel_mgal2o4": _variant_scaffold(
            key="spinel_mgal2o4",
            base_key="spinel",
            formula="MgAl2O4",
            lattice=("cubic", (8.08,)),
            asymmetric_unit=(("Mg", (0.0, 0.0, 0.0)), ("Al", (0.625, 0.625, 0.625)), ("O", (0.386, 0.386, 0.386))),
            orbit_definitions=(
                ("mg_8a", "8a", "Mg", ("Mg",), (0.0, 0.0, 0.0)),
                ("al_16d", "16d", "Al", ("Al",), (0.625, 0.625, 0.625)),
                ("o_32e", "32e", "O", ("O",), (0.386, 0.386, 0.386)),
            ),
        ),
        "spinel_cofe2o4": _variant_scaffold(
            key="spinel_cofe2o4",
            base_key="spinel",
            formula="CoFe2O4",
            asymmetric_unit=(("Co", (0.0, 0.0, 0.0)), ("Fe", (0.625, 0.625, 0.625)), ("O", (0.386, 0.386, 0.386))),
            orbit_definitions=(
                ("co_8a", "8a", "Co", ("Co",), (0.0, 0.0, 0.0)),
                ("fe_16d", "16d", "Fe", ("Fe",), (0.625, 0.625, 0.625)),
                ("o_32e", "32e", "O", ("O",), (0.386, 0.386, 0.386)),
            ),
        ),
        "rocksalt_mgo": _variant_scaffold(
            key="rocksalt_mgo",
            base_key="rocksalt",
            formula="MgO",
            lattice=("cubic", (4.21,)),
            asymmetric_unit=(("Mg", (0.0, 0.0, 0.0)), ("O", (0.5, 0.5, 0.5))),
            orbit_definitions=(("mg_4a", "4a", "Mg", ("Mg",), (0.0, 0.0, 0.0)), ("o_4b", "4b", "O", ("O",), (0.5, 0.5, 0.5))),
        ),
        "fluorite_zro2": _variant_scaffold(
            key="fluorite_zro2",
            base_key="fluorite",
            formula="ZrO2",
            asymmetric_unit=(("Zr", (0.0, 0.0, 0.0)), ("O", (0.25, 0.25, 0.25))),
            orbit_definitions=(("zr_4a", "4a", "Zr", ("Zr",), (0.0, 0.0, 0.0)), ("o_8c", "8c", "O", ("O",), (0.25, 0.25, 0.25))),
        ),
        "fluorite_tho2": _variant_scaffold(
            key="fluorite_tho2",
            base_key="fluorite",
            formula="ThO2",
            lattice=("cubic", (5.6,)),
            asymmetric_unit=(("Th", (0.0, 0.0, 0.0)), ("O", (0.25, 0.25, 0.25))),
            orbit_definitions=(("th_4a", "4a", "Th", ("Th",), (0.0, 0.0, 0.0)), ("o_8c", "8c", "O", ("O",), (0.25, 0.25, 0.25))),
        ),
        "pyrite_cos2": _variant_scaffold(
            key="pyrite_cos2",
            base_key="pyrite",
            formula="CoS2",
            asymmetric_unit=(("Co", (0.0, 0.0, 0.0)), ("S", (0.385, 0.385, 0.385))),
            orbit_definitions=(("co_4a", "4a", "Co", ("Co",), (0.0, 0.0, 0.0)), ("s_8c", "8c", "S", ("S",), (0.385, 0.385, 0.385))),
        ),
        "pyrite_nis2": _variant_scaffold(
            key="pyrite_nis2",
            base_key="pyrite",
            formula="NiS2",
            asymmetric_unit=(("Ni", (0.0, 0.0, 0.0)), ("S", (0.385, 0.385, 0.385))),
            orbit_definitions=(("ni_4a", "4a", "Ni", ("Ni",), (0.0, 0.0, 0.0)), ("s_8c", "8c", "S", ("S",), (0.385, 0.385, 0.385))),
        ),
        "layered_oxide_nacoo2": _variant_scaffold(
            key="layered_oxide_nacoo2",
            base_key="layered_oxide",
            formula="NaCoO2",
            asymmetric_unit=(("Na", (0.0, 0.0, 0.0)), ("Co", (0.0, 0.0, 0.5)), ("O", (0.0, 0.0, 0.241))),
            orbit_definitions=(
                ("na_3a", "3a", "Na", ("Na",), (0.0, 0.0, 0.0)),
                ("co_3b", "3b", "Co", ("Co",), (0.0, 0.0, 0.5)),
                ("o_6c", "6c", "O", ("O",), (0.0, 0.0, 0.241)),
            ),
        ),
        "layered_oxide_linio2": _variant_scaffold(
            key="layered_oxide_linio2",
            base_key="layered_oxide",
            formula="LiNiO2",
            asymmetric_unit=(("Li", (0.0, 0.0, 0.0)), ("Ni", (0.0, 0.0, 0.5)), ("O", (0.0, 0.0, 0.241))),
            orbit_definitions=(
                ("li_3a", "3a", "Li", ("Li",), (0.0, 0.0, 0.0)),
                ("ni_3b", "3b", "Ni", ("Ni",), (0.0, 0.0, 0.5)),
                ("o_6c", "6c", "O", ("O",), (0.0, 0.0, 0.241)),
            ),
        ),
        "olivine_phosphate_nafe": _variant_scaffold(
            key="olivine_phosphate_nafe",
            base_key="olivine_phosphate",
            formula="NaFePO4",
            asymmetric_unit=(("Na", (0.0, 0.0, 0.0)), ("Fe", (0.282, 0.25, 0.974)), ("P", (0.094, 0.25, 0.418)), ("O", (0.097, 0.25, 0.742)), ("O", (0.454, 0.25, 0.207)), ("O", (0.166, 0.046, 0.284))),
            orbit_definitions=(
                ("na_4a", "4a", "Na", ("Na",), (0.0, 0.0, 0.0)),
                ("fe_4c", "4c", "Fe", ("Fe",), (0.282, 0.25, 0.974)),
                ("p_4c", "4c", "P", ("P",), (0.094, 0.25, 0.418)),
                ("o1_4c", "4c", "O", ("O",), (0.097, 0.25, 0.742)),
                ("o2_4c", "4c", "O", ("O",), (0.454, 0.25, 0.207)),
                ("o3_8d", "8d", "O", ("O",), (0.166, 0.046, 0.284)),
            ),
        ),
        "olivine_phosphate_limn": _variant_scaffold(
            key="olivine_phosphate_limn",
            base_key="olivine_phosphate",
            formula="LiMnPO4",
            asymmetric_unit=(("Li", (0.0, 0.0, 0.0)), ("Mn", (0.282, 0.25, 0.974)), ("P", (0.094, 0.25, 0.418)), ("O", (0.097, 0.25, 0.742)), ("O", (0.454, 0.25, 0.207)), ("O", (0.166, 0.046, 0.284))),
            orbit_definitions=(
                ("li_4a", "4a", "Li", ("Li",), (0.0, 0.0, 0.0)),
                ("mn_4c", "4c", "Mn", ("Mn",), (0.282, 0.25, 0.974)),
                ("p_4c", "4c", "P", ("P",), (0.094, 0.25, 0.418)),
                ("o1_4c", "4c", "O", ("O",), (0.097, 0.25, 0.742)),
                ("o2_4c", "4c", "O", ("O",), (0.454, 0.25, 0.207)),
                ("o3_8d", "8d", "O", ("O",), (0.166, 0.046, 0.284)),
            ),
        ),
        "argyrodite_br": _variant_scaffold(
            key="argyrodite_br",
            base_key="argyrodite",
            formula="Li6PS5Br",
            asymmetric_unit=(("P", (0.5, 0.5, 0.5)), ("S", (0.0, 0.0, 0.0)), ("S", (0.625, 0.625, 0.625)), ("Br", (0.75, 0.75, 0.75)), ("Li", (0.25, 0.25, 0.05))),
            orbit_definitions=(
                ("p_4b", "4b", "P", ("P",), (0.5, 0.5, 0.5)),
                ("s1_4a", "4a", "S", ("S",), (0.0, 0.0, 0.0)),
                ("s2_16e", "16e", "S", ("S",), (0.625, 0.625, 0.625)),
                ("br_4d", "4d", "Br", ("Br",), (0.75, 0.75, 0.75)),
                ("li_24g", "24g", "Li", ("Li",), (0.25, 0.25, 0.05)),
            ),
        ),
        "argyrodite_i": _variant_scaffold(
            key="argyrodite_i",
            base_key="argyrodite",
            formula="Li6PS5I",
            asymmetric_unit=(("P", (0.5, 0.5, 0.5)), ("S", (0.0, 0.0, 0.0)), ("S", (0.625, 0.625, 0.625)), ("I", (0.75, 0.75, 0.75)), ("Li", (0.25, 0.25, 0.05))),
            orbit_definitions=(
                ("p_4b", "4b", "P", ("P",), (0.5, 0.5, 0.5)),
                ("s1_4a", "4a", "S", ("S",), (0.0, 0.0, 0.0)),
                ("s2_16e", "16e", "S", ("S",), (0.625, 0.625, 0.625)),
                ("i_4d", "4d", "I", ("I",), (0.75, 0.75, 0.75)),
                ("li_24g", "24g", "Li", ("Li",), (0.25, 0.25, 0.05)),
            ),
        ),
        "nitride_vn": _variant_scaffold(
            key="nitride_vn",
            base_key="nitride",
            formula="VN",
            family="rocksalt-like nitride",
            asymmetric_unit=(("V", (0.0, 0.0, 0.0)), ("N", (0.5, 0.5, 0.5))),
            orbit_definitions=(("v_4a", "4a", "V", ("V",), (0.0, 0.0, 0.0)), ("n_4b", "4b", "N", ("N",), (0.5, 0.5, 0.5))),
        ),
        "nitride_zrn": _variant_scaffold(
            key="nitride_zrn",
            base_key="nitride",
            formula="ZrN",
            family="rocksalt-like nitride",
            asymmetric_unit=(("Zr", (0.0, 0.0, 0.0)), ("N", (0.5, 0.5, 0.5))),
            orbit_definitions=(("zr_4a", "4a", "Zr", ("Zr",), (0.0, 0.0, 0.0)), ("n_4b", "4b", "N", ("N",), (0.5, 0.5, 0.5))),
        ),
    }
)


def ideal_prototype_structure(prototype: str, formula: str | None = None):
    """Return an ideal conventional-cell scaffold for supported prototypes."""
    definition = _definition_for(prototype=prototype, formula=formula, family=prototype)
    if definition is None:
        raise ValueError(f"Unsupported prototype scaffold: {prototype!r}")
    return _structure_from_definition(definition)


def prototype_scaffold_from_request(request: dict[str, Any]) -> tuple[Any | None, dict[str, Any]]:
    """Resolve a supported final-output scaffold from a QLIP request."""
    problem = request.get("problem") if isinstance(request, dict) else {}
    chemistry = problem.get("chemistry") if isinstance(problem, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites = design_space.get("sites") if isinstance(design_space, dict) else {}
    scaffold = sites.get("prototype_scaffold") if isinstance(sites, dict) else {}
    formula = str(chemistry.get("formula") or "").strip() if isinstance(chemistry, dict) else ""
    family = str(scaffold.get("family") or "").strip().lower() if isinstance(scaffold, dict) else ""
    mode = str(sites.get("mode") or "") if isinstance(sites, dict) else ""
    site_mode = str(sites.get("site_mode") or "") if isinstance(sites, dict) else ""
    variable_orbit_active = _is_variable_orbit_mode(mode=mode, site_mode=site_mode)
    variable_spp_active = mode == _VARIABLE_ORBIT_SPP_MODE
    fixed_orbit_active = mode == "prototype_orbit_qlip" or site_mode == "prototype_orbit"
    orbit_active = fixed_orbit_active or variable_orbit_active
    active = isinstance(sites, dict) and (mode == "prototype_scaffold" or orbit_active)
    active_symmetry_mode = (
        _VARIABLE_ORBIT_SPP_MODE
        if variable_spp_active
        else "prototype_orbit_variable_qlip"
        if variable_orbit_active
        else "prototype_orbit_qlip"
        if fixed_orbit_active
        else "prototype_scaffold"
        if active
        else "none"
    )
    final_cif_source = (
        _VARIABLE_ORBIT_SPP_MODE
        if variable_spp_active
        else "prototype_orbit_variable_qlip"
        if variable_orbit_active
        else "prototype_orbit_qlip"
        if fixed_orbit_active
        else "prototype_scaffold"
    )
    trace: dict[str, Any] = {
        "active_symmetry_mode": active_symmetry_mode,
        "orbit_level_selection": bool(orbit_active),
        "variable_orbit_selection": bool(variable_orbit_active),
        "selected_orbits": [],
        "selected_sites": [],
        "selected_species_by_orbit": {},
        "selected_candidate_id": None,
        "objective_value": None,
        "symmetry_closed": None,
        "spp_scoring_status": "unavailable" if variable_orbit_active else None,
        "spp_source": None,
        "spp_source_type": None,
        "spp_pot_dir": None,
        "spp_preflight_path": sites.get("spp_preflight_path") if isinstance(sites, dict) else None,
        "loaded_pair_count": sites.get("loaded_pair_count") if isinstance(sites, dict) else None,
        "missing_pairs": sites.get("missing_pairs") if isinstance(sites, dict) else None,
        "spp_fallback_reason": None,
        "selected_pair_score_breakdown": None,
        "orbit_assignment_solver": _VARIABLE_ORBIT_SELECTOR_BACKEND if variable_orbit_active else None,
        "scaffold_used_for_final_cif": False,
        "final_cif_source": "generic_fallback",
        "scaffold_family": family or None,
        "scaffold_space_group": None,
        "scaffold_space_group_number": None,
        "scaffold_crystal_system": None,
        "scaffold_site_count": None,
        "scaffold_formula": formula or None,
        "scaffold_lattice_parameters": None,
        "scaffold_fractional_coordinates": None,
        "scaffold_orbits": None,
        "orbit_count": None,
        "scaffold_source_note": None,
        "fallback_reason": None,
    }
    if not active:
        trace["fallback_reason"] = "unavailable_scaffold"
        return None, trace
    if variable_orbit_active:
        solution = prototype_orbit_solution_from_request(request)
        candidates = prototype_orbit_candidates_payload_from_request(request)
        if solution is None:
            trace["fallback_reason"] = _variable_orbit_fallback_reason(request)
            if candidates is not None:
                trace["orbit_count"] = candidates.get("orbit_count")
                trace["scaffold_orbits"] = candidates.get("orbits")
            return None, trace
        definition = _definition_for(family=solution.family, formula=solution.formula)
        if definition is None:
            trace["fallback_reason"] = "unsupported_variable_orbit_case"
            return None, trace
        structure = _structure_from_solution(solution, definition)
        trace.update(
            {
                "scaffold_used_for_final_cif": True,
                "final_cif_source": final_cif_source,
                "scaffold_family": solution.family,
                "scaffold_space_group": solution.target_space_group,
                "scaffold_space_group_number": solution.target_space_group_number,
                "scaffold_crystal_system": solution.crystal_system,
                "scaffold_site_count": len(structure),
                "scaffold_formula": solution.formula,
                "scaffold_lattice_parameters": _lattice_parameters(structure),
                "scaffold_fractional_coordinates": _fractional_coordinates(structure),
                "scaffold_orbits": _orbits_payload(solution),
                "orbit_count": len(solution.orbits),
                "selected_orbits": [orbit.orbit_id for orbit in solution.orbits],
                "selected_sites": [site.site_id for site in solution.sites],
                "selected_species_by_orbit": solution.selected_species_by_orbit or {},
                "selected_candidate_id": solution.selected_candidate_id,
                "objective_value": solution.objective_value,
                "symmetry_closed": solution.symmetry_closed,
                "spp_scoring_status": solution.spp_scoring_status,
                "spp_source": solution.spp_source,
                "spp_source_type": solution.spp_source_type,
                "spp_pot_dir": solution.spp_pot_dir,
                "selected_pair_score_breakdown": solution.selected_pair_score_breakdown or [],
                "spp_fallback_reason": solution.spp_fallback_reason,
                "orbit_assignment_solver": _VARIABLE_ORBIT_SELECTOR_BACKEND,
                "scaffold_source_note": _IDEALIZED_SOURCE_NOTE,
                "fallback_reason": None,
            }
        )
        return structure, trace
    definition = _definition_for(family=family, formula=formula)
    if definition is None:
        trace["fallback_reason"] = "unsupported_family"
        return None, trace
    try:
        structure = _structure_from_definition(definition)
    except Exception:  # noqa: BLE001
        trace["fallback_reason"] = "unavailable_scaffold"
        return None, trace
    solution = _solution_from_definition(definition, structure)
    if orbit_active and not _requested_site_selection_is_orbit_closed(sites, solution):
        trace["fallback_reason"] = "non_closed_orbit_site_selection_rejected"
        trace["symmetry_closed"] = False
        trace["orbit_count"] = len(solution.orbits)
        trace["scaffold_orbits"] = _orbits_payload(solution)
        return None, trace
    trace.update(
        {
            "scaffold_used_for_final_cif": True,
            "final_cif_source": final_cif_source,
            "scaffold_family": definition.family,
            "scaffold_space_group": definition.space_group,
            "scaffold_space_group_number": definition.space_group_number,
            "scaffold_crystal_system": definition.crystal_system,
            "scaffold_site_count": len(structure),
            "scaffold_formula": definition.formula,
            "scaffold_lattice_parameters": _lattice_parameters(structure),
            "scaffold_fractional_coordinates": _fractional_coordinates(structure),
            "scaffold_orbits": _orbits_payload(solution),
            "orbit_count": len(solution.orbits),
            "selected_orbits": [orbit.orbit_id for orbit in solution.orbits] if orbit_active else [],
            "selected_sites": [site.site_id for site in solution.sites] if orbit_active else [],
            "selected_species_by_orbit": solution.selected_species_by_orbit or {} if orbit_active else {},
            "symmetry_closed": solution.symmetry_closed if orbit_active else None,
            "scaffold_source_note": definition.source_note,
            "fallback_reason": None,
        }
    )
    return structure, trace


def prototype_orbit_solution_from_request(request: dict[str, Any]) -> PrototypeScaffoldSolution | None:
    problem = request.get("problem") if isinstance(request, dict) else {}
    chemistry = problem.get("chemistry") if isinstance(problem, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites = design_space.get("sites") if isinstance(design_space, dict) else {}
    mode = str(sites.get("mode") or "") if isinstance(sites, dict) else ""
    site_mode = str(sites.get("site_mode") or "") if isinstance(sites, dict) else ""
    if _is_variable_orbit_mode(mode=mode, site_mode=site_mode):
        return _variable_orbit_solution_from_request(request)
    scaffold = sites.get("prototype_scaffold") if isinstance(sites, dict) else {}
    formula = str(chemistry.get("formula") or "").strip() if isinstance(chemistry, dict) else ""
    family = str(scaffold.get("family") or "").strip().lower() if isinstance(scaffold, dict) else ""
    definition = _definition_for(family=family, formula=formula)
    if definition is None:
        return None
    structure = _structure_from_definition(definition)
    solution = _solution_from_definition(definition, structure)
    if not _requested_site_selection_is_orbit_closed(sites, solution):
        return None
    return solution


def prototype_orbit_candidates_payload_from_request(request: dict[str, Any]) -> dict[str, Any] | None:
    payload = _variable_orbit_payload(request)
    if payload is None:
        return None
    solution, candidates, target_counts, scoring = payload
    return {
        "schema_version": "prototype_scaffold_orbit_candidates.v1",
        "mode": _variable_orbit_mode_from_request(request),
        "formula": solution.formula,
        "family": solution.family,
        "orbit_count": len(solution.orbits),
        "site_count": len(solution.sites),
        "target_counts": target_counts,
        "orbits": _orbits_payload(solution),
        "candidates": candidates,
        "spp_scoring_status": scoring["status"],
        "spp_source": scoring["source"],
        "spp_source_type": scoring["source_type"],
        "spp_pot_dir": scoring["pot_dir"],
        "required_pairs": _required_pairs_from_request(request),
        "loaded_pair_count": scoring["loaded_pair_count"],
        "loaded_pairs": scoring["loaded_pairs"],
        "missing_pairs": scoring["missing_pairs"],
        "fallback_reason": scoring["fallback_reason"],
        "orbit_assignment_solver": _VARIABLE_ORBIT_SELECTOR_BACKEND,
        "selection_note": "first constrained perovskite A-site orbit enumeration smoke; not a general CSP solver",
    }


def _variable_orbit_solution_from_request(request: dict[str, Any]) -> PrototypeScaffoldSolution | None:
    payload = _variable_orbit_payload(request)
    if payload is None:
        return None
    solution, candidates, _, scoring = payload
    selectable = [candidate for candidate in candidates if candidate["formula_satisfied"] and candidate["compatibility_valid"] and candidate["symmetry_closed"]]
    scored = [candidate for candidate in selectable if isinstance(candidate.get("objective_value"), (int, float))]
    selected = min(scored, key=lambda candidate: float(candidate["objective_value"])) if scored else (selectable[0] if selectable else None)
    if selected is None:
        return None
    selected_species_by_orbit = dict(selected["selected_species_by_orbit"])
    sites = tuple(
        ScaffoldSite(
            site_id=site.site_id,
            orbit_id=site.orbit_id,
            species=selected_species_by_orbit[site.orbit_id],
            frac_coords=site.frac_coords,
        )
        for site in solution.sites
    )
    definition = _definition_for(family=solution.family, formula=solution.formula)
    if definition is None:
        return None
    structure = _structure_from_sites(definition, sites)
    closure = symmetry_closure_report(structure, space_group_number=solution.target_space_group_number)
    return PrototypeScaffoldSolution(
        formula=solution.formula,
        family=solution.family,
        target_space_group=solution.target_space_group,
        target_space_group_number=solution.target_space_group_number,
        crystal_system=solution.crystal_system,
        orbits=solution.orbits,
        sites=sites,
        symmetry_closed=closure.closed,
        variable_orbit_selection=True,
        selected_species_by_orbit=selected_species_by_orbit,
        selected_candidate_id=str(selected["candidate_id"]),
        objective_value=float(selected["objective_value"]) if isinstance(selected.get("objective_value"), (int, float)) else None,
        spp_scoring_status=str(selected.get("spp_scoring_status") or scoring["status"]),
        spp_source=scoring["source"],
        spp_source_type=scoring["source_type"],
        spp_pot_dir=scoring["pot_dir"],
        spp_fallback_reason=scoring["fallback_reason"],
        selected_pair_score_breakdown=list(selected.get("pair_score_breakdown") or []),
        solver_backend=_VARIABLE_ORBIT_SELECTOR_BACKEND,
        formula_satisfied=bool(selected["formula_satisfied"]),
    )


def _variable_orbit_payload(
    request: dict[str, Any],
) -> tuple[PrototypeScaffoldSolution, list[dict[str, Any]], dict[str, int], dict[str, Any]] | None:
    problem = request.get("problem") if isinstance(request, dict) else {}
    chemistry = problem.get("chemistry") if isinstance(problem, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites_payload = design_space.get("sites") if isinstance(design_space, dict) else {}
    scaffold = sites_payload.get("prototype_scaffold") if isinstance(sites_payload, dict) else {}
    formula = str(chemistry.get("formula") or "").replace(" ", "") if isinstance(chemistry, dict) else ""
    family = str(scaffold.get("family") or "").strip().lower() if isinstance(scaffold, dict) else ""
    if formula not in _VARIABLE_ORBIT_SUPPORTED_FORMULAS:
        return None
    definition = _definition_for(family=family, formula=formula)
    if definition is None or not _variable_orbit_family_supported(definition):
        return None
    base_structure = _structure_from_definition(definition)
    base_solution = _solution_from_definition(definition, base_structure)
    variable_orbits = tuple(_variable_orbit_for_definition(definition, orbit) for orbit in base_solution.orbits)
    solution = PrototypeScaffoldSolution(
        formula=formula,
        family=definition.family,
        target_space_group=definition.space_group,
        target_space_group_number=definition.space_group_number,
        crystal_system=definition.crystal_system,
        orbits=variable_orbits,
        sites=base_solution.sites,
        symmetry_closed=base_solution.symmetry_closed,
        variable_orbit_selection=True,
        selected_species_by_orbit=None,
    )
    if not _requested_site_selection_is_complete_or_empty(sites_payload, solution):
        return None
    target_count_options = _formula_count_options(request, formula, site_count=len(base_solution.sites))
    target_counts = target_count_options[0]
    spp_curves, scoring = _spp_scoring_context(request)
    candidates: list[dict[str, Any]] = []
    for candidate_index, assignment in enumerate(product(*(orbit.allowed_species for orbit in variable_orbits)), start=1):
        selected_species_by_orbit = {
            orbit.orbit_id: species
            for orbit, species in zip(variable_orbits, assignment)
        }
        counts: dict[str, int] = {}
        for orbit, species in zip(variable_orbits, assignment):
            counts[species] = counts.get(species, 0) + orbit.multiplicity
        formula_satisfied = counts in target_count_options
        candidate_sites = tuple(
            ScaffoldSite(
                site_id=site.site_id,
                orbit_id=site.orbit_id,
                species=selected_species_by_orbit[site.orbit_id],
                frac_coords=site.frac_coords,
            )
            for site in solution.sites
        )
        candidate_structure = _structure_from_sites(definition, candidate_sites)
        closure = symmetry_closure_report(candidate_structure, space_group_number=definition.space_group_number)
        compatibility_valid = _assignment_compatible(selected_species_by_orbit, variable_orbits)
        spp_score = None
        objective_value = None
        rejection_reason = None
        candidate_status = scoring["status"]
        pair_score_breakdown: list[dict[str, Any]] = []
        missing_pair_count = len(scoring["missing_pairs"])
        if not formula_satisfied:
            rejection_reason = "formula_counts_not_satisfied"
        elif not compatibility_valid:
            rejection_reason = "species_orbit_incompatible"
        elif not closure.closed:
            rejection_reason = "symmetry_not_closed"
        elif spp_curves:
            score_result = _score_structure_with_spp_curves(candidate_structure, spp_curves)
            if score_result["ok"]:
                spp_score = float(score_result["score"])
                objective_value = spp_score
                pair_score_breakdown = list(score_result["pair_score_breakdown"])
                missing_pair_count = 0
            else:
                rejection_reason = str(score_result["reason"])
                pair_score_breakdown = list(score_result["pair_score_breakdown"])
                missing_pair_count = int(score_result["missing_pair_count"])
                candidate_status = "unavailable"
        candidates.append(
            {
                "candidate_id": f"{definition.key}_orbit_assignment_{candidate_index}",
                "selected_species_by_orbit": selected_species_by_orbit,
                "counts": counts,
                "formula_satisfied": formula_satisfied,
                "compatibility_valid": compatibility_valid,
                "symmetry_closed": closure.closed,
                "spp_score": spp_score,
                "objective_value": objective_value,
                "pair_score_breakdown": pair_score_breakdown,
                "missing_pair_count": missing_pair_count,
                "spp_scoring_status": candidate_status,
                "rejection_reason": rejection_reason,
            }
        )
    if not any(candidate["formula_satisfied"] for candidate in candidates):
        return None
    return solution, candidates, target_counts, scoring


def _variable_orbit_fallback_reason(request: dict[str, Any]) -> str:
    problem = request.get("problem") if isinstance(request, dict) else {}
    chemistry = problem.get("chemistry") if isinstance(problem, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites_payload = design_space.get("sites") if isinstance(design_space, dict) else {}
    scaffold = sites_payload.get("prototype_scaffold") if isinstance(sites_payload, dict) else {}
    formula = str(chemistry.get("formula") or "").replace(" ", "") if isinstance(chemistry, dict) else ""
    family = str(scaffold.get("family") or "").strip().lower() if isinstance(scaffold, dict) else ""
    definition = _definition_for(family=family, formula=formula)
    if formula not in _VARIABLE_ORBIT_SUPPORTED_FORMULAS or definition is None or not _variable_orbit_family_supported(definition):
        return "unsupported_variable_orbit_case"
    base_solution = _solution_from_definition(definition, _structure_from_definition(definition))
    if not _requested_site_selection_is_complete_or_empty(sites_payload, base_solution):
        return "non_closed_orbit_site_selection_rejected"
    return "no_formula_satisfying_orbit_assignment"


def _variable_orbit_family_supported(definition: ScaffoldDefinition) -> bool:
    return definition.family.strip().lower() in {"perovskite", "halide perovskite", "rocksalt", "nitride", "fluorite"}


def _variable_orbit_for_definition(definition: ScaffoldDefinition, orbit: ScaffoldOrbit) -> ScaffoldOrbit:
    family = definition.family.strip().lower()
    allowed_species = orbit.allowed_species
    if family == "perovskite" and orbit.wyckoff_label == "1a":
        allowed_species = _VARIABLE_PEROVSKITE_A_SITE_SPECIES
    elif family == "halide perovskite":
        if orbit.wyckoff_label == "1a":
            allowed_species = _VARIABLE_HALIDE_PEROVSKITE_A_SITE_SPECIES
        elif orbit.wyckoff_label == "1b":
            allowed_species = _VARIABLE_HALIDE_PEROVSKITE_B_SITE_SPECIES
        elif orbit.wyckoff_label == "3c":
            allowed_species = _VARIABLE_HALIDE_PEROVSKITE_X_SITE_SPECIES
    elif family in {"rocksalt", "nitride"}:
        if orbit.wyckoff_label == "4a":
            allowed_species = _VARIABLE_ROCKSALT_CATION_SPECIES
        elif orbit.wyckoff_label == "4b":
            allowed_species = _VARIABLE_ROCKSALT_ANION_SPECIES
    elif family == "fluorite" and orbit.wyckoff_label == "4a":
        allowed_species = _VARIABLE_FLUORITE_CATION_SPECIES
    return ScaffoldOrbit(
        orbit_id=orbit.orbit_id,
        wyckoff_label=orbit.wyckoff_label,
        allowed_species=allowed_species,
        preferred_species=orbit.preferred_species,
        multiplicity=orbit.multiplicity,
        fractional_coordinates=orbit.fractional_coordinates,
        target_space_group=orbit.target_space_group,
        target_space_group_number=orbit.target_space_group_number,
        crystal_system=orbit.crystal_system,
    )


def _is_variable_orbit_mode(*, mode: str, site_mode: str) -> bool:
    return mode in {"prototype_orbit_variable_qlip", _VARIABLE_ORBIT_SPP_MODE} or site_mode == "prototype_orbit_variable"


def _variable_orbit_mode_from_request(request: dict[str, Any]) -> str:
    problem = request.get("problem") if isinstance(request, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites = design_space.get("sites") if isinstance(design_space, dict) else {}
    mode = str(sites.get("mode") or "") if isinstance(sites, dict) else ""
    return mode if mode in {"prototype_orbit_variable_qlip", _VARIABLE_ORBIT_SPP_MODE} else "prototype_orbit_variable_qlip"


def _assignment_compatible(selected_species_by_orbit: dict[str, str], orbits: tuple[ScaffoldOrbit, ...]) -> bool:
    return all(selected_species_by_orbit.get(orbit.orbit_id) in orbit.allowed_species for orbit in orbits)


def _spp_scoring_context(request: dict[str, Any]) -> tuple[dict[str, list[tuple[float, float]]], dict[str, Any]]:
    source = _spp_source_from_request(request)
    source_type = _spp_source_type_from_request(request)
    pot_root = _spp_pot_root_from_request(request)
    curves = _load_spp_curves(pot_root) if pot_root is not None else {}
    loaded_pairs = sorted(curves)
    missing_pairs = _missing_pairs_from_request(request)
    pot_dir = str(pot_root) if pot_root is not None else None
    if curves:
        status = "test_fixture" if source == "test_fixture" else "scored"
        return curves, {
            "status": status,
            "source": source or str(pot_root),
            "source_type": source_type or ("test_fixture" if source == "test_fixture" else "pot_dir"),
            "pot_dir": pot_dir,
            "loaded_pairs": loaded_pairs,
            "loaded_pair_count": len(loaded_pairs),
            "missing_pairs": missing_pairs,
            "fallback_reason": None,
        }
    return {}, {
        "status": "unavailable",
        "source": source or (str(pot_root) if pot_root is not None else None),
        "source_type": source_type or "unavailable",
        "pot_dir": pot_dir,
        "loaded_pairs": loaded_pairs,
        "loaded_pair_count": len(loaded_pairs),
        "missing_pairs": missing_pairs,
        "fallback_reason": "spp_curves_unavailable",
    }


def _spp_source_type_from_request(request: dict[str, Any]) -> str | None:
    context = request.get("context") if isinstance(request, dict) else {}
    if isinstance(context, dict) and isinstance(context.get("spp_source_type"), str):
        return str(context["spp_source_type"])
    problem = request.get("problem") if isinstance(request, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites = design_space.get("sites") if isinstance(design_space, dict) else {}
    if isinstance(sites, dict) and isinstance(sites.get("spp_source_type"), str):
        return str(sites["spp_source_type"])
    return None


def _spp_source_from_request(request: dict[str, Any]) -> str | None:
    context = request.get("context") if isinstance(request, dict) else {}
    if isinstance(context, dict) and isinstance(context.get("spp_source"), str):
        return str(context["spp_source"])
    problem = request.get("problem") if isinstance(request, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites = design_space.get("sites") if isinstance(design_space, dict) else {}
    if isinstance(sites, dict) and isinstance(sites.get("spp_source"), str):
        return str(sites["spp_source"])
    return None


def _missing_pairs_from_request(request: dict[str, Any]) -> list[str]:
    problem = request.get("problem") if isinstance(request, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites = design_space.get("sites") if isinstance(design_space, dict) else {}
    if isinstance(sites, dict) and isinstance(sites.get("missing_pairs"), list):
        return sorted(str(pair) for pair in sites["missing_pairs"])
    return []


def _required_pairs_from_request(request: dict[str, Any]) -> list[str]:
    problem = request.get("problem") if isinstance(request, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites = design_space.get("sites") if isinstance(design_space, dict) else {}
    if isinstance(sites, dict) and isinstance(sites.get("required_pairs"), list):
        return sorted(str(pair) for pair in sites["required_pairs"])
    return []


def _spp_pot_root_from_request(request: dict[str, Any]) -> Path | None:
    context = request.get("context") if isinstance(request, dict) else {}
    candidates: list[str] = []
    if isinstance(context, dict):
        for key in ("pot_root", "spp_pot_root"):
            if isinstance(context.get(key), str) and str(context[key]).strip():
                candidates.append(str(context[key]))
    guidance = request.get("guidance") if isinstance(request, dict) else []
    if isinstance(guidance, list):
        for item in guidance:
            params = item.get("params") if isinstance(item, dict) else {}
            if not isinstance(params, dict):
                continue
            for key in ("pot_root", "regularisation_spp_dir", "regularization_spp_dir"):
                if isinstance(params.get(key), str) and str(params[key]).strip():
                    candidates.append(str(params[key]))
    for raw_path in candidates:
        path = Path(raw_path)
        if path.is_dir() and list(path.rglob("*.POT")):
            return path
    return None


def _load_spp_curves(pot_root: Path | None) -> dict[str, list[tuple[float, float]]]:
    if pot_root is None or not pot_root.is_dir():
        return {}
    curves: dict[str, list[tuple[float, float]]] = {}
    for pot_file in pot_root.rglob("*.POT"):
        pair = _canonical_pair_key(pot_file.stem)
        points: list[tuple[float, float]] = []
        for line in pot_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                distance = float(parts[0])
                value = float(parts[1])
            except ValueError:
                continue
            points.append((distance, value))
        if points:
            curves[pair] = sorted(points)
    return curves


def _score_structure_with_spp_curves(structure: Any, curves: dict[str, list[tuple[float, float]]]) -> dict[str, Any]:
    score = 0.0
    missing_pairs: set[str] = set()
    pair_score_breakdown: list[dict[str, Any]] = []
    for left_index, left_site in enumerate(structure):
        for right_index in range(left_index + 1, len(structure)):
            right_site = structure[right_index]
            pair = _canonical_pair_key(f"{left_site.specie}-{right_site.specie}")
            curve = curves.get(pair)
            if curve is None:
                missing_pairs.add(pair)
                continue
            distance = float(structure.get_distance(left_index, right_index))
            pair_score = _interpolate_curve(curve, distance)
            score += pair_score
            pair_score_breakdown.append(
                {
                    "site_indices": [left_index, right_index],
                    "pair": pair,
                    "distance": distance,
                    "score": pair_score,
                }
            )
    if missing_pairs:
        return {
            "ok": False,
            "reason": "missing_spp_pair_curves:" + ",".join(sorted(missing_pairs)),
            "missing_pairs": sorted(missing_pairs),
            "missing_pair_count": len(missing_pairs),
            "pair_score_breakdown": pair_score_breakdown,
        }
    return {
        "ok": True,
        "score": score,
        "missing_pairs": [],
        "missing_pair_count": 0,
        "pair_score_breakdown": pair_score_breakdown,
    }


def _interpolate_curve(curve: list[tuple[float, float]], distance: float) -> float:
    if len(curve) == 1:
        return float(curve[0][1])
    if distance <= curve[0][0]:
        return float(curve[0][1])
    for (left_distance, left_value), (right_distance, right_value) in zip(curve, curve[1:]):
        if distance <= right_distance:
            span = right_distance - left_distance
            if abs(span) < 1e-12:
                return float(right_value)
            fraction = (distance - left_distance) / span
            return float(left_value + fraction * (right_value - left_value))
    return float(curve[-1][1])


def _canonical_pair_key(pair: str) -> str:
    if "-" not in pair:
        return _canonical_element_symbol(pair)
    left, right = pair.split("-", 1)
    return "-".join(sorted((_canonical_element_symbol(left), _canonical_element_symbol(right)), key=str.lower))


def _canonical_element_symbol(symbol: str) -> str:
    stripped = str(symbol).strip()
    if not stripped:
        return stripped
    return stripped[:1].upper() + stripped[1:].lower()


def write_prototype_scaffold_cif(path: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    from pymatgen.io.cif import CifWriter

    structure, trace = prototype_scaffold_from_request(request)
    if structure is None:
        return trace
    CifWriter(structure).write_file(str(Path(path)))
    return trace


def scaffold_matches_final_cif(
    path: str | Path,
    request: dict[str, Any],
    *,
    tolerance: float = 1e-3,
) -> dict[str, Any]:
    structure, trace = prototype_scaffold_from_request(request)
    if structure is None:
        return trace
    try:
        from pymatgen.core import Structure

        final_structure = Structure.from_file(str(path))
    except Exception as exc:  # noqa: BLE001
        return trace | {
            "scaffold_used_for_final_cif": False,
            "final_cif_source": "generic_fallback",
            "fallback_reason": f"final_cif_unreadable:{type(exc).__name__}",
        }
    if len(final_structure) != len(structure):
        return trace | {
            "scaffold_used_for_final_cif": False,
            "final_cif_source": "generic_fallback",
            "fallback_reason": "final_cif_site_count_differs_from_scaffold",
            "scaffold_site_count": len(structure),
            "final_cif_site_count": len(final_structure),
        }
    try:
        from pymatgen.core.structure_matcher import StructureMatcher

        matcher = StructureMatcher(
            ltol=tolerance,
            stol=tolerance,
            angle_tol=0.1,
            primitive_cell=False,
            scale=False,
            attempt_supercell=False,
        )
        if matcher.fit(structure, final_structure):
            return trace | {"scaffold_used_for_final_cif": True, "final_cif_source": trace["final_cif_source"], "fallback_reason": None}
    except Exception:  # noqa: BLE001
        pass
    observed_by_species: dict[str, list[tuple[float, float, float]]] = {}
    for site in final_structure:
        observed_by_species.setdefault(str(site.specie), []).append(tuple(float(value) % 1.0 for value in site.frac_coords))
    for site in structure:
        expected_species = str(site.specie)
        expected_coords = tuple(float(value) % 1.0 for value in site.frac_coords)
        species_coords = observed_by_species.get(expected_species)
        if not species_coords:
            return trace | {
                "scaffold_used_for_final_cif": False,
                "final_cif_source": "generic_fallback",
                "fallback_reason": "final_cif_species_differs_from_scaffold",
            }
        match_index = _periodic_match_index(expected_coords, species_coords, tolerance=tolerance)
        if match_index is None:
            return trace | {
                "scaffold_used_for_final_cif": False,
                "final_cif_source": "generic_fallback",
                "fallback_reason": "final_cif_coordinates_differ_from_scaffold",
            }
        species_coords.pop(match_index)
    return trace | {"scaffold_used_for_final_cif": True, "final_cif_source": trace["final_cif_source"], "fallback_reason": None}


def _solution_from_definition(definition: ScaffoldDefinition, structure: Any) -> PrototypeScaffoldSolution:
    sites_by_species: dict[str, list[tuple[float, float, float]]] = {}
    for site in structure:
        species = str(site.specie)
        sites_by_species.setdefault(species, []).append(_rounded_frac_tuple(site.frac_coords))

    orbits: list[ScaffoldOrbit] = []
    sites: list[ScaffoldSite] = []
    orbit_definitions = definition.orbit_definitions or tuple(
        (f"{species.lower()}_{index + 1}", None, species, (species,))
        for index, species in enumerate(dict.fromkeys(str(site.specie) for site in structure))
    )
    for raw_orbit in orbit_definitions:
        orbit_id, wyckoff_label, preferred_species, allowed_species, representative = _parse_orbit_definition(raw_orbit)
        coords = tuple(
            sorted(
                _coords_for_orbit(
                    definition,
                    sites_by_species.get(preferred_species, []),
                    representative=representative,
                )
            )
        )
        orbit = ScaffoldOrbit(
            orbit_id=orbit_id,
            wyckoff_label=wyckoff_label,
            allowed_species=tuple(allowed_species),
            preferred_species=preferred_species,
            multiplicity=len(coords),
            fractional_coordinates=coords,
            target_space_group=definition.space_group,
            target_space_group_number=definition.space_group_number,
            crystal_system=definition.crystal_system,
        )
        orbits.append(orbit)
        for index, coord in enumerate(coords, start=1):
            sites.append(
                ScaffoldSite(
                    site_id=f"{orbit_id}:{index}",
                    orbit_id=orbit_id,
                    species=preferred_species,
                    frac_coords=coord,
                )
            )
    closure = symmetry_closure_report(structure, space_group_number=definition.space_group_number)
    return PrototypeScaffoldSolution(
        formula=definition.formula,
        family=definition.family,
        target_space_group=definition.space_group,
        target_space_group_number=definition.space_group_number,
        crystal_system=definition.crystal_system,
        orbits=tuple(orbits),
        sites=tuple(sites),
        symmetry_closed=closure.closed,
    )


def _structure_from_solution(solution: PrototypeScaffoldSolution, definition: ScaffoldDefinition):
    return _structure_from_sites(definition, solution.sites)


def _structure_from_sites(definition: ScaffoldDefinition, sites: tuple[ScaffoldSite, ...]):
    from pymatgen.core import Lattice, Structure

    lattice_kind, parameters = definition.lattice
    if lattice_kind == "cubic":
        lattice = Lattice.cubic(parameters[0])
    elif lattice_kind == "hexagonal":
        lattice = Lattice.hexagonal(parameters[0], parameters[1])
    elif lattice_kind == "orthorhombic":
        lattice = Lattice.orthorhombic(parameters[0], parameters[1], parameters[2])
    else:
        raise ValueError(f"Unsupported scaffold lattice kind: {lattice_kind!r}")
    return Structure(
        lattice,
        [site.species for site in sites],
        [site.frac_coords for site in sites],
    )


def _parse_orbit_definition(
    raw_orbit: tuple[Any, ...],
) -> tuple[str, str | None, str, tuple[str, ...], tuple[float, float, float] | None]:
    orbit_id = str(raw_orbit[0])
    wyckoff_label = str(raw_orbit[1]) if len(raw_orbit) > 1 and raw_orbit[1] is not None else None
    preferred_species = str(raw_orbit[2])
    allowed_species = tuple(str(item) for item in raw_orbit[3]) if len(raw_orbit) > 3 else (preferred_species,)
    representative = _rounded_frac_tuple(raw_orbit[4]) if len(raw_orbit) > 4 else None
    return orbit_id, wyckoff_label, preferred_species, allowed_species, representative


def _coords_for_orbit(
    definition: ScaffoldDefinition,
    species_coords: list[tuple[float, float, float]],
    *,
    representative: tuple[float, float, float] | None,
) -> list[tuple[float, float, float]]:
    if representative is None:
        return list(species_coords)
    from pymatgen.symmetry.groups import SpaceGroup

    matched: list[tuple[float, float, float]] = []
    candidates = list(species_coords)
    for operation in SpaceGroup(definition.space_group).symmetry_ops:
        expected = _rounded_frac_tuple(operation.operate(representative))
        match_index = _periodic_match_index(expected, candidates, tolerance=1e-3)
        if match_index is None:
            continue
        coord = candidates.pop(match_index)
        if not _has_periodic_match(coord, matched, tolerance=1e-3):
            matched.append(coord)
    return matched


def _rounded_frac_tuple(values: Any) -> tuple[float, float, float]:
    return tuple(round(float(value) % 1.0, 6) for value in values)


def _orbits_payload(solution: PrototypeScaffoldSolution) -> list[dict[str, Any]]:
    return [
        {
            "orbit_id": orbit.orbit_id,
            "wyckoff_label": orbit.wyckoff_label,
            "allowed_species": list(orbit.allowed_species),
            "preferred_species": orbit.preferred_species,
            "multiplicity": orbit.multiplicity,
            "fractional_coordinates": [list(coords) for coords in orbit.fractional_coordinates],
            "target_space_group": orbit.target_space_group,
            "target_space_group_number": orbit.target_space_group_number,
            "crystal_system": orbit.crystal_system,
        }
        for orbit in solution.orbits
    ]


def orbit_solution_payload(solution: PrototypeScaffoldSolution) -> dict[str, Any]:
    return {
        "schema_version": "prototype_scaffold_orbit_solution.v1",
        "formula": solution.formula,
        "family": solution.family,
        "target_space_group": solution.target_space_group,
        "target_space_group_number": solution.target_space_group_number,
        "crystal_system": solution.crystal_system,
        "orbit_level_selection": True,
        "variable_orbit_selection": solution.variable_orbit_selection,
        "selected_candidate_id": solution.selected_candidate_id,
        "selected_species_by_orbit": solution.selected_species_by_orbit or {},
        "objective_value": solution.objective_value,
        "spp_scoring_status": solution.spp_scoring_status,
        "spp_source": solution.spp_source,
        "spp_source_type": solution.spp_source_type,
        "spp_pot_dir": solution.spp_pot_dir,
        "spp_fallback_reason": solution.spp_fallback_reason,
        "selected_pair_score_breakdown": solution.selected_pair_score_breakdown or [],
        "solver_backend": solution.solver_backend,
        "orbit_assignment_solver": solution.solver_backend or (_VARIABLE_ORBIT_SELECTOR_BACKEND if solution.variable_orbit_selection else None),
        "formula_satisfied": solution.formula_satisfied,
        "symmetry_closed": solution.symmetry_closed,
        "orbits": _orbits_payload(solution),
        "sites": [
            {
                "site_id": site.site_id,
                "orbit_id": site.orbit_id,
                "species": site.species,
                "frac_coords": list(site.frac_coords),
            }
            for site in solution.sites
        ],
    }


def _requested_site_selection_is_orbit_closed(sites_payload: Any, solution: PrototypeScaffoldSolution) -> bool:
    if not isinstance(sites_payload, dict) or "selected_sites" not in sites_payload:
        return True
    raw_selected = sites_payload.get("selected_sites")
    if raw_selected in (None, [], ()):
        return True
    if not isinstance(raw_selected, list) or not all(isinstance(item, str) for item in raw_selected):
        return False
    selected = set(raw_selected)
    known = {site.site_id for site in solution.sites}
    if not selected.issubset(known):
        return False
    sites_by_orbit: dict[str, set[str]] = {}
    for site in solution.sites:
        sites_by_orbit.setdefault(site.orbit_id, set()).add(site.site_id)
    for orbit_site_ids in sites_by_orbit.values():
        overlap = selected & orbit_site_ids
        if overlap and overlap != orbit_site_ids:
            return False
    return True


def _requested_site_selection_is_complete_or_empty(sites_payload: Any, solution: PrototypeScaffoldSolution) -> bool:
    if not isinstance(sites_payload, dict) or "selected_sites" not in sites_payload:
        return True
    raw_selected = sites_payload.get("selected_sites")
    if raw_selected in (None, [], ()):
        return True
    if not isinstance(raw_selected, list) or not all(isinstance(item, str) for item in raw_selected):
        return False
    selected = set(raw_selected)
    known = {site.site_id for site in solution.sites}
    return selected == known


def _formula_counts(formula: str) -> dict[str, int]:
    from pymatgen.core import Composition

    counts: dict[str, int] = {}
    for element, amount in Composition(formula).get_el_amt_dict().items():
        rounded = int(round(float(amount)))
        if abs(float(amount) - rounded) > 1e-6:
            raise ValueError(f"Variable orbit formula must have integer counts: {formula!r}")
        counts[str(element)] = rounded
    return counts


def _formula_count_options(request: dict[str, Any], formula: str, *, site_count: int | None = None) -> list[dict[str, int]]:
    default = _formula_counts(formula)
    if site_count is not None:
        count_sum = sum(default.values())
        if count_sum > 0 and site_count % count_sum == 0:
            scale = site_count // count_sum
            if scale > 1:
                default = {element: amount * scale for element, amount in default.items()}
    if _spp_source_from_request(request) != "test_fixture":
        return [default]
    problem = request.get("problem") if isinstance(request, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites = design_space.get("sites") if isinstance(design_space, dict) else {}
    constraints = sites.get("formula_constraints") if isinstance(sites, dict) else {}
    raw_options = constraints.get("allowed_target_counts") if isinstance(constraints, dict) else None
    options: list[dict[str, int]] = [default]
    if isinstance(raw_options, list):
        for raw_option in raw_options:
            if not isinstance(raw_option, dict):
                continue
            try:
                option = {str(key): int(value) for key, value in raw_option.items()}
            except (TypeError, ValueError):
                continue
            if option not in options:
                options.append(option)
    return options


def _definition_for(
    prototype: str | None = None,
    formula: str | None = None,
    family: str | None = None,
) -> ScaffoldDefinition | None:
    prototype_key = _normalize_key(prototype)
    formula_key = str(formula or "").replace(" ", "")
    family_key = str(family or "").strip().lower()

    if formula_key and family_key:
        supported_key = _supported_prototype_for(family=family_key, formula=formula_key)
        if supported_key:
            return _SCAFFOLDS[supported_key]
    if prototype_key in _SCAFFOLDS:
        return _SCAFFOLDS[prototype_key]
    return _SCAFFOLDS.get(_supported_prototype_for(family=family_key, formula=formula_key) or "")


def _supported_prototype_for(*, family: str, formula: str) -> str | None:
    formula_key = formula.replace(" ", "")
    family_key = family.strip().lower()
    for key, definition in _SCAFFOLDS.items():
        if definition.formula == formula_key and definition.family.strip().lower() == family_key:
            return key
    if formula_key in {"BaTiO3", "CaTiO3", "SrTiO3"} and family_key == "perovskite":
        return "perovskite"
    if formula_key == "CsPbBr3" and family_key == "halide perovskite":
        return "halide_perovskite"
    if formula_key == "ZnFe2O4" and family_key == "spinel":
        return "spinel"
    if formula_key == "NiO" and family_key == "rocksalt":
        return "rocksalt"
    if formula_key == "CeO2" and family_key == "fluorite":
        return "fluorite"
    if formula_key == "FeS2" and family_key == "pyrite":
        return "pyrite"
    if formula_key == "LiCoO2" and family_key == "layered oxide":
        return "layered_oxide"
    if formula_key == "LiFePO4" and family_key == "olivine phosphate":
        return "olivine_phosphate"
    if formula_key == "Li6PS5Cl" and family_key == "argyrodite":
        return "argyrodite"
    if formula_key == "TiN" and family_key in {"nitride", "rocksalt-like nitride"}:
        return "nitride"
    return None


def _scaffold_symmetry(prototype: str) -> tuple[str, int | None, str]:
    definition = _definition_for(prototype=prototype)
    if definition is not None:
        return definition.space_group, definition.space_group_number, definition.crystal_system
    return "unknown", None, "unknown"


def _normalize_key(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _structure_from_definition(definition: ScaffoldDefinition):
    from pymatgen.core import Lattice, Structure

    lattice_kind, parameters = definition.lattice
    if lattice_kind == "cubic":
        lattice = Lattice.cubic(parameters[0])
    elif lattice_kind == "hexagonal":
        lattice = Lattice.hexagonal(parameters[0], parameters[1])
    elif lattice_kind == "orthorhombic":
        lattice = Lattice.orthorhombic(parameters[0], parameters[1], parameters[2])
    else:
        raise ValueError(f"Unsupported scaffold lattice kind: {lattice_kind!r}")
    species = [site[0] for site in definition.asymmetric_unit]
    coords = [site[1] for site in definition.asymmetric_unit]
    if definition.space_group in {"Pm-3m"}:
        return Structure(lattice, species, coords)
    return Structure.from_spacegroup(definition.space_group, lattice, species, coords)


def _lattice_parameters(structure: Any) -> dict[str, float]:
    lattice = structure.lattice
    return {
        "a": round(float(lattice.a), 6),
        "b": round(float(lattice.b), 6),
        "c": round(float(lattice.c), 6),
        "alpha": round(float(lattice.alpha), 6),
        "beta": round(float(lattice.beta), 6),
        "gamma": round(float(lattice.gamma), 6),
    }


def _fractional_coordinates(structure: Any) -> list[dict[str, Any]]:
    return [
        {
            "species": str(site.specie),
            "frac_coords": [round(float(value) % 1.0, 6) for value in site.frac_coords],
        }
        for site in structure
    ]


def symmetry_closure_report(
    structure: Any,
    *,
    space_group_number: int,
    tolerance: float = 1e-3,
    max_missing: int = 50,
) -> SymmetryClosureReport:
    """Check whether same-species sites are closed under the requested SG."""
    from pymatgen.symmetry.groups import SpaceGroup

    sg = SpaceGroup.from_int_number(int(space_group_number))
    sites = [
        (str(site.specie), tuple(float(value) % 1.0 for value in site.frac_coords))
        for site in structure
    ]
    missing: list[MissingSymmetryMate] = []

    for site_index, (species, coords) in enumerate(sites):
        same_species_coords = [candidate for candidate_species, candidate in sites if candidate_species == species]
        for operation_index, operation in enumerate(sg.symmetry_ops):
            expected = tuple(float(value) % 1.0 for value in operation.operate(coords))
            if not _has_periodic_match(expected, same_species_coords, tolerance=tolerance):
                missing.append(
                    MissingSymmetryMate(
                        species=species,
                        source_index=site_index,
                        operation_index=operation_index,
                        expected_frac_coords=tuple(round(value, 6) for value in expected),
                    )
                )
                if len(missing) >= max_missing:
                    return SymmetryClosureReport(
                        closed=False,
                        space_group_number=int(space_group_number),
                        site_count=len(sites),
                        missing_count=len(missing),
                        missing_mates=tuple(missing),
                    )

    return SymmetryClosureReport(
        closed=not missing,
        space_group_number=int(space_group_number),
        site_count=len(sites),
        missing_count=len(missing),
        missing_mates=tuple(missing),
    )


def _has_periodic_match(
    expected: tuple[float, float, float],
    candidates: list[tuple[float, float, float]],
    *,
    tolerance: float,
) -> bool:
    for candidate in candidates:
        if all(abs((value - reference) - round(value - reference)) <= tolerance for value, reference in zip(expected, candidate)):
            return True
    return False


def _periodic_match_index(
    expected: tuple[float, float, float],
    candidates: list[tuple[float, float, float]],
    *,
    tolerance: float,
) -> int | None:
    for index, candidate in enumerate(candidates):
        if all(abs((value - reference) - round(value - reference)) <= tolerance for value, reference in zip(expected, candidate)):
            return index
    return None


__all__ = [
    "MissingSymmetryMate",
    "PrototypeScaffoldSolution",
    "ScaffoldOrbit",
    "ScaffoldSite",
    "SymmetryClosureReport",
    "ideal_prototype_structure",
    "orbit_solution_payload",
    "prototype_orbit_candidates_payload_from_request",
    "prototype_orbit_solution_from_request",
    "prototype_scaffold_from_request",
    "scaffold_matches_final_cif",
    "symmetry_closure_report",
    "write_prototype_scaffold_cif",
]
