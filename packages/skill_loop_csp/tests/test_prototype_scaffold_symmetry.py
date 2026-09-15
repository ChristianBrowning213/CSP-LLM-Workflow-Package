from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pymatgen.core import Composition
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pymatgen.core import Structure

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.spp_regularisation import find_spp_pot_root, formula_pairs
from sok_llm_orchestrator.structures.parseable_cif import build_parseable_structure
from sok_llm_orchestrator.structures.prototype_scaffold import (
    ideal_prototype_structure,
    prototype_orbit_candidates_payload_from_request,
    prototype_orbit_solution_from_request,
    scaffold_matches_final_cif,
    symmetry_closure_report,
    write_prototype_scaffold_cif,
)


_SMOKE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_prototype_orbit_variable_spp_qlip_smoke.py"
_SMOKE_SPEC = importlib.util.spec_from_file_location("run_prototype_orbit_variable_spp_qlip_smoke", _SMOKE_SCRIPT)
assert _SMOKE_SPEC is not None and _SMOKE_SPEC.loader is not None
_SMOKE_MODULE = importlib.util.module_from_spec(_SMOKE_SPEC)
_SMOKE_SPEC.loader.exec_module(_SMOKE_MODULE)
CASES = _SMOKE_MODULE.CASES
build_spp_preflight = _SMOKE_MODULE.build_spp_preflight
run_smoke = _SMOKE_MODULE.run_smoke


def _analyze(structure):
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5)
    return analyzer.get_space_group_symbol(), analyzer.get_space_group_number(), analyzer.get_crystal_system()


def _request(formula: str, family: str, space_group: str, crystal_system: str = "cubic") -> dict:
    return {
        "problem": {
            "chemistry": {"formula": formula},
            "design_space": {
                "sites": {
                    "mode": "prototype_scaffold",
                    "candidate_site_source": "prototype_scaffold",
                    "prototype_scaffold": {
                        "family": family,
                        "target_space_group": space_group,
                        "target_crystal_system": crystal_system,
                    },
                }
            },
        }
    }


def _orbit_request(formula: str, family: str, space_group: str, crystal_system: str = "cubic") -> dict:
    request = _request(formula, family, space_group, crystal_system)
    sites = request["problem"]["design_space"]["sites"]
    sites["mode"] = "prototype_orbit_qlip"
    sites["site_mode"] = "prototype_orbit"
    sites["candidate_site_source"] = "prototype_orbit_scaffold"
    return request


def _variable_orbit_request(formula: str) -> dict:
    request = _request(formula, "perovskite", "Pm-3m")
    sites = request["problem"]["design_space"]["sites"]
    sites["mode"] = "prototype_orbit_variable_qlip"
    sites["site_mode"] = "prototype_orbit_variable"
    sites["candidate_site_source"] = "prototype_orbit_variable_scaffold"
    return request


def _variable_spp_orbit_request(formula: str, pot_root: Path | None = None, *, spp_source: str | None = None) -> dict:
    request = _variable_orbit_request(formula)
    sites = request["problem"]["design_space"]["sites"]
    sites["mode"] = "prototype_orbit_variable_spp_qlip"
    if pot_root is not None:
        request["context"] = {"pot_root": str(pot_root)}
        if spp_source is not None:
                request["context"]["spp_source"] = spp_source
    return request


def _variable_spp_orbit_request_for_family(
    formula: str,
    family: str,
    space_group: str,
    pot_root: Path,
    *,
    crystal_system: str = "cubic",
) -> dict:
    request = _request(formula, family, space_group, crystal_system)
    sites = request["problem"]["design_space"]["sites"]
    sites["mode"] = "prototype_orbit_variable_spp_qlip"
    sites["site_mode"] = "prototype_orbit_variable"
    sites["candidate_site_source"] = "prototype_orbit_variable_scaffold"
    sites["spp_source"] = "direct_pot_dir"
    sites["spp_source_type"] = "direct_pot_dir"
    sites["required_pairs"] = formula_pairs(formula)
    sites["missing_pairs"] = []
    request["context"] = {
        "pot_root": str(pot_root),
        "spp_source": "direct_pot_dir",
        "spp_source_type": "direct_pot_dir",
    }
    return request


def _write_fixture_pot(root: Path, pair: str, value: float) -> None:
    pair_dir = root / pair
    pair_dir.mkdir(parents=True, exist_ok=True)
    (pair_dir / f"{pair}.POT").write_text(f"0.0 {value}\n8.0 {value}\n", encoding="utf-8")


def _bad_contact_threshold(left: str, right: str) -> float:
    try:
        from pymatgen.core import Element

        left_radius = float(Element(left).atomic_radius or 1.2)
        right_radius = float(Element(right).atomic_radius or 1.2)
    except Exception:
        left_radius = 1.2
        right_radius = 1.2
    return max(0.65, 0.45 * (left_radius + right_radius))


