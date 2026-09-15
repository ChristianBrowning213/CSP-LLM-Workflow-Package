"""Create the same-composition v1/v2 scaffold freedom comparison."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
import time

from pymatgen.core import Composition


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sok_llm_orchestrator.workflow.paper_scaffolds_library import build_family_scaffold  # noqa: E402
from sok_llm_orchestrator.workflow.paper_scaffolds_library_v2 import build_family_scaffold_alternatives  # noqa: E402
from sok_llm_orchestrator.workflow.scaffold_ablation import count_orbit_assignments  # noqa: E402


PANEL = REPO / "artifacts" / "Paper_scaffolds_september" / "scaffold_v2" / "spp_ablation" / "SPP_V2_ABLATION_PANEL_FREEZE.json"
SOURCE = REPO / "outputs" / "Paper_scaffolds_september" / "result_D_stress40"
OUT = REPO / "artifacts" / "Paper_scaffolds_september" / "scaffold_v2"
ABLATION_OUTPUT = REPO / "outputs" / "Paper_scaffolds_september" / "scaffold_v2_ablation"
EVALUATION = OUT / "spp_ablation" / "SPP_V2_SCA_CHGNET_RESULTS.csv"


def _model_counts(formula: str, sites: int, orbits: list[dict]) -> tuple[int, int]:
    species_count = len(Composition(formula).elements)
    binary_variables = sites * species_count + sites  # x[species,site] + uniform vacancy[site]
    orbit_constraints = 0
    for orbit in orbits:
        allowed = set(str(value) for value in orbit["allowed_species"])
        indices = list(orbit["site_indices"])
        for position, _site in enumerate(indices):
            orbit_constraints += species_count - len(allowed)
            if position and not orbit.get("allow_partial_occupation", False):
                orbit_constraints += len(allowed)
            if orbit.get("fixed_species"):
                orbit_constraints += 1
            elif orbit.get("required_occupancy", True):
                orbit_constraints += 1
    hard_constraints = orbit_constraints + species_count + sites + 1
    return binary_variables, hard_constraints


def _variable_sites(orbits: list[dict]) -> int:
    return sum(len(orbit["site_indices"]) for orbit in orbits if len(orbit["allowed_species"]) > 1)


def main() -> int:
    panel = json.loads(PANEL.read_text(encoding="utf-8"))["rows"]
    evaluations = {}
    if EVALUATION.is_file():
        with EVALUATION.open(newline="", encoding="utf-8") as handle:
            evaluations = {
                row["row_id"]: row for row in csv.DictReader(handle)
                if row["condition"] == "request" and row["stage"] == "pre_chgnet"
            }
    rows = []
    for frozen in panel:
        task = {"formula": frozen["formula"], "family": frozen["family"]}
        started = time.perf_counter()
        v1_id, v1_structure, v1_orbits, _ = build_family_scaffold(task, "variable")
        v1_runtime = time.perf_counter() - started
        v1_binaries, v1_constraints = _model_counts(task["formula"], len(v1_structure), v1_orbits)
        v1_states = count_orbit_assignments(task["formula"], len(v1_structure), v1_orbits)
        v1_solver = json.loads((SOURCE / frozen["row_id"] / "qlip" / "solver_result.json").read_text(encoding="utf-8"))
        rows.append({
            "row_id": frozen["row_id"], "family": frozen["family"], "formula": frozen["formula"],
            "scaffold_version": "v1", "scaffold_id": v1_id, "sites": len(v1_structure),
            "variable_sites": _variable_sites(v1_orbits), "binary_variables": v1_binaries,
            "integer_variables": 0, "hard_constraints": v1_constraints,
            "geometry_alternatives": 1, "feasible_assignments_per_geometry": v1_states,
            "total_topology_valid_realisations": v1_states, "fixed_geometry": "cell shape, scale, all fractional coordinates/internal parameters",
            "free_geometry": "none", "fixed_occupations": ";".join(o["orbit_id"] for o in v1_orbits if len(o["allowed_species"]) == 1),
            "free_occupations": ";".join(o["orbit_id"] for o in v1_orbits if len(o["allowed_species"]) > 1) or "none",
            "topology_result": "frozen v1 Result-D PASS by family validator", "construction_runtime_s": v1_runtime,
            "solve_runtime_s": v1_solver.get("runtime_s"),
        })
        started = time.perf_counter()
        alternatives = build_family_scaffold_alternatives(task)
        v2_runtime = time.perf_counter() - started
        example = alternatives[0]
        v2_orbits = list(example.ordered_orbits)
        v2_binaries, v2_constraints = _model_counts(task["formula"], len(example.structure), v2_orbits)
        states = {item.feasible_state_count for item in alternatives}
        if len(states) != 1:
            raise RuntimeError(f"nonuniform v2 occupation count for {frozen['row_id']}")
        per_geometry = states.pop()
        v2_result = json.loads((ABLATION_OUTPUT / frozen["row_id"] / "request" / "result.json").read_text(encoding="utf-8"))
        v2_evaluation = evaluations.get(frozen["row_id"], {})
        topology_result = f"SCA {v2_evaluation.get('sca_topology_status', 'NOT_RUN')}"
        if v2_evaluation.get("independent_olivine") == "OLIVINE":
            topology_result += "; independent OLIVINE"
        rows.append({
            "row_id": frozen["row_id"], "family": frozen["family"], "formula": frozen["formula"],
            "scaffold_version": "v2", "scaffold_id": "paper_scaffolds_library.v2 discrete family set", "sites": len(example.structure),
            "variable_sites": _variable_sites(v2_orbits), "binary_variables": v2_binaries,
            "integer_variables": 0, "hard_constraints": v2_constraints,
            "geometry_alternatives": len(alternatives), "feasible_assignments_per_geometry": per_geometry,
            "total_topology_valid_realisations": len(alternatives) * per_geometry,
            "fixed_geometry": "topology network and fractional sites within each discrete solve",
            "free_geometry": "retrieval-derived cell-scale quartiles; frozen family-generic internal grid where supported",
            "fixed_occupations": ";".join(o["orbit_id"] for o in v2_orbits if len(o["allowed_species"]) == 1),
            "free_occupations": ";".join(o["orbit_id"] for o in v2_orbits if len(o["allowed_species"]) > 1) or "none",
            "topology_result": topology_result,
            "construction_runtime_s": v2_runtime,
            "solve_runtime_s": v2_result["winner"]["runtime_s"],
        })
    csv_path = OUT / "V1_V2_FREEDOM_COMPARISON.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# V1 vs v2 freedom comparison", "",
        "Counts use the exact QLIP allocation encoding: species/site binaries plus the uniform fixed-zero vacancy binary per site; hard constraints include orbit-domain/closure/full-occupancy constraints, stoichiometry, site exclusivity, and vacancy count.", "",
        "| row | family | formula | version | sites | variable sites | binaries | hard constraints | geometries | states/geometry | total realisations |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(f"| {row['row_id']} | {row['family']} | {row['formula']} | {row['scaffold_version']} | {row['sites']} | {row['variable_sites']} | {row['binary_variables']} | {row['hard_constraints']} | {row['geometry_alternatives']} | {row['feasible_assignments_per_geometry']} | {row['total_topology_valid_realisations']} |")
    lines.extend(["", "V2 freedom is discrete and interpretable. Rocksalt gains cell-scale choice but no artificial occupational state; spinel gains normal and two ordered inverse-compatible states plus scale/oxygen-parameter alternatives; O3 gains layer ordering and scale/oxygen-height alternatives; olivine retains M1/M2 ordering and gains scale alternatives.", ""])
    (OUT / "V1_V2_FREEDOM_COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
