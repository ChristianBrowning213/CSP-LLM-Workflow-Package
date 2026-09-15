from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StructureInput:
    structure_id: str
    lattice: tuple[float, float, float, float, float, float]
    species: list[str]
    frac_coords: list[tuple[float, float, float]]
    space_group: str | None = None


@dataclass(slots=True)
class NormalizedStructure:
    structure_id: str
    raw: StructureInput
    primitive: StructureInput
    conventional: StructureInput
    canonical_signature: str
    formula_units: int
    volume_per_fu: float
    symmetry_before: str | None
    symmetry_after: str | None
