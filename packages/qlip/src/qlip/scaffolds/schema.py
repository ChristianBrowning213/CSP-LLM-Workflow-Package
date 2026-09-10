"""Schema objects for immutable, versioned crystal scaffolds."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ScaffoldValidation:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScaffoldRecord:
    scaffold_id: str
    scaffold_version: str
    family: str
    source_structure_id: str
    source_cif_path: str
    source_cif_sha256: str
    source_formula: str
    source_space_group: str
    lattice: dict[str, float]
    fractional_candidate_sites: tuple[tuple[float, float, float], ...]
    symmetry_orbits: tuple[dict[str, Any], ...]
    orbit_multiplicities: dict[str, int]
    orbit_coordination_roles: dict[str, str]
    fixed_species_allowlist: dict[str, tuple[str, ...]]
    variable_species_allowlist: dict[str, tuple[str, ...]]
    vacancy_allowed_by_orbit: dict[str, bool]
    topology_policy: str
    provenance: dict[str, Any]
    validation_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