def _bad_contact_count(structure: Structure) -> tuple[int, float]:
    min_distance = 999.0
    bad_count = 0
    for left in range(len(structure)):
        for right in range(left + 1, len(structure)):
            distance = float(structure.get_distance(left, right))
            min_distance = min(min_distance, distance)
            if distance < _bad_contact_threshold(str(structure[left].specie), str(structure[right].specie)):
                bad_count += 1
    return bad_count, min_distance


SCAFFOLD_CASES = [
    ("BaTiO3", "perovskite", "Pm-3m", 221, "cubic", 5),
    ("CsPbBr3", "halide perovskite", "Pm-3m", 221, "cubic", 5),
    ("ZnFe2O4", "spinel", "Fd-3m", 227, "cubic", 56),
    ("NiO", "rocksalt", "Fm-3m", 225, "cubic", 8),
    ("CeO2", "fluorite", "Fm-3m", 225, "cubic", 12),
    ("FeS2", "pyrite", "Pa-3", 205, "cubic", 12),
    ("LiCoO2", "layered oxide", "R-3m", 166, "trigonal", 12),
    ("LiFePO4", "olivine phosphate", "Pnma", 62, "orthorhombic", 28),
    ("Li6PS5Cl", "argyrodite", "F-43m", 216, "cubic", 52),
    ("TiN", "nitride", "Fm-3m", 225, "cubic", 8),
]

ORBIT_CASES = [
    ("BaTiO3", "perovskite", "Pm-3m", 221, "cubic", [("Ba", "1a", 1), ("Ti", "1b", 1), ("O", "3c", 3)]),
    (
        "CsPbBr3",
        "halide perovskite",
        "Pm-3m",
        221,
        "cubic",
        [("Cs", "1a", 1), ("Pb", "1b", 1), ("Br", "3c", 3)],
    ),
    ("ZnFe2O4", "spinel", "Fd-3m", 227, "cubic", [("Zn", "8a", 8), ("Fe", "16d", 16), ("O", "32e", 32)]),
    ("NiO", "rocksalt", "Fm-3m", 225, "cubic", [("Ni", "4a", 4), ("O", "4b", 4)]),
    ("CeO2", "fluorite", "Fm-3m", 225, "cubic", [("Ce", "4a", 4), ("O", "8c", 8)]),
    ("FeS2", "pyrite", "Pa-3", 205, "cubic", [("Fe", "4a", 4), ("S", "8c", 8)]),
    ("LiCoO2", "layered oxide", "R-3m", 166, "trigonal", [("Li", "3a", 3), ("Co", "3b", 3), ("O", "6c", 6)]),
    (
        "LiFePO4",
        "olivine phosphate",
        "Pnma",
        62,
        "orthorhombic",
        [("Li", "4a", 4), ("Fe", "4c", 4), ("P", "4c", 4), ("O", "4c", 4), ("O", "4c", 4), ("O", "8d", 8)],
    ),
    (
        "Li6PS5Cl",
        "argyrodite",
        "F-43m",
        216,
        "cubic",
        [("P", "4b", 4), ("S", "4a", 4), ("S", "16e", 16), ("Cl", "4d", 4), ("Li", "24g", 24)],
    ),
    ("TiN", "nitride", "Fm-3m", 225, "cubic", [("Ti", "4a", 4), ("N", "4b", 4)]),
]


FAMILY_COMPATIBLE_SYSTEMS = {
    "perovskite": {"cubic", "tetragonal", "orthorhombic"},
    "halide perovskite": {"cubic", "tetragonal", "orthorhombic"},
    "spinel": {"cubic"},
    "rocksalt": {"cubic"},
    "fluorite": {"cubic"},
    "pyrite": {"cubic"},
    "layered oxide": {"rhombohedral", "hexagonal", "trigonal"},
    "olivine phosphate": {"orthorhombic"},
    "argyrodite": {"cubic"},
    "nitride": {"cubic"},
    "rocksalt-like nitride": {"cubic"},
}


def test_all_10_supported_scaffolds_have_expected_formula_and_symmetry() -> None:
    for formula, family, space_group, space_group_number, crystal_system, site_count in SCAFFOLD_CASES:
        structure = ideal_prototype_structure(family, formula)
        symbol, number, analyzed_system = _analyze(structure)

        assert structure.composition.reduced_composition == Composition(formula).reduced_composition
        assert len(structure) == site_count
        assert analyzed_system == crystal_system
        assert analyzed_system in FAMILY_COMPATIBLE_SYSTEMS[family]
        assert (symbol, number) == (space_group, space_group_number)
        assert symmetry_closure_report(structure, space_group_number=space_group_number).closed is True


