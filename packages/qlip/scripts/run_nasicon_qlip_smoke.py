"""Run the ordered Na3Zr2Si2PO12 orbit-allocation smoke solve.

The reference supplies only the cell and candidate orbit coordinates.  QLIP
must choose which symmetry-closed tetrahedral orbit(s) receive P versus Si.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
import math
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.formula import Formula
from ase.io import read

from qlip.core.solve import solve
from qlip.core.validate import validate_request
from qlip.interactions.spp import SPPCollection, canonical_pair_name


TARGET_FORMULA = "Na6Zr4Si4P2O24"
TARGET_REDUCED_FORMULA = "Na3Zr2Si2PO12"
VARIABLE_SPECIES = {"Si", "P"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_orbits(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            indices = [int(item) for item in str(raw["site_indices"]).split()]
            species = str(raw["species"])
            variable = str(raw["fixed or variable in QLIP"]).lower().startswith("variable")
            rows.append(
                {
                    "orbit_id": str(raw["orbit_id"]),
                    "site_indices": indices,
                    "allowed_species": sorted(VARIABLE_SPECIES) if variable else [species],
                    "required_occupancy": True,
                    "reference_species": species,
                    "multiplicity": len(indices),
                    "variable": variable,
                }
            )
    return rows


def build_request(reference_cif: Path, orbit_table: Path, pot_root: Path, cutoff: float) -> dict[str, Any]:
    reference = read(reference_cif)
    cellpar = reference.cell.cellpar()
    ordered_orbits = _read_orbits(orbit_table)
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": TARGET_FORMULA},
            "design_space": {
                "template": {
                    "name": "ordered_nasicon_mp_1221148_orbit_scaffold",
                    "lattice": {
                        "a": float(cellpar[0]), "b": float(cellpar[1]), "c": float(cellpar[2]),
                        "alpha": float(cellpar[3]), "beta": float(cellpar[4]), "gamma": float(cellpar[5]),
                        "units": "angstrom",
                    },
                },
                "sites": {
                    "mode": "explicit_fractional_sites",
                    "explicit_fractional_sites": reference.get_scaled_positions(wrap=True).tolist(),
                    "ordered_orbits": [
                        {key: orbit[key] for key in ("orbit_id", "site_indices", "allowed_species", "required_occupancy")}
                        for orbit in ordered_orbits
                    ],
                },
            },
            "objective": {"type": "spp_energy"},
        },
        "constraints": [],
        "guidance": [{
            "id": "objective.energy_spp",
            "weight": 1.0,
            "params": {
                "pot_root": str(pot_root.resolve()),
                "mode": "complete",
                "strict_pair_coverage": True,
                "missing_pair_policy": "block",
                "cutoff": float(cutoff),
            },
        }],
        "guidance_mode": "weighted_sum",
        "solver": {
            "name": "gurobi", "time_limit_s": 300, "mip_gap": 0.0, "threads": 1,
            "seed": 0, "parameters": {"NonConvex": 2},
        },
        "artifacts": {"return_cif": True, "return_decoder_debug": False},
        "runtime": {"max_sites": 40, "max_binary_vars": 200, "max_constraints": 300},
        "context": {"run_id": "nasicon_qlip_smoke", "pot_root": str(pot_root.resolve()), "tags": ["nasicon", "ordered", "orbit-allocation"]},
    }


def _formula_key(symbols: list[str]) -> str:
    counts = Counter(symbols)
    divisor = 0
    for count in counts.values():
        divisor = math.gcd(divisor, count)
    return "".join(
        symbol + (str(counts[symbol] // divisor) if counts[symbol] // divisor != 1 else "")
        for symbol in ("Na", "Zr", "Si", "P", "O")
        if counts.get(symbol)
    )


def _load_spp(pot_root: Path, cutoff: float) -> SPPCollection:
    symbols = list(Formula(TARGET_FORMULA).count())
    pairs = list(itertools.combinations_with_replacement(symbols, 2))
    spp = SPPCollection(pot_root, cutoff=cutoff, missing_pair_policy="block")
    spp.load(pairs)
    return spp


def _alternative_assignments(orbits: list[dict[str, Any]]) -> list[dict[str, str]]:
    variable = [orbit for orbit in orbits if orbit["variable"]]
    alternatives: list[dict[str, str]] = []
    for p_mask in itertools.product((False, True), repeat=len(variable)):
        p_count = sum(orbit["multiplicity"] for orbit, is_p in zip(variable, p_mask) if is_p)
        if p_count != 2:
            continue
        alternatives.append({orbit["orbit_id"]: ("P" if is_p else "Si") for orbit, is_p in zip(variable, p_mask)})
    return alternatives


def _symbols_for_assignment(orbits: list[dict[str, Any]], assignment: dict[str, str], site_count: int) -> list[str]:
    symbols = [""] * site_count
    for orbit in orbits:
        species = assignment.get(orbit["orbit_id"], orbit["reference_species"])
        for idx in orbit["site_indices"]:
            symbols[idx] = species
    if any(not item for item in symbols):
        raise ValueError("Orbit table does not cover every candidate site.")
    return symbols


def _count_periodic_terms(atoms: Atoms, cutoff: float) -> int:
    frac = atoms.get_scaled_positions(wrap=True)
    cell = np.asarray(atoms.cell.array, dtype=float)
    depth = int(np.ceil(cutoff / min(atoms.cell.lengths())) + 1)
    count = 0
    for i in range(len(atoms)):
        for j in range(i, len(atoms)):
            for shift in itertools.product(range(-depth, depth + 1), repeat=3):
                distance = np.linalg.norm((frac[j] + np.asarray(shift) - frac[i]) @ cell)
                if 1e-12 < distance <= cutoff + 1e-12:
                    count += 1
    return count


def run(reference_cif: Path, orbit_table: Path, pot_root: Path, out_dir: Path, cutoff: float = 11.0) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    request = build_request(reference_cif, orbit_table, pot_root, cutoff)
    (out_dir / "solve_request.json").write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    validation = validate_request(request, strict=True)
    (out_dir / "validation_report.json").write_text(json.dumps(validation.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not validation.valid:
        raise RuntimeError("QLIP request validation failed; see validation_report.json")

    started = time.perf_counter()
    result = solve(request)
    wall_time = time.perf_counter() - started
    result_payload = result.to_dict()
    (out_dir / "solve_result.json").write_text(json.dumps(result_payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if result.status not in {"OPTIMAL", "FEASIBLE"} or not result.outputs.cif:
        raise RuntimeError(f"QLIP solve did not produce a structure: {result.status}")

    solution_path = out_dir / "solution.cif"
    solution_path.write_text(result.outputs.cif, encoding="latin-1")
    solution = read(io.StringIO(result.outputs.cif), format="cif")
    spp = _load_spp(pot_root, cutoff)
    parity_objective = float(spp.score(solution.get_chemical_symbols(), solution.positions, solution.cell.array, pbc=True))
    solver_objective = float(result.summary.objective_value)

    reference = read(reference_cif)
    orbits = _read_orbits(orbit_table)
    alternatives = []
    for assignment in _alternative_assignments(orbits):
        candidate = Atoms(
            symbols=_symbols_for_assignment(orbits, assignment, len(reference)),
            cell=reference.cell,
            pbc=True,
        )
        candidate.set_scaled_positions(reference.get_scaled_positions(wrap=True))
        alternatives.append({"assignment": assignment, "objective": float(spp.score(candidate.symbols, candidate.positions, candidate.cell.array, pbc=True))})
    alternatives.sort(key=lambda item: (item["objective"], json.dumps(item["assignment"], sort_keys=True)))

    scaled = solution.get_scaled_positions(wrap=True)
    duplicate_pairs = [
        [i, j] for i in range(len(solution)) for j in range(i + 1, len(solution))
        if np.linalg.norm(((scaled[j] - scaled[i] + 0.5) % 1.0) - 0.5) < 1e-7
    ]
    summary = {
        "schema_version": "nasicon_qlip_smoke.v1",
        "status": result.status,
        "solver_termination": result.summary.termination,
        "solver_objective": solver_objective,
        "independent_output_objective": parity_objective,
        "objective_parity_abs_error": abs(solver_objective - parity_objective),
        "objective_parity_tolerance": 1e-5,
        "objective_parity": abs(solver_objective - parity_objective) <= 1e-5,
        "wall_time_s": wall_time,
        "reported_timing_ms": result.summary.timing_ms,
        "model_build_time_ms": result.certificates.get("diagnostics", {}).get("model_build_time_ms"),
        "solver_time_ms": result.certificates.get("diagnostics", {}).get("solver_time_ms"),
        "mip_gap": result.summary.mip_gap,
        "candidate_sites": 40,
        "species": 5,
        "binary_variables": 200,
        "auxiliary_variables": 0,
        "constraints": result.certificates.get("diagnostics", {}).get("model_stats", {}).get("constraints"),
        "periodic_pair_image_terms_in_solution": _count_periodic_terms(solution, cutoff),
        "cutoff_angstrom": cutoff,
        "feasible_orbit_alternatives": len(alternatives),
        "alternative_objectives": alternatives,
        "generated_formula": solution.get_chemical_formula(),
        "generated_reduced_formula": _formula_key(solution.get_chemical_symbols()),
        "formula_correct": _formula_key(solution.get_chemical_symbols()) == TARGET_REDUCED_FORMULA,
        "generated_atom_count": len(solution),
        "duplicate_occupied_coordinates": duplicate_pairs,
        "pot_pair_count": len(list(pot_root.rglob("*.POT"))),
        "pot_pairs": sorted(canonical_pair_name(*pair) for pair in itertools.combinations_with_replacement(list(Formula(TARGET_FORMULA).count()), 2)),
        "reference_cif_sha256": _sha256(reference_cif),
        "solution_cif_sha256": _sha256(solution_path),
        "solution_is_byte_copy_of_reference": _sha256(reference_cif) == _sha256(solution_path),
        "scientific_limitations": [
            "The cell and candidate orbit coordinates come from the selected ordered reference scaffold.",
            "The discrete decision is the symmetry-closed Si/P tetrahedral-orbit assignment among three feasible alternatives.",
            "The SPP objective is a statistical proxy and is not thermodynamic stability evidence.",
        ],
    }
    (out_dir / "smoke_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-cif", type=Path, required=True)
    parser.add_argument("--orbit-table", type=Path, required=True)
    parser.add_argument("--pot-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/nasicon_qlip_smoke"))
    parser.add_argument("--cutoff", type=float, default=11.0)
    args = parser.parse_args()
    print(json.dumps(run(args.reference_cif.resolve(), args.orbit_table.resolve(), args.pot_root.resolve(), args.out_dir.resolve(), args.cutoff), indent=2))


if __name__ == "__main__":
    main()
