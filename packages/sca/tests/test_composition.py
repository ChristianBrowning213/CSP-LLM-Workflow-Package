from pathlib import Path

from sca.evaluators.cif_parse import parse_cif
from sca.evaluators.composition import evaluate_composition


FIXTURES = Path(__file__).parent / "fixtures"


def test_composition_target_match_equivalent_reduced_formula() -> None:
    structure, _ = parse_cif(FIXTURES / "tiny_valid.cif")

    result = evaluate_composition(structure, "Na2Cl2")

    assert result.target_reduced_formula == "NaCl"
    assert result.target_formula_match is True


def test_composition_mismatch_detected() -> None:
    structure, _ = parse_cif(FIXTURES / "tiny_valid.cif")

    result = evaluate_composition(structure, "LiCl")

    assert result.target_formula_match is False