def test_all_10_orbit_scaffolds_have_expected_formula_symmetry_and_orbits() -> None:
    for formula, family, space_group, space_group_number, crystal_system, expected_orbits in ORBIT_CASES:
        request = _orbit_request(formula, family, space_group, crystal_system)
        solution = prototype_orbit_solution_from_request(request)
        structure = ideal_prototype_structure(family, formula)
        symbol, number, analyzed_system = _analyze(structure)

        assert solution is not None
        assert solution.formula == formula
        assert solution.family == family
        assert solution.target_space_group == space_group
        assert solution.target_space_group_number == space_group_number
        assert solution.crystal_system == crystal_system
        assert solution.symmetry_closed is True
        assert structure.composition.reduced_composition == Composition(formula).reduced_composition
        assert len(solution.sites) == len(structure)
        assert sum(orbit.multiplicity for orbit in solution.orbits) == len(structure)
        assert [(orbit.preferred_species, orbit.wyckoff_label, orbit.multiplicity) for orbit in solution.orbits] == expected_orbits
        assert all(orbit.fractional_coordinates for orbit in solution.orbits)
        assert (symbol, number, analyzed_system) == (space_group, space_group_number, crystal_system)


@pytest.mark.parametrize(
    ("formula", "expected_min_distance_floor"),
    [
        ("ZnFe2O4", 1.9),
        ("MgAl2O4", 1.8),
        ("CoFe2O4", 1.9),
    ],
)
def test_spinel_scaffolds_have_no_severe_short_contacts(formula: str, expected_min_distance_floor: float) -> None:
    structure = ideal_prototype_structure("spinel", formula)
    bad_count, min_distance = _bad_contact_count(structure)

    assert structure.composition.reduced_composition == Composition(formula).reduced_composition
    assert _analyze(structure) == ("Fd-3m", 227, "cubic")
    assert bad_count == 0
    assert min_distance > expected_min_distance_floor


def test_ideal_batio3_perovskite_scaffold_is_pm3m_cubic() -> None:
    structure = ideal_prototype_structure("perovskite", "BaTiO3")

    symbol, number, crystal_system = _analyze(structure)

    assert (symbol, number, crystal_system) == ("Pm-3m", 221, "cubic")
    assert symmetry_closure_report(structure, space_group_number=221).closed is True


def test_batio3_orbit_scaffold_has_expected_orbits() -> None:
    solution = prototype_orbit_solution_from_request(_orbit_request("BaTiO3", "perovskite", "Pm-3m"))

    assert solution is not None
    assert [(orbit.preferred_species, orbit.wyckoff_label, orbit.multiplicity) for orbit in solution.orbits] == [
        ("Ba", "1a", 1),
        ("Ti", "1b", 1),
        ("O", "3c", 3),
    ]
    assert solution.symmetry_closed is True


def test_ideal_nio_rocksalt_scaffold_is_fm3m_cubic() -> None:
    structure = ideal_prototype_structure("rocksalt", "NiO")

    symbol, number, crystal_system = _analyze(structure)

    assert (symbol, number, crystal_system) == ("Fm-3m", 225, "cubic")
    assert symmetry_closure_report(structure, space_group_number=225).closed is True


def test_nio_orbit_scaffold_has_rocksalt_orbits() -> None:
    solution = prototype_orbit_solution_from_request(_orbit_request("NiO", "rocksalt", "Fm-3m"))

    assert solution is not None
    assert [(orbit.preferred_species, orbit.wyckoff_label, orbit.multiplicity) for orbit in solution.orbits] == [
        ("Ni", "4a", 4),
        ("O", "4b", 4),
    ]
    assert solution.symmetry_closed is True


def test_ideal_ceo2_fluorite_scaffold_is_fm3m_cubic() -> None:
    structure = ideal_prototype_structure("fluorite", "CeO2")

    symbol, number, crystal_system = _analyze(structure)

    assert (symbol, number, crystal_system) == ("Fm-3m", 225, "cubic")
    assert symmetry_closure_report(structure, space_group_number=225).closed is True


def test_ceo2_orbit_scaffold_has_fluorite_orbits() -> None:
    solution = prototype_orbit_solution_from_request(_orbit_request("CeO2", "fluorite", "Fm-3m"))

    assert solution is not None
    assert [(orbit.preferred_species, orbit.wyckoff_label, orbit.multiplicity) for orbit in solution.orbits] == [
        ("Ce", "4a", 4),
        ("O", "8c", 8),
    ]
    assert solution.symmetry_closed is True


def test_generic_parseable_nio_coordinates_are_not_closed_under_fm3m() -> None:
    structure = build_parseable_structure("NiO", lattice_a=4.0)

    report = symmetry_closure_report(structure, space_group_number=225)

    assert report.closed is False
    assert report.missing_count > 0


def test_final_cif_writer_uses_batio3_scaffold_when_requested() -> None:
    tmp = TemporaryDirectory()
    cif_path = Path(tmp.name) / "solution.cif"
    trace = write_prototype_scaffold_cif(cif_path, _request("BaTiO3", "perovskite", "Pm-3m"))

    symbol, number, crystal_system = _analyze(Structure.from_file(cif_path))
    match = scaffold_matches_final_cif(cif_path, _request("BaTiO3", "perovskite", "Pm-3m"))

    assert trace["scaffold_used_for_final_cif"] is True
    assert trace["final_cif_source"] == "prototype_scaffold"
    assert trace["scaffold_space_group_number"] == 221
    assert (symbol, number, crystal_system) == ("Pm-3m", 221, "cubic")
    assert match["scaffold_used_for_final_cif"] is True
    assert match["scaffold_site_count"] == 5


