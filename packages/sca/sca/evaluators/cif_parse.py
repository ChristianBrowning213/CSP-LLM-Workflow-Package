"""CIF parsing evaluator."""

from __future__ import annotations

from pathlib import Path

from pymatgen.core import Structure
from pymatgen.core.periodic_table import DummySpecies

from sca.schemas import CifParseResult


def parse_cif(path: str | Path) -> tuple[Structure | None, CifParseResult]:
    """Parse a CIF file with pymatgen and return structured metadata."""

    try:
        structure = Structure.from_file(str(path))
    except Exception as exc:
        return None, CifParseResult(
            parse_ok=False,
            chemical_species_valid=None,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    lattice = structure.lattice
    species = [str(site.specie) for site in structure]
    invalid_species = sorted(
        {str(element) for element in structure.composition.elements if isinstance(element, DummySpecies)}
    )
    if invalid_species:
        return None, CifParseResult(
            parse_ok=False,
            chemical_species_valid=False,
            species=species,
            invalid_species=invalid_species,
            n_sites=len(structure),
            volume=float(structure.volume),
            lattice_a=float(lattice.a),
            lattice_b=float(lattice.b),
            lattice_c=float(lattice.c),
            lattice_alpha=float(lattice.alpha),
            lattice_beta=float(lattice.beta),
            lattice_gamma=float(lattice.gamma),
            error_type="InvalidSpeciesError",
            error_message=f"Invalid or dummy species in CIF: {', '.join(invalid_species)}",
        )

    try:
        density = float(structure.density)
        density_error = None
    except Exception as exc:
        density = None
        density_error = f"{type(exc).__name__}: {exc}"

    return structure, CifParseResult(
        parse_ok=density_error is None,
        chemical_species_valid=True,
        species=species,
        formula=structure.composition.formula,
        reduced_formula=structure.composition.reduced_formula,
        n_sites=len(structure),
        volume=float(structure.volume),
        density=density,
        density_error=density_error,
        lattice_a=float(lattice.a),
        lattice_b=float(lattice.b),
        lattice_c=float(lattice.c),
        lattice_alpha=float(lattice.alpha),
        lattice_beta=float(lattice.beta),
        lattice_gamma=float(lattice.gamma),
        error_type="DensityError" if density_error else None,
        error_message=density_error,
    )
