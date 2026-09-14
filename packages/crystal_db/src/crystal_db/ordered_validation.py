"""Deterministic validation for fully ordered crystallographic structures."""

from __future__ import annotations

from typing import Any

from pymatgen.core import Structure
from pymatgen.core.periodic_table import DummySpecies, Element, Species


ORDERED_OCCUPANCY_TOLERANCE = 1e-8


def is_fully_ordered_structure(
    structure: Structure,
    *,
    occupancy_tolerance: float = ORDERED_OCCUPANCY_TOLERANCE,
) -> dict[str, Any]:
    """Return auditable evidence that every site has one species at occupancy one."""
    offending_sites: list[dict[str, Any]] = []
    for index, site in enumerate(structure):
        try:
            species_items = list(site.species.items())
        except (AttributeError, TypeError, ValueError) as exc:
            offending_sites.append(
                {
                    "site_index": index,
                    "reason": "UNRESOLVED_OCCUPANCY",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if len(species_items) != 1:
            offending_sites.append(
                {
                    "site_index": index,
                    "reason": "MIXED_SPECIES_SITE",
                    "species_count": len(species_items),
                    "species": [str(species) for species, _ in species_items],
                    "occupancies": [float(occupancy) for _, occupancy in species_items],
                }
            )
            continue
        species, occupancy = species_items[0]
        if isinstance(species, DummySpecies):
            offending_sites.append(
                {
                    "site_index": index,
                    "reason": "DUMMY_SPECIES",
                    "species": str(species),
                    "occupancy": float(occupancy),
                }
            )
            continue
        if not isinstance(species, (Element, Species)):
            offending_sites.append(
                {
                    "site_index": index,
                    "reason": "INVALID_SPECIES",
                    "species": str(species),
                    "occupancy": float(occupancy),
                }
            )
            continue
        try:
            occupancy_value = float(occupancy)
        except (TypeError, ValueError):
            offending_sites.append(
                {
                    "site_index": index,
                    "reason": "UNRESOLVED_OCCUPANCY",
                    "species": str(species),
                    "occupancy": str(occupancy),
                }
            )
            continue
        if abs(occupancy_value - 1.0) > occupancy_tolerance:
            offending_sites.append(
                {
                    "site_index": index,
                    "reason": "PARTIAL_OCCUPANCY",
                    "species": str(species),
                    "occupancy": occupancy_value,
                }
            )

    reasons = sorted({str(item["reason"]) for item in offending_sites})
    return {
        "ordered": not offending_sites,
        "reason": "FULLY_ORDERED" if not offending_sites else ";".join(reasons),
        "offending_sites": offending_sites,
        "site_count": len(structure),
        "occupancy_tolerance": occupancy_tolerance,
    }