def test_orbit_level_output_is_symmetry_closed_and_analyzes_to_expected_sg() -> None:
    with TemporaryDirectory() as tmp_name:
        cif_path = Path(tmp_name) / "solution.cif"
        request = _orbit_request("NiO", "rocksalt", "Fm-3m")
        trace = write_prototype_scaffold_cif(cif_path, request)
        structure = Structure.from_file(cif_path)
        symbol, number, crystal_system = _analyze(structure)

        assert trace["active_symmetry_mode"] == "prototype_orbit_qlip"
        assert trace["orbit_level_selection"] is True
        assert trace["final_cif_source"] == "prototype_orbit_qlip"
        assert trace["symmetry_closed"] is True
        assert trace["selected_orbits"] == ["ni_4a", "o_4b"]
        assert len(trace["selected_sites"]) == 8
        assert symmetry_closure_report(structure, space_group_number=225).closed is True
        assert (symbol, number, crystal_system) == ("Fm-3m", 225, "cubic")


def test_orbit_mode_rejects_individual_site_non_closed_subset() -> None:
    with TemporaryDirectory() as tmp_name:
        cif_path = Path(tmp_name) / "solution.cif"
        request = _orbit_request("NiO", "rocksalt", "Fm-3m")
        request["problem"]["design_space"]["sites"]["selected_sites"] = ["ni_4a:1"]
        trace = write_prototype_scaffold_cif(cif_path, request)

        assert trace["active_symmetry_mode"] == "prototype_orbit_qlip"
        assert trace["scaffold_used_for_final_cif"] is False
        assert trace["fallback_reason"] == "non_closed_orbit_site_selection_rejected"
        assert not cif_path.exists()


def test_orbit_mode_rejects_non_closed_subset_for_duplicate_species_orbits() -> None:
    with TemporaryDirectory() as tmp_name:
        cif_path = Path(tmp_name) / "solution.cif"
        request = _orbit_request("Li6PS5Cl", "argyrodite", "F-43m")
        request["problem"]["design_space"]["sites"]["selected_sites"] = ["s2_16e:1"]
        trace = write_prototype_scaffold_cif(cif_path, request)

        assert trace["active_symmetry_mode"] == "prototype_orbit_qlip"
        assert trace["scaffold_used_for_final_cif"] is False
        assert trace["fallback_reason"] == "non_closed_orbit_site_selection_rejected"
        assert not cif_path.exists()


def test_variable_orbit_perovskite_selects_formula_constrained_a_site_species() -> None:
    for formula, expected_a_species in [("BaTiO3", "Ba"), ("CaTiO3", "Ca"), ("SrTiO3", "Sr")]:
        request = _variable_orbit_request(formula)
        solution = prototype_orbit_solution_from_request(request)
        candidates = prototype_orbit_candidates_payload_from_request(request)

        assert solution is not None
        assert candidates is not None
        assert solution.variable_orbit_selection is True
        assert solution.selected_species_by_orbit == {
            "ba_1a": expected_a_species,
            "ti_1b": "Ti",
            "o_3c": "O",
        }
        assert [(orbit.orbit_id, orbit.wyckoff_label, orbit.multiplicity) for orbit in solution.orbits] == [
            ("ba_1a", "1a", 1),
            ("ti_1b", "1b", 1),
            ("o_3c", "3c", 3),
        ]
        assert next(orbit for orbit in solution.orbits if orbit.orbit_id == "ba_1a").allowed_species == ("Ba", "Ca", "Sr")
        assert Composition({site.species: sum(1 for other in solution.sites if other.species == site.species) for site in solution.sites}).reduced_composition == Composition(formula).reduced_composition
        assert solution.symmetry_closed is True
        assert candidates["mode"] == "prototype_orbit_variable_qlip"
        assert candidates["target_counts"][expected_a_species] == 1
        assert len([candidate for candidate in candidates["candidates"] if candidate["formula_satisfied"]]) == 1


def test_variable_orbit_output_is_symmetry_closed_and_analyzes_to_expected_sg() -> None:
    with TemporaryDirectory() as tmp_name:
        cif_path = Path(tmp_name) / "solution.cif"
        request = _variable_orbit_request("CaTiO3")
        trace = write_prototype_scaffold_cif(cif_path, request)
        structure = Structure.from_file(cif_path)
        symbol, number, crystal_system = _analyze(structure)

        assert trace["active_symmetry_mode"] == "prototype_orbit_variable_qlip"
        assert trace["orbit_level_selection"] is True
        assert trace["variable_orbit_selection"] is True
        assert trace["final_cif_source"] == "prototype_orbit_variable_qlip"
        assert trace["symmetry_closed"] is True
        assert trace["selected_species_by_orbit"]["ba_1a"] == "Ca"
        assert symmetry_closure_report(structure, space_group_number=221).closed is True
        assert (symbol, number, crystal_system) == ("Pm-3m", 221, "cubic")


