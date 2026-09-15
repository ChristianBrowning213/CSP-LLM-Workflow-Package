from __future__ import annotations

from sok_llm_orchestrator.structures.models import StructureInput
from sok_llm_orchestrator.structures.normalize import normalize_structure


def test_normalization_equivalent_order_same_signature() -> None:
    a = StructureInput(
        structure_id="a",
        lattice=(4.0, 4.0, 4.0, 90.0, 90.0, 90.0),
        species=["Ti", "O", "O"],
        frac_coords=[(0.0, 0.0, 0.0), (0.5, 0.5, 0.5), (0.25, 0.25, 0.25)],
        space_group="P1",
    )
    b = StructureInput(
        structure_id="b",
        lattice=(4.0, 4.0, 4.0, 90.0, 90.0, 90.0),
        species=["O", "Ti", "O"],
        frac_coords=[(0.25, 0.25, 0.25), (0.0, 0.0, 0.0), (0.5, 0.5, 0.5)],
        space_group="P1",
    )
    na = normalize_structure(a)
    nb = normalize_structure(b)
    assert na.canonical_signature == nb.canonical_signature
