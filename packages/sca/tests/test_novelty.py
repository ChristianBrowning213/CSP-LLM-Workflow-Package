from pathlib import Path

from sca.evaluators.cif_parse import parse_cif
from sca.evaluators.novelty import evaluate_novelty, load_reference_structures


FIXTURES = Path(__file__).parent / "fixtures"


def test_novelty_finds_known_match_in_reference_folder(tmp_path: Path) -> None:
    reference = tmp_path / "reference.cif"
    reference.write_text((FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    references = load_reference_structures(reference_folder=tmp_path)
    structure, _ = parse_cif(FIXTURES / "tiny_valid_copy.cif")

    result = evaluate_novelty(structure, references)

    assert result.novelty_checked is True
    assert result.known_match is True
    assert result.novel_by_structure_matcher is False