def test_variable_orbit_mode_rejects_individual_site_subset() -> None:
    with TemporaryDirectory() as tmp_name:
        cif_path = Path(tmp_name) / "solution.cif"
        request = _variable_orbit_request("SrTiO3")
        request["problem"]["design_space"]["sites"]["selected_sites"] = ["ba_1a:1"]
        trace = write_prototype_scaffold_cif(cif_path, request)

        assert trace["active_symmetry_mode"] == "prototype_orbit_variable_qlip"
        assert trace["variable_orbit_selection"] is True
        assert trace["scaffold_used_for_final_cif"] is False
        assert trace["fallback_reason"] == "non_closed_orbit_site_selection_rejected"
        assert not cif_path.exists()


def test_variable_orbit_mode_reports_explicit_fallback_for_unsupported_case() -> None:
    with TemporaryDirectory() as tmp_name:
        cif_path = Path(tmp_name) / "solution.cif"
        request = _orbit_request("FeS2", "pyrite", "Pa-3")
        sites = request["problem"]["design_space"]["sites"]
        sites["mode"] = "prototype_orbit_variable_qlip"
        sites["site_mode"] = "prototype_orbit_variable"
        sites["candidate_site_source"] = "prototype_orbit_variable_scaffold"

        trace = write_prototype_scaffold_cif(cif_path, request)

        assert trace["active_symmetry_mode"] == "prototype_orbit_variable_qlip"
        assert trace["variable_orbit_selection"] is True
        assert trace["scaffold_used_for_final_cif"] is False
        assert trace["fallback_reason"] == "unsupported_variable_orbit_case"
        assert not cif_path.exists()


def test_variable_spp_orbit_ranks_valid_fixture_assignments_by_pair_curves() -> None:
    with TemporaryDirectory() as tmp_name:
        pot_root = Path(tmp_name) / "spp_root"
        for pair, value in {
            "Ba-O": 0.0,
            "Ba-Ti": 0.0,
            "Ca-O": 5.0,
            "Ca-Ti": 5.0,
            "O-O": 0.0,
            "O-Ti": 0.0,
        }.items():
            _write_fixture_pot(pot_root, pair, value)
        request = _variable_spp_orbit_request("BaTiO3", pot_root, spp_source="test_fixture")
        request["problem"]["design_space"]["sites"]["formula_constraints"] = {
            "allowed_target_counts": [
                {"Ba": 1, "Ti": 1, "O": 3},
                {"Ca": 1, "Ti": 1, "O": 3},
            ]
        }

        candidates = prototype_orbit_candidates_payload_from_request(request)
        solution = prototype_orbit_solution_from_request(request)

        assert candidates is not None
        valid_candidates = [candidate for candidate in candidates["candidates"] if candidate["formula_satisfied"]]
        assert len(valid_candidates) == 2
        assert candidates["spp_scoring_status"] == "test_fixture"
        assert all(candidate["objective_value"] is not None for candidate in valid_candidates)
        assert solution is not None
        assert solution.spp_scoring_status == "test_fixture"
        assert solution.selected_species_by_orbit == {"ba_1a": "Ba", "ti_1b": "Ti", "o_3c": "O"}
        assert solution.objective_value == min(float(candidate["objective_value"]) for candidate in valid_candidates)
        assert solution.symmetry_closed is True


def test_variable_spp_orbit_direct_fixture_pot_dir_scores_real_mode() -> None:
    with TemporaryDirectory() as tmp_name:
        pot_root = Path(tmp_name) / "spp_root"
        for pair in formula_pairs("BaTiO3"):
            _write_fixture_pot(pot_root, pair, 1.0)
        request = _variable_spp_orbit_request("BaTiO3", pot_root, spp_source="direct_pot_dir")
        request["problem"]["design_space"]["sites"]["spp_source_type"] = "direct_pot_dir"
        request["problem"]["design_space"]["sites"]["required_pairs"] = formula_pairs("BaTiO3")
        request["problem"]["design_space"]["sites"]["missing_pairs"] = []
        solution = prototype_orbit_solution_from_request(request)
        candidates = prototype_orbit_candidates_payload_from_request(request)

        assert solution is not None
        assert candidates is not None
        assert solution.spp_scoring_status == "scored"
        assert solution.spp_source_type == "direct_pot_dir"
        assert solution.spp_pot_dir == str(pot_root)
        assert solution.objective_value is not None
        assert solution.selected_pair_score_breakdown
        assert candidates["loaded_pair_count"] == len(formula_pairs("BaTiO3"))
        selected = next(candidate for candidate in candidates["candidates"] if candidate["candidate_id"] == solution.selected_candidate_id)
        assert selected["missing_pair_count"] == 0
        assert selected["pair_score_breakdown"]
        assert selected["symmetry_closed"] is True


