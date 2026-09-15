from __future__ import annotations

from dataclasses import dataclass

from sok_llm_orchestrator.structures.models import NormalizedStructure


@dataclass(slots=True)
class StructureIdentity:
    structure_id: str
    canonical_signature: str
    space_group: str | None
    formula_units: int


def identity_from_normalized(normalized: NormalizedStructure) -> StructureIdentity:
    return StructureIdentity(
        structure_id=normalized.structure_id,
        canonical_signature=normalized.canonical_signature,
        space_group=normalized.symmetry_after,
        formula_units=normalized.formula_units,
    )


def is_duplicate_identity(left: StructureIdentity, right: StructureIdentity) -> bool:
    return left.canonical_signature == right.canonical_signature
