"""Generated-to-relaxed structural change analysis with periodic atom assignment."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from pymatgen.core import Structure
from scipy.optimize import linear_sum_assignment


class StructureTransitionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    initial_cif_path: str
    final_cif_path: str
    composition_consistent: bool
    site_count_consistent: bool
    mapping_succeeded: bool
    atomic_rms_displacement_A: float | None = None
    atomic_max_displacement_A: float | None = None
    lattice_a_change_pct: float | None = None
    lattice_b_change_pct: float | None = None
    lattice_c_change_pct: float | None = None
    max_lattice_angle_change_deg: float | None = None
    volume_change_pct: float | None = None
    assignment: list[int] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


def analyse_structure_transition(
    initial: str | Path | Structure,
    final: str | Path | Structure,
) -> StructureTransitionResult:
    initial_structure, initial_path = _load(initial, "<initial-structure>")
    final_structure, final_path = _load(final, "<final-structure>")
    composition_consistent = initial_structure.composition.reduced_composition == final_structure.composition.reduced_composition
    site_count_consistent = len(initial_structure) == len(final_structure)
    base = {
        "initial_cif_path": initial_path,
        "final_cif_path": final_path,
        "composition_consistent": composition_consistent,
        "site_count_consistent": site_count_consistent,
        "lattice_a_change_pct": _pct(initial_structure.lattice.a, final_structure.lattice.a),
        "lattice_b_change_pct": _pct(initial_structure.lattice.b, final_structure.lattice.b),
        "lattice_c_change_pct": _pct(initial_structure.lattice.c, final_structure.lattice.c),
        "max_lattice_angle_change_deg": max(
            abs(a - b)
            for a, b in zip(initial_structure.lattice.angles, final_structure.lattice.angles, strict=True)
        ),
        "volume_change_pct": _pct(initial_structure.volume, final_structure.volume),
    }
    if not composition_consistent or not site_count_consistent:
        reasons = []
        if not composition_consistent:
            reasons.append("composition differs")
        if not site_count_consistent:
            reasons.append("site count differs")
        return StructureTransitionResult(status="MAPPING_FAILED", mapping_succeeded=False, reasons=reasons, **base)
    try:
        assignment = _species_periodic_assignment(initial_structure, final_structure)
        distances = []
        for initial_index, final_index in enumerate(assignment):
            delta = final_structure[final_index].frac_coords - initial_structure[initial_index].frac_coords
            delta -= np.round(delta)
            average_lattice = (initial_structure.lattice.matrix + final_structure.lattice.matrix) / 2.0
            distances.append(float(np.linalg.norm(delta @ average_lattice)))
        return StructureTransitionResult(
            status="COMPUTED",
            mapping_succeeded=True,
            atomic_rms_displacement_A=float(np.sqrt(np.mean(np.square(distances)))) if distances else 0.0,
            atomic_max_displacement_A=max(distances, default=0.0),
            assignment=assignment,
            **base,
        )
    except Exception as exc:
        return StructureTransitionResult(
            status="MAPPING_FAILED",
            mapping_succeeded=False,
            reasons=[f"{type(exc).__name__}: {exc}"],
            **base,
        )


def _species_periodic_assignment(initial: Structure, final: Structure) -> list[int]:
    assignment = [-1] * len(initial)
    symbols = sorted({site.specie.symbol for site in initial})
    for symbol in symbols:
        left = [index for index, site in enumerate(initial) if site.specie.symbol == symbol]
        right = [index for index, site in enumerate(final) if site.specie.symbol == symbol]
        if len(left) != len(right):
            raise ValueError(f"species count differs for {symbol}")
        cost = initial.lattice.get_all_distances(
            np.array([initial[index].frac_coords for index in left]),
            np.array([final[index].frac_coords for index in right]),
        )
        row_indices, column_indices = linear_sum_assignment(cost)
        for row_index, column_index in zip(row_indices, column_indices, strict=True):
            assignment[left[int(row_index)]] = right[int(column_index)]
    if any(index < 0 for index in assignment):
        raise ValueError("incomplete periodic assignment")
    return assignment


def _load(value: str | Path | Structure, fallback: str) -> tuple[Structure, str]:
    if isinstance(value, Structure):
        return value, fallback
    path = Path(value)
    return Structure.from_file(path), str(path)


def _pct(before: float, after: float) -> float | None:
    return (float(after) - float(before)) / float(before) * 100.0 if before else None