def test_variable_spp_orbit_accepts_uppercase_real_corpus_pair_names() -> None:
    with TemporaryDirectory() as tmp_name:
        pot_root = Path(tmp_name) / "spp_root"
        for pair in formula_pairs("BaTiO3"):
            upper_pair = pair.upper()
            pair_dir = pot_root / upper_pair
            pair_dir.mkdir(parents=True, exist_ok=True)
            (pair_dir / f"{upper_pair}.POT").write_text("0.0 1.0\n8.0 1.0\n", encoding="utf-8")
        request = _variable_spp_orbit_request("BaTiO3", pot_root, spp_source="direct_pot_dir")
        request["problem"]["design_space"]["sites"]["spp_source_type"] = "direct_pot_dir"
        request["problem"]["design_space"]["sites"]["required_pairs"] = formula_pairs("BaTiO3")
        request["problem"]["design_space"]["sites"]["missing_pairs"] = []
        solution = prototype_orbit_solution_from_request(request)

        assert solution is not None
        assert solution.spp_scoring_status == "scored"
        assert solution.objective_value is not None
        assert solution.selected_pair_score_breakdown


def test_variable_spp_orbit_ax_rocksalt_scores_formula_and_symmetry() -> None:
    with TemporaryDirectory() as tmp_name:
        pot_root = Path(tmp_name) / "spp_root"
        for pair in formula_pairs("NiO"):
            _write_fixture_pot(pot_root, pair, 1.0)
        request = _variable_spp_orbit_request_for_family("NiO", "rocksalt", "Fm-3m", pot_root)
        solution = prototype_orbit_solution_from_request(request)
        candidates = prototype_orbit_candidates_payload_from_request(request)
        cif_path = pot_root / "NiO.cif"
        trace = write_prototype_scaffold_cif(cif_path, request)

        assert solution is not None
        assert candidates is not None
        assert solution.variable_orbit_selection is True
        assert solution.formula_satisfied is True
        assert solution.symmetry_closed is True
        assert solution.spp_scoring_status == "scored"
        assert solution.objective_value is not None
        assert solution.selected_species_by_orbit == {"ni_4a": "Ni", "o_4b": "O"}
        assert any(not candidate["formula_satisfied"] for candidate in candidates["candidates"])
        assert trace["active_symmetry_mode"] == "prototype_orbit_variable_spp_qlip"
        assert trace["variable_orbit_selection"] is True
        assert trace["objective_value"] is not None
        assert cif_path.exists()
        assert _analyze(Structure.from_file(cif_path)) == ("Fm-3m", 225, "cubic")


def test_variable_spp_orbit_ax2_fluorite_scores_formula_and_symmetry() -> None:
    with TemporaryDirectory() as tmp_name:
        pot_root = Path(tmp_name) / "spp_root"
        for pair in formula_pairs("CeO2"):
            _write_fixture_pot(pot_root, pair, 1.0)
        request = _variable_spp_orbit_request_for_family("CeO2", "fluorite", "Fm-3m", pot_root)
        solution = prototype_orbit_solution_from_request(request)
        candidates = prototype_orbit_candidates_payload_from_request(request)
        cif_path = pot_root / "CeO2.cif"
        trace = write_prototype_scaffold_cif(cif_path, request)

        assert solution is not None
        assert candidates is not None
        assert solution.variable_orbit_selection is True
        assert solution.formula_satisfied is True
        assert solution.symmetry_closed is True
        assert solution.spp_scoring_status == "scored"
        assert solution.objective_value is not None
        assert solution.selected_species_by_orbit == {"ce_4a": "Ce", "o_8c": "O"}
        assert any(not candidate["formula_satisfied"] for candidate in candidates["candidates"])
        assert trace["active_symmetry_mode"] == "prototype_orbit_variable_spp_qlip"
        assert trace["variable_orbit_selection"] is True
        assert trace["objective_value"] is not None
        assert cif_path.exists()
        assert _analyze(Structure.from_file(cif_path)) == ("Fm-3m", 225, "cubic")


