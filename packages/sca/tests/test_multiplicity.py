from pathlib import Path

from sca.evaluators.cif_parse import parse_cif
from sca.evaluators.multiplicity import evaluate_multiplicity


FIXTURES = Path(__file__).parent / "fixtures"


def test_multiplicity_missing_field_does_not_fail() -> None:
    path = FIXTURES / "tiny_valid.cif"
    structure, _ = parse_cif(path)

    result = evaluate_multiplicity(structure, path.read_text(encoding="utf-8"))

    assert result.multiplicity_checked is False
    assert result.multiplicity_consistent is None


def test_multiplicity_detects_explicit_inconsistency() -> None:
    path = FIXTURES / "multiplicity_bad.cif"
    structure, _ = parse_cif(path)

    result = evaluate_multiplicity(structure, path.read_text(encoding="utf-8"))

    assert result.multiplicity_checked is True
    assert result.multiplicity_consistent is False
