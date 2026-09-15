from pathlib import Path

from sca.evaluators.cif_parse import parse_cif


FIXTURES = Path(__file__).parent / "fixtures"


DUMMY_SPECIES_CIF = """data_dummy
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   5
_cell_length_b   5
_cell_length_c   5
_cell_angle_alpha   90
_cell_angle_beta    90
_cell_angle_gamma   90
_symmetry_Int_Tables_number 1
loop_
 _symmetry_equiv_pos_as_xyz
 'x, y, z'
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 A1 A0+ 0 0 0 1
 O1 O 0.5 0.5 0.5 1
"""


def test_valid_cif_parse_result() -> None:
    structure, result = parse_cif(FIXTURES / "tiny_valid.cif")

    assert structure is not None
    assert result.parse_ok is True
    assert result.reduced_formula == "NaCl"
    assert result.lattice_a is not None


def test_malformed_cif_parse_result() -> None:
    structure, result = parse_cif(FIXTURES / "malformed.cif")

    assert structure is None
    assert result.parse_ok is False
    assert result.error_type is not None


def test_dummy_species_cif_is_invalid_without_crashing(tmp_path: Path) -> None:
    cif = tmp_path / "dummy.cif"
    cif.write_text(DUMMY_SPECIES_CIF, encoding="utf-8")

    structure, result = parse_cif(cif)

    assert structure is None
    assert result.parse_ok is False
    assert result.chemical_species_valid is False
    assert result.invalid_species == ["A0+"]
    assert result.error_type == "InvalidSpeciesError"
    assert "A0+" in (result.error_message or "")