@pytest.mark.parametrize(
    ("formula", "expected_species"),
    [
        ("CsPbBr3", {"cs_1a": "Cs", "pb_1b": "Pb", "br_3c": "Br"}),
        ("CsSnBr3", {"cs_1a": "Cs", "sn_1b": "Sn", "br_3c": "Br"}),
        ("CsPbCl3", {"cs_1a": "Cs", "pb_1b": "Pb", "cl_3c": "Cl"}),
        ("CsSnI3", {"cs_1a": "Cs", "sn_1b": "Sn", "i_3c": "I"}),
        ("CsPbI3", {"cs_1a": "Cs", "pb_1b": "Pb", "i_3c": "I"}),
    ],
)
def test_variable_spp_orbit_cubic_halide_abx3_scores_formula_and_symmetry(formula: str, expected_species: dict[str, str]) -> None:
    with TemporaryDirectory() as tmp_name:
        pot_root = Path(tmp_name) / "spp_root"
        for pair in formula_pairs(formula):
            _write_fixture_pot(pot_root, pair, 1.0)
        request = _variable_spp_orbit_request_for_family(formula, "halide perovskite", "Pm-3m", pot_root)
        solution = prototype_orbit_solution_from_request(request)
        candidates = prototype_orbit_candidates_payload_from_request(request)
        cif_path = pot_root / f"{formula}.cif"
        trace = write_prototype_scaffold_cif(cif_path, request)

        assert solution is not None
        assert candidates is not None
        assert solution.variable_orbit_selection is True
        assert solution.formula_satisfied is True
        assert solution.symmetry_closed is True
        assert solution.spp_scoring_status == "scored"
        assert solution.objective_value is not None
        assert solution.selected_species_by_orbit == expected_species
        assert candidates["missing_pairs"] == []
        assert all(orbit["wyckoff_label"] in {"1a", "1b", "3c"} for orbit in candidates["orbits"])
        assert trace["active_symmetry_mode"] == "prototype_orbit_variable_spp_qlip"
        assert trace["variable_orbit_selection"] is True
        assert trace["objective_value"] is not None
        assert cif_path.exists()
        structure = Structure.from_file(cif_path)
        assert structure.composition.reduced_composition == Composition(formula).reduced_composition
        assert _analyze(structure) == ("Pm-3m", 221, "cubic")


def test_variable_spp_orbit_cubic_halide_abx3_does_not_label_without_objective() -> None:
    request = _variable_spp_orbit_request_for_family("CsPbBr3", "halide perovskite", "Pm-3m", Path("missing_pot_root"))
    request.pop("context", None)
    sites = request["problem"]["design_space"]["sites"]
    sites["spp_pot_dir"] = None
    sites["missing_pairs"] = formula_pairs("CsPbBr3")

    solution = prototype_orbit_solution_from_request(request)

    assert solution is not None
    assert solution.spp_scoring_status == "unavailable"
    assert solution.objective_value is None
    assert solution.selected_species_by_orbit == {"cs_1a": "Cs", "pb_1b": "Pb", "br_3c": "Br"}


def test_variable_spp_orbit_records_unavailable_without_spp_curves() -> None:
    request = _variable_spp_orbit_request("CaTiO3")
    solution = prototype_orbit_solution_from_request(request)
    candidates = prototype_orbit_candidates_payload_from_request(request)

    assert solution is not None
    assert candidates is not None
    assert solution.selected_species_by_orbit == {"ba_1a": "Ca", "ti_1b": "Ti", "o_3c": "O"}
    assert solution.spp_scoring_status == "unavailable"
    assert solution.spp_fallback_reason == "spp_curves_unavailable"
    assert solution.objective_value is None
    assert candidates["spp_scoring_status"] == "unavailable"
    assert candidates["fallback_reason"] == "spp_curves_unavailable"


def test_spp_preflight_records_direct_pot_dir_ready_and_bypasses_retrieval() -> None:
    with TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        pot_root = root / "spp_root"
        for pair in formula_pairs("BaTiO3"):
            _write_fixture_pot(pot_root, pair, 1.0)
        settings = Settings.from_sources(None)
        preflight = build_spp_preflight(
            case=CASES[0],
            settings=settings,
            workspace=root,
            pot_dir=pot_root,
            run_service_probes=True,
        )

        assert preflight["final_status"] == "ready"
        assert preflight["source_type"] == "direct_pot_dir"
        assert preflight["crystaldb_status"] == "skipped_direct_pot_dir"
        assert preflight["vector_query_status"] == "skipped_direct_pot_dir"
        assert preflight["loaded_pair_count"] == len(formula_pairs("BaTiO3"))
        assert preflight["missing_pairs"] == []


def test_spp_preflight_accepts_uppercase_real_corpus_pair_names() -> None:
    with TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        pot_root = root / "spp_root"
        for pair in formula_pairs("BaTiO3"):
            upper_pair = pair.upper()
            pair_dir = pot_root / upper_pair
            pair_dir.mkdir(parents=True, exist_ok=True)
            (pair_dir / f"{upper_pair}.POT").write_text("0.0 1.0\n8.0 1.0\n", encoding="utf-8")
        settings = Settings.from_sources(None)
        preflight = build_spp_preflight(
            case=CASES[0],
            settings=settings,
            workspace=root,
            pot_dir=pot_root,
            run_service_probes=False,
        )

        assert preflight["final_status"] == "ready"
        assert preflight["loaded_pair_count"] == len(formula_pairs("BaTiO3"))
        assert preflight["missing_pairs"] == []


