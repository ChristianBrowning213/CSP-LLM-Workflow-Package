from __future__ import annotations

from typing import Any

from qlip.analysis.spacegroup import detect_spacegroup_dataset

def detect_spacegroup(atoms, *, symprec: float = 1.0e-2, angle_tolerance: float = 5.0) -> dict[str, Any]:
    dataset = detect_spacegroup_dataset(
        atoms.get_cell().array,
        atoms.get_scaled_positions(wrap=True),
        atoms.get_chemical_symbols(),
        symprec=float(symprec),
        angle_tolerance=float(angle_tolerance),
    )
    return {
        "sg_number": dataset.get("number"),
        "sg_symbol": dataset.get("international"),
        "sg_hall": dataset.get("hall"),
        "symprec": float(symprec),
        "angle_tolerance": float(angle_tolerance),
        "reason": dataset.get("reason"),
        "dataset": dataset,
    }
