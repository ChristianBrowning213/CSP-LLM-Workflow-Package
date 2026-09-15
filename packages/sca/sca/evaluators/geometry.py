"""Basic geometry checks."""

from __future__ import annotations

from pymatgen.core import Structure

from sca.schemas import GeometryResult


def evaluate_geometry(structure: Structure) -> GeometryResult:
    warnings: list[str] = []
    errors: list[str] = []
    volume = float(structure.volume)
    density_error = None
    try:
        density = float(structure.density)
    except Exception as exc:
        density = None
        density_error = f"{type(exc).__name__}: {exc}"
        errors.append(f"density unavailable: {density_error}")
    volume_per_atom = volume / len(structure) if len(structure) else None
    lattice = structure.lattice

    if volume_per_atom is not None and volume_per_atom < 3:
        warnings.append("volume_per_atom below 3 A^3")
    if volume_per_atom is not None and volume_per_atom > 120:
        warnings.append("volume_per_atom above 120 A^3")
    if density is not None and density <= 0:
        errors.append("density <= 0")
    if density is not None and density > 30:
        warnings.append("density above 30 g/cm^3")
    if any(length <= 0 for length in (lattice.a, lattice.b, lattice.c)):
        errors.append("lattice length <= 0")
    if any(angle <= 0 or angle >= 180 for angle in (lattice.alpha, lattice.beta, lattice.gamma)):
        errors.append("lattice angle outside (0, 180)")

    geometry_ok = not errors
    return GeometryResult(
        geometry_ok=geometry_ok,
        volume=volume,
        volume_per_atom=volume_per_atom,
        density=density,
        density_error=density_error,
        geometry_warning_count=len(warnings),
        geometry_warnings=warnings,
        geometry_error="; ".join(errors) if errors else None,
    )