def test_spp_preflight_discovers_configured_uppercase_pot_root_without_direct_pot_dir() -> None:
    with TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        pot_root = root / "SPP"
        for pair in formula_pairs("BaTiO3"):
            upper_pair = pair.upper()
            pair_dir = pot_root / upper_pair
            pair_dir.mkdir(parents=True, exist_ok=True)
            (pair_dir / f"{upper_pair}.POT").write_text("0.0 1.0\n8.0 1.0\n", encoding="utf-8")
        settings = Settings.from_sources(None)
        settings.qlip_allowed_path_roots = [pot_root]
        preflight = build_spp_preflight(
            case=CASES[0],
            settings=settings,
            workspace=root,
            pot_dir=None,
            run_service_probes=False,
        )

        assert find_spp_pot_root([pot_root], "BaTiO3") == str(pot_root.resolve())
        assert preflight["final_status"] == "ready"
        assert preflight["source_type"] == "discovered_exported_pot_dir"
        assert preflight["missing_pairs"] == []


def test_spp_preflight_records_unavailable_without_pot_dir() -> None:
    with TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        settings = Settings.from_sources(None)
        settings.qlip_allowed_path_roots = [root / "missing"]
        preflight = build_spp_preflight(
            case=CASES[0],
            settings=settings,
            workspace=root,
            pot_dir=None,
            run_service_probes=False,
        )

        assert preflight["final_status"] == "unavailable"
        assert preflight["source_type"] == "unavailable"
        assert preflight["failure_reason"] == "spp_pot_curves_unavailable"
        assert preflight["loaded_pair_count"] == 0
        assert preflight["missing_pairs"] == sorted(formula_pairs("BaTiO3"))


def test_variable_spp_smoke_require_real_spp_exits_when_curves_missing() -> None:
    with TemporaryDirectory() as tmp_name:
        with pytest.raises(SystemExit) as excinfo:
            run_smoke(Path(tmp_name), require_real_spp=True, run_spp_preflight=False)

        assert "Real SPP curves are required but unavailable" in str(excinfo.value)


def test_final_cif_writer_uses_nio_scaffold_when_requested() -> None:
    tmp = TemporaryDirectory()
    cif_path = Path(tmp.name) / "solution.cif"
    trace = write_prototype_scaffold_cif(cif_path, _request("NiO", "rocksalt", "Fm-3m"))

    symbol, number, crystal_system = _analyze(Structure.from_file(cif_path))

    assert trace["scaffold_used_for_final_cif"] is True
    assert trace["final_cif_source"] == "prototype_scaffold"
    assert trace["scaffold_space_group_number"] == 225
    assert (symbol, number, crystal_system) == ("Fm-3m", 225, "cubic")
    assert scaffold_matches_final_cif(cif_path, _request("NiO", "rocksalt", "Fm-3m"))["scaffold_used_for_final_cif"] is True


def test_final_cif_writer_uses_ceo2_scaffold_when_requested() -> None:
    tmp = TemporaryDirectory()
    cif_path = Path(tmp.name) / "solution.cif"
    trace = write_prototype_scaffold_cif(cif_path, _request("CeO2", "fluorite", "Fm-3m"))

    symbol, number, crystal_system = _analyze(Structure.from_file(cif_path))

    assert trace["scaffold_used_for_final_cif"] is True
    assert trace["final_cif_source"] == "prototype_scaffold"
    assert trace["scaffold_space_group_number"] == 225
    assert (symbol, number, crystal_system) == ("Fm-3m", 225, "cubic")
    assert scaffold_matches_final_cif(cif_path, _request("CeO2", "fluorite", "Fm-3m"))["scaffold_used_for_final_cif"] is True


def test_final_cif_writer_reports_fallback_for_unsupported_scaffold() -> None:
    tmp = TemporaryDirectory()
    cif_path = Path(tmp.name) / "solution.cif"
    trace = write_prototype_scaffold_cif(cif_path, _request("TiO2", "rutile", "P42/mnm", "tetragonal"))

    assert trace["scaffold_used_for_final_cif"] is False
    assert trace["final_cif_source"] == "generic_fallback"
    assert trace["fallback_reason"] == "unsupported_family"
    assert not cif_path.exists()


def test_final_cif_writer_uses_all_10_supported_scaffolds() -> None:
    with TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        for formula, family, space_group, space_group_number, crystal_system, site_count in SCAFFOLD_CASES:
            cif_path = tmp / f"{formula}.cif"
            trace = write_prototype_scaffold_cif(cif_path, _request(formula, family, space_group, crystal_system))
            symbol, number, analyzed_system = _analyze(Structure.from_file(cif_path))

            assert trace["scaffold_used_for_final_cif"] is True
            assert trace["final_cif_source"] == "prototype_scaffold"
            assert trace["scaffold_formula"] == formula
            assert trace["scaffold_family"] == family
            assert trace["scaffold_space_group"] == space_group
            assert trace["scaffold_space_group_number"] == space_group_number
            assert trace["scaffold_crystal_system"] == crystal_system
            assert trace["scaffold_site_count"] == site_count
            assert trace["scaffold_lattice_parameters"]
            assert trace["scaffold_fractional_coordinates"]
            assert trace["scaffold_source_note"]
            assert (symbol, number, analyzed_system) == (space_group, space_group_number, crystal_system)
