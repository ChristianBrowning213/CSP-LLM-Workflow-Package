"""Generic ordered-orbit composition preflight.

This module solves only the finite orbit-multiplicity feasibility problem. It
does not invoke the MILP solver and therefore rejects impossible compositions
before model construction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from typing import Any, Iterable

from ase.formula import Formula


VACANCY_STATE = "VACANCY"


@dataclass(frozen=True)
class OccupationPreflight:
    requested_composition: dict[str, int]
    representable_composition: dict[str, int] | None
    orbit_multiplicity_equations: tuple[str, ...]
    stoichiometry_representable: bool
    rejection_reason: str | None
    formula_units: int | None
    vacancy_count: int
    selected_state_by_orbit: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _formula_counts(formula: str) -> dict[str, int]:
    counts = Formula(formula).count()
    integer: dict[str, int] = {}
    for species, value in counts.items():
        rounded = int(round(float(value)))
        if abs(float(value) - rounded) > 1e-9 or rounded <= 0:
            raise ValueError(f"formula contains a non-positive or non-integral count for {species}: {value}")
        integer[str(species)] = rounded
    if not integer:
        raise ValueError("formula contains no species")
    return integer


def _partial_distributions(states: tuple[str, ...], multiplicity: int) -> list[dict[str, int]]:
    distributions: list[dict[str, int]] = []

    def visit(index: int, remaining: int, values: dict[str, int]) -> None:
        if index == len(states) - 1:
            distributions.append({**values, states[index]: remaining})
            return
        for count in range(remaining + 1):
            visit(index + 1, remaining - count, {**values, states[index]: count})

    visit(0, multiplicity, {})
    return distributions


def _orbit_options(orbit: dict[str, Any], target_species: set[str]) -> list[dict[str, int]]:
    multiplicity = len(orbit.get("site_indices", []))
    allowed = tuple(
        str(value) for value in orbit.get("allowed_species", [])
        if str(value) == VACANCY_STATE or str(value) in target_species
    )
    vacancy_allowed = bool(orbit.get("vacancy_allowed", False)) or VACANCY_STATE in allowed
    if vacancy_allowed and VACANCY_STATE not in allowed:
        allowed = (*allowed, VACANCY_STATE)
    fixed = orbit.get("fixed_species")
    required_state = str(orbit.get("required_state", "AUTO")).upper()
    if fixed:
        fixed = str(fixed)
        return [{fixed: multiplicity}] if fixed in allowed else []
    if required_state == "EMPTY":
        return [{VACANCY_STATE: multiplicity}] if vacancy_allowed else []
    if required_state == "FULL" or bool(orbit.get("required_occupancy", True)):
        allowed = tuple(value for value in allowed if value != VACANCY_STATE)
    if not allowed:
        return []
    if bool(orbit.get("allow_partial_occupation", False)):
        return _partial_distributions(allowed, multiplicity)
    return [{state: multiplicity} for state in allowed]


def preflight_ordered_occupation(
    formula: str,
    site_count: int,
    ordered_orbits: Iterable[dict[str, Any]],
    *,
    vacancy_count: int = 0,
) -> OccupationPreflight:
    """Determine whether orbit multiplicities can express the exact formula."""

    base_counts = _formula_counts(formula)
    if site_count <= 0:
        raise ValueError("site_count must be positive")
    if vacancy_count < 0 or vacancy_count > site_count:
        raise ValueError("vacancy_count must be between zero and site_count")
    occupied_sites = site_count - vacancy_count
    base_total = sum(base_counts.values())
    if occupied_sites % base_total:
        return OccupationPreflight(
            requested_composition=base_counts,
            representable_composition=None,
            orbit_multiplicity_equations=(),
            stoichiometry_representable=False,
            rejection_reason="candidate-site count minus vacancies is not an integer multiple of the requested formula",
            formula_units=None,
            vacancy_count=vacancy_count,
            selected_state_by_orbit=None,
        )
    formula_units = occupied_sites // base_total
    requested = {species: count * formula_units for species, count in base_counts.items()}
    requested[VACANCY_STATE] = vacancy_count
    orbits = [dict(orbit) for orbit in ordered_orbits]
    claimed = [int(index) for orbit in orbits for index in orbit.get("site_indices", [])]
    if sorted(claimed) != list(range(site_count)):
        return OccupationPreflight(
            requested_composition=requested,
            representable_composition=None,
            orbit_multiplicity_equations=(),
            stoichiometry_representable=False,
            rejection_reason="ordered orbits do not form an exact partition of candidate sites",
            formula_units=formula_units,
            vacancy_count=vacancy_count,
            selected_state_by_orbit=None,
        )
    equations = tuple(
        f"{orbit.get('orbit_id', f'orbit_{index}')}[m={len(orbit.get('site_indices', []))}] -> "
        f"{','.join(str(value) for value in orbit.get('allowed_species', []))}"
        for index, orbit in enumerate(orbits)
    )
    species_order = tuple(sorted(requested))
    target_vector = tuple(requested[species] for species in species_order)
    states: dict[tuple[int, ...], dict[str, Any]] = {tuple(0 for _ in species_order): {}}
    for index, orbit in enumerate(orbits):
        orbit_id = str(orbit.get("orbit_id", f"orbit_{index}"))
        options = _orbit_options(orbit, set(base_counts))
        if not options:
            return OccupationPreflight(
                requested_composition=requested,
                representable_composition=None,
                orbit_multiplicity_equations=equations,
                stoichiometry_representable=False,
                rejection_reason=f"orbit {orbit_id} has no allowed state compatible with the requested composition",
                formula_units=formula_units,
                vacancy_count=vacancy_count,
                selected_state_by_orbit=None,
            )
        next_states: dict[tuple[int, ...], dict[str, Any]] = {}
        for current, witness in states.items():
            for option in options:
                candidate = tuple(current[i] + option.get(species, 0) for i, species in enumerate(species_order))
                if any(candidate[i] > target_vector[i] for i in range(len(species_order))):
                    continue
                next_states.setdefault(candidate, {**witness, orbit_id: option})
        states = next_states
        if not states:
            break
    witness = states.get(target_vector)
    if witness is None:
        return OccupationPreflight(
            requested_composition=requested,
            representable_composition=None,
            orbit_multiplicity_equations=equations,
            stoichiometry_representable=False,
            rejection_reason="orbit multiplicities and allowlists cannot satisfy the exact requested composition",
            formula_units=formula_units,
            vacancy_count=vacancy_count,
            selected_state_by_orbit=None,
        )
    represented = {species: 0 for species in species_order}
    for option in witness.values():
        for species, count in option.items():
            represented[species] += int(count)
    return OccupationPreflight(
        requested_composition=requested,
        representable_composition=represented,
        orbit_multiplicity_equations=equations,
        stoichiometry_representable=True,
        rejection_reason=None,
        formula_units=formula_units,
        vacancy_count=vacancy_count,
        selected_state_by_orbit=witness,
    )
