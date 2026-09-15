from __future__ import annotations

from pathlib import Path

from pymatgen.core import Lattice, Structure

from sok_llm_orchestrator.verification.nasicon_topology import validate_nasicon_topology


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE = REPO_ROOT / "data" / "nasicon" / "reference" / "reference.cif"


def test_selected_ordered_nasicon_reference_passes_or_is_explained_partial():
    result = validate_nasicon_topology(REFERENCE)
    assert result["topology_status"] in {"PASS", "PARTIAL"}
    assert result["formula_correct"] is True
    assert result["zr_o6_fraction"] == 1.0
    assert result["si_o4_fraction"] == 1.0
    assert result["p_o4_fraction"] == 1.0
    assert result["framework_dimensionality"] == 3


def test_deliberately_broken_nasicon_coordination_fails():
    structure = Structure.from_file(REFERENCE)
    oxygen_index = next(idx for idx, site in enumerate(structure) if site.specie.symbol == "O")
    structure.translate_sites([oxygen_index], [0.25, 0.25, 0.25], frac_coords=True, to_unit_cell=True)
    result = validate_nasicon_topology(structure)
    assert result["topology_status"] != "PASS"
    assert min(result["zr_o6_fraction"], result["si_o4_fraction"], result["p_o4_fraction"]) < 1.0


def test_composition_correct_but_disconnected_structure_fails():
    symbols = ["Na"] * 3 + ["Zr"] * 2 + ["Si"] * 2 + ["P"] + ["O"] * 12
    coords = [[(idx % 5) / 5, ((idx // 5) % 4) / 4, (idx // 20) / 2] for idx in range(len(symbols))]
    wrong = Structure(Lattice.cubic(40.0), symbols, coords)
    result = validate_nasicon_topology(wrong)
    assert result["formula_correct"] is True
    assert result["topology_status"] == "FAIL"
    assert result["framework_dimensionality"] < 3
