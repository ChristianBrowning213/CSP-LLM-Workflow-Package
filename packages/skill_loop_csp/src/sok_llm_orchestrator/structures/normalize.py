from __future__ import annotations

import hashlib
import json
import math
from collections import Counter

from sok_llm_orchestrator.structures.models import NormalizedStructure, StructureInput


def _round_tuple(values: tuple[float, float, float], tol: float) -> tuple[float, float, float]:
    digits = max(0, min(9, int(round(-math.log10(max(tol, 1e-9))))))
    return (round(values[0], digits), round(values[1], digits), round(values[2], digits))


def _canonical_atoms(species: list[str], coords: list[tuple[float, float, float]], tol: float) -> list[tuple[str, tuple[float, float, float]]]:
    atoms: list[tuple[str, tuple[float, float, float]]] = []
    for specie, xyz in zip(species, coords, strict=True):
        wrapped = tuple(v % 1.0 for v in xyz)
        atoms.append((specie, _round_tuple((wrapped[0], wrapped[1], wrapped[2]), tol)))
    atoms.sort(key=lambda item: (item[0], item[1][0], item[1][1], item[1][2]))
    return atoms


def _simple_volume(lattice: tuple[float, float, float, float, float, float]) -> float:
    # Deterministic approximation for stub benchmarks: axis product only.
    return lattice[0] * lattice[1] * lattice[2]


def _formula_units(species: list[str]) -> int:
    counts = Counter(species)
    if not counts:
        return 1
    values = sorted(counts.values())
    smallest = values[0]
    return max(1, smallest)


def normalize_structure(raw: StructureInput, tol: float = 1e-3) -> NormalizedStructure:
    atoms = _canonical_atoms(raw.species, raw.frac_coords, tol=tol)
    canonical_payload = {
        "species_coords": atoms,
        "lattice": [round(x, 6) for x in raw.lattice],
        "space_group": (raw.space_group or "").upper(),
    }
    signature = hashlib.sha256(json.dumps(canonical_payload, sort_keys=True).encode("utf-8")).hexdigest()

    primitive = StructureInput(
        structure_id=f"{raw.structure_id}:primitive",
        lattice=raw.lattice,
        species=[x[0] for x in atoms],
        frac_coords=[x[1] for x in atoms],
        space_group=raw.space_group,
    )
    conventional = StructureInput(
        structure_id=f"{raw.structure_id}:conventional",
        lattice=raw.lattice,
        species=[x[0] for x in atoms],
        frac_coords=[x[1] for x in atoms],
        space_group=raw.space_group,
    )
    fu = _formula_units(raw.species)
    volume = _simple_volume(raw.lattice)
    return NormalizedStructure(
        structure_id=raw.structure_id,
        raw=raw,
        primitive=primitive,
        conventional=conventional,
        canonical_signature=signature,
        formula_units=fu,
        volume_per_fu=volume / fu if fu else volume,
        symmetry_before=raw.space_group,
        symmetry_after=raw.space_group,
    )
