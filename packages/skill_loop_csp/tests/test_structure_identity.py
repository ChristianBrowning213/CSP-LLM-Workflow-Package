from __future__ import annotations

from sok_llm_orchestrator.structures.identity import identity_from_normalized, is_duplicate_identity
from sok_llm_orchestrator.structures.models import StructureInput
from sok_llm_orchestrator.structures.normalize import normalize_structure


def test_identity_duplicate_detection() -> None:
    a = StructureInput(
        structure_id="s1",
        lattice=(3.0, 3.0, 3.0, 90.0, 90.0, 90.0),
        species=["A"],
        frac_coords=[(0.0, 0.0, 0.0)],
    )
    b = StructureInput(
        structure_id="s2",
        lattice=(3.0, 3.0, 3.0, 90.0, 90.0, 90.0),
        species=["A"],
        frac_coords=[(0.0, 0.0, 0.0)],
    )
    ia = identity_from_normalized(normalize_structure(a))
    ib = identity_from_normalized(normalize_structure(b))
    assert is_duplicate_identity(ia, ib) is True
