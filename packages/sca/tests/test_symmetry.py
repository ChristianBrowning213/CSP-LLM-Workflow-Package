from pathlib import Path

from sca.evaluators.cif_parse import parse_cif
from sca.evaluators.symmetry import evaluate_symmetry


FIXTURES = Path(__file__).parent / "fixtures"


def test_symmetry_detects_simple_space_group() -> None:
    path = FIXTURES / "tiny_valid.cif"
    structure, _ = parse_cif(path)

    result = evaluate_symmetry(structure, path.read_text(encoding="utf-8"), "1")

    assert result.detected_space_group is not None
    assert result.detected_space_group_number is not None
    assert result.symprec_used is not None
