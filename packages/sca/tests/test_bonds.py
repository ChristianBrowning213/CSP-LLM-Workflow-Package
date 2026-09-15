from pathlib import Path

from sca.evaluators.bonds import evaluate_bonds
from sca.evaluators.cif_parse import parse_cif


FIXTURES = Path(__file__).parent / "fixtures"


def test_bond_evaluator_detects_short_contact() -> None:
    structure, _ = parse_cif(FIXTURES / "short_contact.cif")

    result = evaluate_bonds(structure)

    assert result.bond_lengths_reasonable is False
    assert result.num_bad_contacts > 0
    assert result.min_distance is not None
