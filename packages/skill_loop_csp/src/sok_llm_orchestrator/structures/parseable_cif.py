from __future__ import annotations

from pathlib import Path


_BASE_FRACTIONAL_COORDS: tuple[tuple[float, float, float], ...] = (
    (0.0, 0.0, 0.0),
    (0.25, 0.25, 0.25),
    (0.5, 0.5, 0.0),
    (0.75, 0.75, 0.25),
    (0.5, 0.0, 0.5),
    (0.0, 0.5, 0.5),
    (0.25, 0.75, 0.75),
    (0.75, 0.25, 0.75),
)


def _fallback_formula(formula: str | None) -> str:
    text = str(formula or "").strip()
    return text if text else "Si"


def _species_for_formula(formula: str) -> list[str]:
    from pymatgen.core import Composition

    try:
        composition = Composition(formula).reduced_composition
    except Exception:
        composition = Composition("Si")
    species: list[str] = []
    for element, amount in composition.get_el_amt_dict().items():
        count = max(1, int(round(float(amount))))
        species.extend([str(element)] * count)
    return species or ["Si"]


def _fractional_coord(index: int) -> tuple[float, float, float]:
    if index < len(_BASE_FRACTIONAL_COORDS):
        return _BASE_FRACTIONAL_COORDS[index]
    slot = index + 1
    return (
        (slot * 0.173) % 1.0,
        (slot * 0.347) % 1.0,
        (slot * 0.521) % 1.0,
    )


def build_parseable_structure(
    formula: str | None,
    *,
    lattice_a: float,
):
    from pymatgen.core import Lattice, Structure

    safe_formula = _fallback_formula(formula)
    species = _species_for_formula(safe_formula)
    coords = [_fractional_coord(index) for index in range(len(species))]
    return Structure(Lattice.cubic(float(lattice_a)), species, coords)


def write_parseable_cif(
    path: str | Path,
    *,
    formula: str | None,
    lattice_a: float,
) -> None:
    from pymatgen.io.cif import CifWriter

    structure = build_parseable_structure(formula, lattice_a=float(lattice_a))
    writer = CifWriter(structure)
    writer.write_file(str(Path(path)))


__all__ = ["build_parseable_structure", "write_parseable_cif"]
