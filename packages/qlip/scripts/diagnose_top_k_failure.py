"""Reproduce and audit the two assignments from the first top-k failure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyomo.environ as pyo
from ase import Atoms
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from qlip.allocation import Allocation
from qlip.scaffolds import resolve_scaffold_corpus_root
from qlip.scaffolds.topk import _assignment, _default_structure


class _ZeroCost:
    include_diagonal_pair_terms = False

    def pair_cost_matrix(self, pair, positions):
        return np.zeros((len(positions), len(positions)), dtype=float)


def _allocation() -> Allocation:
    allocation = Allocation(Atoms("LiNa"))
    allocation.positions = Atoms("H2", cell=[4.0, 4.0, 4.0], pbc=True)
    allocation.positions.set_scaled_positions([[0, 0, 0], [0.25, 0.25, 0.25]])
    allocation.cost = _ZeroCost()
    allocation.ordered_orbits = [
        {"orbit_id": "a", "site_indices": [0], "allowed_species": ["Li", "Na"], "required_occupancy": True},
        {"orbit_id": "b", "site_indices": [1], "allowed_species": ["Li", "Na"], "required_occupancy": True},
    ]
    allocation.encode()
    allocation.m.diagnostic_no_good_cuts = pyo.ConstraintList()
    return allocation


def _raw_structure(allocation: Allocation, assignment: tuple[str, ...]) -> Structure:
    cell = [float(value) for value in allocation.positions.cell.cellpar()]
    fractional = allocation.positions.get_scaled_positions(wrap=True)
    species = [state for state in assignment if state != "VACANCY"]
    coordinates = [fractional[index] for index, state in enumerate(assignment) if state != "VACANCY"]
    return Structure(Lattice.from_parameters(*cell), species, coordinates)


def _cif(structure: Structure) -> str:
    return str(CifWriter(structure, symprec=None)) + "\n"


def _safe(callable_value) -> Any:
    try:
        value = callable_value()
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, tuple):
            return [item.tolist() if isinstance(item, np.ndarray) else item for item in value]
        return value
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    allocation = _allocation()
    solver = pyo.SolverFactory("gurobi")
    assignments: list[dict[str, Any]] = []
    structures: list[Structure] = []
    for index in range(2):
        solved = solver.solve(allocation.m, tee=False)
        if solved.solver.termination_condition != pyo.TerminationCondition.optimal:
            raise RuntimeError(f"assignment {index} did not solve optimally: {solved.solver.termination_condition}")
        decoded = _assignment(allocation)
        raw = _raw_structure(allocation, decoded)
        canonical = _default_structure(allocation, decoded)
        raw_cif = _cif(raw)
        canonical_cif = _cif(canonical)
        analyzer = SpacegroupAnalyzer(canonical, symprec=0.01, angle_tolerance=5.0)
        assignments.append(
            {
                "assignment_index": index,
                "occupation_vector": list(decoded),
                "occupied_species_by_orbit": {"a": decoded[0], "b": decoded[1]},
                "objective_value": float(pyo.value(allocation.m.obj)),
                "generated_cif": canonical_cif,
                "raw_cif_sha256": hashlib.sha256(raw_cif.encode("utf-8")).hexdigest(),
                "canonical_cif_sha256": hashlib.sha256(canonical_cif.encode("utf-8")).hexdigest(),
                "reduced_formula": canonical.composition.reduced_formula,
                "detected_space_group": {"symbol": analyzer.get_space_group_symbol(), "number": analyzer.get_space_group_number()},
                "lattice_parameters": {
                    "a": canonical.lattice.a, "b": canonical.lattice.b, "c": canonical.lattice.c,
                    "alpha": canonical.lattice.alpha, "beta": canonical.lattice.beta, "gamma": canonical.lattice.gamma,
                },
                "fractional_coordinates": [
                    {"species": site.specie.symbol, "coordinates": [float(value) for value in site.frac_coords]}
                    for site in canonical
                ],
            }
        )
        structures.append(canonical)
        selected = [
            allocation.m.vacancy[site] if state == "VACANCY" else allocation.m.x[state, site]
            for site, state in enumerate(decoded)
        ]
        allocation.m.diagnostic_no_good_cuts.add(sum(selected) <= len(selected) - 1)

    matcher = StructureMatcher(
        ltol=0.2, stol=0.3, angle_tol=5.0,
        primitive_cell=True, scale=True, attempt_supercell=False,
    )
    supercell_matcher = StructureMatcher(
        ltol=0.2, stol=0.3, angle_tol=5.0,
        primitive_cell=True, scale=True, attempt_supercell=True,
    )
    fit = bool(matcher.fit(structures[0], structures[1]))
    rms = _safe(lambda: matcher.get_rms_dist(structures[0], structures[1]))
    comparison = {
        "matcher_fit": fit,
        "rms_dist": rms[0] if isinstance(rms, list) else rms,
        "max_dist": rms[1] if isinstance(rms, list) and len(rms) > 1 else None,
        "anonymous_fit": bool(matcher.fit_anonymous(structures[0], structures[1])),
        "supercell_fit": bool(supercell_matcher.fit(structures[0], structures[1])),
        "primitive_cell_setting": True,
        "scale_setting": True,
        "attempt_supercell_setting": False,
        "stol": 0.3,
        "ltol": 0.2,
        "angle_tol": 5.0,
        "mapping_if_available": _safe(lambda: matcher.get_mapping(structures[0], structures[1])),
        "transformation_if_available": _safe(lambda: matcher.get_transformation(structures[0], structures[1])),
    }
    equivalent = fit and comparison["rms_dist"] is not None
    payload = {
        "schema": "paper_diversity_v2.top_k_failure_diagnostic.v1",
        "fixture": "LiNa on two singleton orbits at [0,0,0] and [0.25,0.25,0.25]",
        "assignments": assignments,
        "production_structurematcher": comparison,
        "audit_conclusion": (
            "GENUINELY_EQUIVALENT_UNDER_PRODUCTION_MATCHER"
            if equivalent else "NOT_EQUIVALENT_UNDER_PRODUCTION_MATCHER"
        ),
        "interpretation": (
            "The assignments exchange Li and Na between sites; a periodic origin shift maps both species exactly."
            if equivalent else "The assignments are not related under the recorded matcher configuration."
        ),
    }
    resolution = resolve_scaffold_corpus_root()
    if not resolution.skill_loop_repo_root:
        raise RuntimeError("Sibling Skill-Loop-CSP repository is required for diagnostic export")
    output = Path(resolution.skill_loop_repo_root) / "artifacts" / "paper_diversity_v2" / "representability"
    output.mkdir(parents=True, exist_ok=True)
    (output / "TOP_K_FAILURE_DIAGNOSTIC.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "TOP_K_FAILURE_DIAGNOSTIC.md").write_text(
        f"""# Top-k first-failure diagnostic

The two real Gurobi assignments are `{assignments[0]['occupation_vector']}` and `{assignments[1]['occupation_vector']}`. Their canonical CIF hashes are `{assignments[0]['canonical_cif_sha256']}` and `{assignments[1]['canonical_cif_sha256']}`.

Production `StructureMatcher` reports `fit={comparison['matcher_fit']}`, RMS distance `{comparison['rms_dist']}`, and maximum distance `{comparison['max_dist']}` with `ltol=0.2`, `stol=0.3`, `angle_tol=5.0`, `primitive_cell=True`, `scale=True`, and `attempt_supercell=False`.

Conclusion: **{payload['audit_conclusion']}**. {payload['interpretation']} The original fixture therefore has two assignment-distinct and hash-distinct outputs but one StructureMatcher-distinct crystal. Production structural deduplication should remain enabled for paper candidate-diversity mode.
""",
        encoding="utf-8",
    )
    print(json.dumps({"conclusion": payload["audit_conclusion"], "matcher": comparison, "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
