from pathlib import Path

from sca.evaluators.cif_parse import parse_cif
from sca.evaluators.geometry import evaluate_geometry


FIXTURES = Path(__file__).parent / "fixtures"


def test_geometry_computes_volume_per_atom_and_density() -> None:
    structure, _ = parse_cif(FIXTURES / "tiny_valid.cif")

    result = evaluate_geometry(structure)

    assert result.volume_per_atom is not None
    assert result.density is not None
    assert result.geometry_ok is True
