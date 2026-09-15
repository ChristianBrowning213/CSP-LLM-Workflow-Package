"""Bond/contact reasonableness checks."""

from __future__ import annotations

from pymatgen.core import Element, Structure

from sca.schemas import BondResult


FALLBACK_RADII = {
    "H": 0.31,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "Na": 1.66,
    "Mg": 1.41,
    "Al": 1.21,
    "Si": 1.11,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "K": 2.03,
    "Ca": 1.76,
}


def evaluate_bonds(
    structure: Structure,
    tolerance_low: float = 0.7,
    tolerance_high: float = 1.3,
    absolute_min_non_h: float = 0.6,
    absolute_min_h: float = 0.35,
) -> BondResult:
    try:
        if len(structure) < 2:
            return BondResult(
                bond_reasonableness_score=1.0,
                bond_lengths_reasonable=True,
                num_bad_contacts=0,
            )

        max_radius = max(_radius(str(site.specie)) for site in structure)
        cutoff = max(absolute_min_non_h, tolerance_high * max_radius * 2)
        neighbors = structure.get_all_neighbors(cutoff, include_index=True)
        min_distance: float | None = None
        min_pair: str | None = None
        bad_contacts: list[str] = []
        seen: set[tuple[int, int, float]] = set()

        for i, site_neighbors in enumerate(neighbors):
            elem_i = str(structure[i].specie)
            for neighbor in site_neighbors:
                j = int(neighbor.index)
                distance = float(neighbor.nn_distance)
                key = (min(i, j), max(i, j), round(distance, 5))
                if i == j or key in seen:
                    continue
                seen.add(key)
                elem_j = str(structure[j].specie)
                pair = f"{elem_i}-{elem_j}"
                if min_distance is None or distance < min_distance:
                    min_distance = distance
                    min_pair = pair
                absolute_min = absolute_min_h if "H" in (elem_i, elem_j) else absolute_min_non_h
                radius_sum = _radius(elem_i) + _radius(elem_j)
                if distance < absolute_min or distance < tolerance_low * radius_sum:
                    bad_contacts.append(f"{pair}:{distance:.3f}")

        num_bad = len(bad_contacts)
        score = 1.0 / (1.0 + num_bad)
        return BondResult(
            bond_reasonableness_score=score,
            bond_lengths_reasonable=num_bad == 0,
            min_distance=min_distance,
            min_distance_pair=min_pair,
            num_bad_contacts=num_bad,
            bad_contact_pairs=bad_contacts[:50],
        )
    except Exception as exc:
        return BondResult(
            bond_reasonableness_score=None,
            bond_lengths_reasonable=None,
            bond_error=f"{type(exc).__name__}: {exc}",
        )


def _radius(symbol: str) -> float:
    try:
        radius = Element(symbol).covalent_radius
        if radius is not None:
            return float(radius)
    except Exception:
        pass
    return FALLBACK_RADII.get(symbol, 1.0)
