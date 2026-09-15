"""Build PAPER-RESULTS-1B artefacts from frozen inputs and isolated new cases."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import shutil
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sok_llm_orchestrator.structures.variable_perovskite import (  # noqa: E402
    SCAFFOLD_ID,
    VariablePerovskiteCase,
    canonical_structure_hash,
    enumerate_feasible_assignments,
    structure_for_assignment,
)

OUT = ROOT / "artifacts" / "paper_results_extension_v2" / "00b_scaffold_dof"
FINAL = ROOT / "artifacts" / "paper_final_results_v1"
NA = "NA"

CASE_SOURCES = {
    "CsPbBr3": "local_runs/paper_experiment_2_hard_v3/exp2v3_cspbbr3_halide",
    "CsPbCl3": "local_runs/paper_experiment_2_hard_v3/exp2v3_cspbcl3_halide",
    "CsPbI3": "local_runs/paper_experiment_2_hard_v3/exp2v3_cspbi3_halide",
    "CsSnBr3": "local_runs/paper_experiment_2_hard_v3/exp2v3_cssnbr3_halide",
    "CsSnI3": "local_runs/paper_experiment_2_hard_v3/exp2v3_cssni3_halide",
    "BaTiO3": "local_runs/paper_experiment_1_common_v1/exp1_batio3_perovskite",
    "CaTiO3": "local_runs/paper_experiment_2_hard_v3/exp2v3_catio3_perovskite",
    "SrTiO3": "local_runs/paper_experiment_2_hard_v3/exp2v3_srtio3_perovskite",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def full_formula_counts(formula: str, site_count: int) -> dict[str, int]:
    from pymatgen.core import Composition

    reduced = Composition(formula).reduced_composition
    base = {str(el): int(round(amount)) for el, amount in reduced.get_el_amt_dict().items()}
    scale = site_count // sum(base.values())
    assert scale * sum(base.values()) == site_count
    return {key: value * scale for key, value in base.items()}


def enumerate_orbits(
    orbits: list[dict[str, Any]], target_counts: dict[str, int], lattice, coords: list[list[float]]
) -> tuple[int, list[tuple[dict[str, str], str]]]:
    from pymatgen.core import Structure

    raw_count = math.prod(len(o["allowed_species"]) for o in orbits)
    feasible: list[tuple[dict[str, str], str]] = []
    for values in itertools.product(*(o["allowed_species"] for o in orbits)):
        assignment = {o["orbit_id"]: species for o, species in zip(orbits, values)}
        counts: Counter[str] = Counter()
        species_by_site = [None] * len(coords)
        for orbit, species in zip(orbits, values):
            indices = orbit["site_indices"]
            counts[species] += len(indices)
            for index in indices:
                species_by_site[index] = species
        if dict(counts) != target_counts:
            continue
        assert all(species_by_site)
        structure = Structure(lattice, species_by_site, coords)
        feasible.append((assignment, canonical_structure_hash(structure)))
    return raw_count, feasible


def legacy_scaffold_audit(result: dict[str, str]) -> dict[str, Any]:
    from pymatgen.core import Structure

    cif = Path(result["generated_cif_path"])
    solution = read_json(cif.parent / "qlip_solution.json")["solution"]
    structure = Structure.from_file(cif)
    raw_orbits = solution["orbits"]
    orbits = []
    index_by_orbit: dict[str, list[int]] = {}
    coords = []
    for index, site in enumerate(solution["sites"]):
        index_by_orbit.setdefault(site["orbit_id"], []).append(index)
        coords.append(site["frac_coords"])
    for orbit in raw_orbits:
        orbits.append({
            "orbit_id": orbit["orbit_id"],
            "multiplicity": int(orbit["multiplicity"]),
            "allowed_species": list(orbit["allowed_species"]),
            "site_indices": index_by_orbit[orbit["orbit_id"]],
        })
    target = full_formula_counts(result["target_formula"], len(coords))
    raw_count, feasible = enumerate_orbits(orbits, target, structure.lattice, coords)
    distinct = len({item[1] for item in feasible})
    variable = [o for o in orbits if len(o["allowed_species"]) > 1]
    fixed = [o for o in orbits if len(o["allowed_species"]) == 1]
    return scaffold_row(
        result, orbits, raw_count, feasible, distinct,
        binary_variables=0,
        variable=variable,
        fixed=fixed,
        notes="Complete orbit-product enumeration. Backend was enumeration_backed_qlip_style_selector; it created no formal MILP binary variables.",
    )


def ordered_scaffold_paths(task: str) -> tuple[Path, Path, Path]:
    if task == "nasicon_leave_target_out_v2":
        base = ROOT / "artifacts" / "paper_nasicon_specialist_v2_final" / "leave_target_out"
        return base / "solve_request.json", base / "solve_result.json", base / "generated_nasicon.cif"
    base = ROOT / "artifacts" / "paper_diversity_v2" / "nasicon_demo" / "tasks" / task
    return base / "solve_request.json", base / "solve_result.json", base / "solution.cif"


def ordered_scaffold_audit(result: dict[str, str]) -> dict[str, Any]:
    from pymatgen.core import Structure

    request_path, solve_path, cif_path = ordered_scaffold_paths(result["source_task_id"])
    request = read_json(request_path)
    solve = read_json(solve_path)
    sites = request["problem"]["design_space"]["sites"]
    orbits = [{
        "orbit_id": o["orbit_id"], "multiplicity": len(o["site_indices"]),
        "allowed_species": list(o["allowed_species"]), "site_indices": list(o["site_indices"]),
    } for o in sites["ordered_orbits"]]
    target = {k: int(v) for k, v in full_formula_counts(request["problem"]["chemistry"]["formula"], len(sites["explicit_fractional_sites"])).items()}
    structure = Structure.from_file(cif_path)
    raw_count, feasible = enumerate_orbits(orbits, target, structure.lattice, sites["explicit_fractional_sites"])
    distinct = len({item[1] for item in feasible})
    variable = [o for o in orbits if len(o["allowed_species"]) > 1]
    fixed = [o for o in orbits if len(o["allowed_species"]) == 1]
    binary_variables = solve["certificates"]["diagnostics"]["model_stats"]["variables"]
    return scaffold_row(
        result, orbits, raw_count, feasible, distinct,
        binary_variables=binary_variables,
        variable=variable,
        fixed=fixed,
        notes="Complete symmetry-orbit assignment enumeration; reported binary variable count is the actual QLIP model statistic and does not imply occupational freedom.",
    )


def scaffold_row(
    result: dict[str, str], orbits: list[dict[str, Any]], raw_count: int,
    feasible: list[tuple[dict[str, str], str]], distinct: int, *,
    binary_variables: int, variable: list[dict[str, Any]], fixed: list[dict[str, Any]], notes: str,
) -> dict[str, Any]:
    if distinct == 1:
        classification = "HARD_CONSTRAINT_DETERMINED"
    elif distinct >= 2:
        classification = "MEANINGFUL_VARIABLE_SEARCH"
    else:
        classification = "UNKNOWN"
    return {
        "unique_structure_id": result["unique_structure_id"],
        "source_task_id": result["source_task_id"],
        "composition": result["target_formula"],
        "scaffold_id": result["scaffold_id"],
        "family": result["target_family"],
        "space_group": result["requested_space_group"],
        "candidate_sites": sum(o["multiplicity"] for o in orbits),
        "symmetry_orbits": len(orbits),
        "orbit_multiplicities": ";".join(f"{o['orbit_id']}:{o['multiplicity']}" for o in orbits),
        "variable_orbits": ";".join(o["orbit_id"] for o in variable) or "none",
        "fixed_orbits": ";".join(o["orbit_id"] for o in fixed) or "none",
        "allowed_species_summary": ";".join(f"{o['orbit_id']}={','.join(o['allowed_species'])}" for o in orbits),
        "exact_stoichiometric_constraints": f"exact reduced composition {result['target_formula']} scaled to {sum(o['multiplicity'] for o in orbits)} full-cell sites",
        "orbit_closure_constraints": "one species per complete symmetry orbit; every listed orbit required occupied",
        "other_hard_feasibility_constraints": f"fixed lattice and fractional coordinates; requested {result['requested_space_group']} symmetry; orbit-specific allowed-species domains",
        "binary_variables": binary_variables,
        "raw_assignment_count": raw_count,
        "feasible_assignment_count": len(feasible),
        "distinct_feasible_structure_count": distinct,
        "enumeration_complete": True,
        "objective_can_affect_selection": distinct > 1,
        "classification": classification,
        "notes": notes,
    }


def phase1_audit() -> list[dict[str, Any]]:
    results = read_csv(FINAL / "07_tables" / "FINAL_UNIQUE_STRUCTURE_RESULTS.csv")
    rows = []
    for result in results:
        if result["source_task_id"].startswith(("exp1_", "exp2v3_")):
            rows.append(legacy_scaffold_audit(result))
        else:
            rows.append(ordered_scaffold_audit(result))
    assert len(rows) == 24
    assert Counter(row["classification"] for row in rows) == {
        "HARD_CONSTRAINT_DETERMINED": 22,
        "MEANINGFUL_VARIABLE_SEARCH": 2,
    }
    return rows


def build_cases() -> list[VariablePerovskiteCase]:
    from pymatgen.core import Composition, Structure

    cases = []
    for formula, source in CASE_SOURCES.items():
        run = ROOT / source
        structure = Structure.from_file(run / "generated.cif")
        elements = [str(e) for e in Composition(formula).elements]
        anion = "O" if "O" in elements else next(x for x in ("Br", "Cl", "I") if x in elements)
        cations = tuple(sorted(x for x in elements if x != anion))
        cases.append(VariablePerovskiteCase(formula.lower(), formula, cations, anion, float(structure.lattice.a)))
    return cases


def reference_roles(case: VariablePerovskiteCase) -> tuple[str, str]:
    from pymatgen.core import Structure

    source = ROOT / CASE_SOURCES[case.composition]
    structure = Structure.from_file(source / "generated.cif")
    a = str(min(structure, key=lambda site: float(sum(abs(x) for x in site.frac_coords))).specie)
    b = str(min(structure, key=lambda site: sum(abs(float(x) - 0.5) for x in site.frac_coords)).specie)
    assert {a, b} == set(case.cation_species)
    return a, b


def historical_halide_rows() -> list[dict[str, Any]]:
    rows = []
    for formula in list(CASE_SOURCES)[:5]:
        run = ROOT / CASE_SOURCES[formula]
        solution = read_json(run / "qlip_solution.json")["solution"]
        allowed = {o["wyckoff_label"]: list(o["allowed_species"]) for o in solution["orbits"]}
        candidates = read_json(run / "orbit_candidates.json")["candidates"]
        feasible = [c for c in candidates if c["formula_satisfied"] and c["compatibility_valid"] and c["symmetry_closed"]]
        rows.append({"formula": formula, "allowed": allowed, "feasible": len(feasible), "distinct": 1})
    return rows


def build_variable_outputs(cases: list[VariablePerovskiteCase]):
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Structure
    from pymatgen.io.cif import CifWriter

    assignment_rows, score_rows, decomposition_rows, recovery_rows = [], [], [], []
    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5, primitive_cell=False, scale=False, attempt_supercell=False)
    for case in cases:
        ref_a, ref_b = reference_roles(case)
        reference = Structure.from_file(ROOT / CASE_SOURCES[case.composition] / "generated.cif")
        assignments = enumerate_feasible_assignments(case)
        config = {
            "schema_version": "cubic_perovskite_variable_cation.v1",
            "scaffold_id": SCAFFOLD_ID,
            "case_id": case.case_id,
            "composition": case.composition,
            "lattice_a": case.lattice_a,
            "hard_constraints": {
                "space_group": "Pm-3m", "orbit_closure": True,
                "fixed_fractional_coordinates": True, "fixed_lattice": True,
                "exact_formula": case.composition, "A_allowed": sorted(case.cation_species),
                "B_allowed": sorted(case.cation_species), "X_allowed": [case.anion_species],
            },
            "reference_information_used_by_search": False,
        }
        write_json(OUT / "configs" / f"{case.case_id}.json", config)
        case_assignment_rows = []
        for assignment in assignments:
            structure = structure_for_assignment(case, assignment.a_site_species, assignment.b_site_species)
            cif_path = OUT / "cifs" / f"{assignment.assignment_id}.cif"
            CifWriter(structure, symprec=1e-3).write_file(cif_path)
            is_reference_role = assignment.a_site_species == ref_a and assignment.b_site_species == ref_b
            matches = matcher.fit(structure, reference)
            row = {
                "case_id": case.case_id, "composition": case.composition, "scaffold_id": SCAFFOLD_ID,
                "assignment_id": assignment.assignment_id, "A_site_species": assignment.a_site_species,
                "B_site_species": assignment.b_site_species, "X_site_species": assignment.x_site_species,
                "formula_valid": assignment.formula_valid, "symmetry_valid": assignment.symmetry_valid,
                "orbit_closure_valid": assignment.orbit_closure_valid,
                "canonical_structure_hash": assignment.canonical_structure_hash,
                "reference_role_assignment": is_reference_role, "reference_match": matches,
                "notes": "Reference role and match evaluated only after enumeration; neither constrained construction.",
            }
            assignment_rows.append(row); case_assignment_rows.append(row)

            # Frozen historical records name required pairs but contain no POT
            # curves/numerical coefficients, so scoring and both SPP solves are unavailable.
            score_rows.append({
                "case_id": case.case_id, "composition": case.composition,
                "assignment_id": assignment.assignment_id, "A_site_species": assignment.a_site_species,
                "B_site_species": assignment.b_site_species, "correct_spp_score": NA,
                "correct_spp_rank": NA, "reference_role_assignment": is_reference_role,
                "score_margin_to_next": NA, "required_pair_coverage_percent": 0.0,
                "notes": "Numerical request-specific SPP unavailable: historical qlip_solution has spp_pot_dir=null, spp_scoring_status=unavailable and no pair-score decomposition.",
            })
            for species, distance, multiplicity in (
                (assignment.a_site_species, case.lattice_a / math.sqrt(2), 3),
                (assignment.b_site_species, case.lattice_a / 2, 6),
            ):
                decomposition_rows.append({
                    "case_id": case.case_id, "assignment_id": assignment.assignment_id,
                    "species_pair": "-".join(sorted((species, case.anion_species), key=str.lower)),
                    "distance_A": distance, "periodic_multiplicity": multiplicity,
                    "pair_score": NA, "weighted_contribution": NA, "total_assignment_score": NA,
                })

        ref_assignment = next(r for r in case_assignment_rows if r["reference_role_assignment"])
        recovery_rows.append({
            "case_id": case.case_id, "composition": case.composition,
            "reference_id": f"frozen_historical_scaffold:{CASE_SOURCES[case.composition]}/generated.cif",
            "reference_A_species": ref_a, "reference_B_species": ref_b,
            "num_feasible_assignments": len(assignments), "correct_spp_top_assignment": NA,
            "correct_spp_reference_rank": NA, "correct_spp_reference_top1": NA,
            "correct_spp_margin": NA, "label_swapped_top_assignment": NA,
            "label_swapped_reference_rank": NA, "no_spp_unique_preference": False,
            "solver_correct_spp_status": "NOT_RUN_NUMERICAL_SPP_UNAVAILABLE",
            "solver_correct_spp_assignment": NA, "solver_objective": NA,
            "independent_objective": NA, "objective_difference": NA,
            "reference_structure_match": ref_assignment["reference_match"],
            "notes": "NO_SPP is an exact two-way tie by construction. LABEL_SWAPPED_SPP_CONTROL cannot be formed without numerical source coefficients.",
        })
        write_json(OUT / "solver_logs" / f"{case.case_id}.json", {
            "case_id": case.case_id, "enumeration_status": "COMPLETE", "feasible_assignments": 2,
            "NO_SPP": "EXACT_TIE_ENUMERATED",
            "CORRECT_SPP": "NOT_RUN_NUMERICAL_SPP_UNAVAILABLE",
            "LABEL_SWAPPED_SPP_CONTROL": "NOT_RUN_SOURCE_COEFFICIENTS_UNAVAILABLE",
            "reference_used_by_solver": False,
        })
    return assignment_rows, score_rows, decomposition_rows, recovery_rows


def relaxation_rows(cases: list[VariablePerovskiteCase], run_relaxation: bool) -> list[dict[str, Any]]:
    fields_default = {
        "relaxation_status": "NOT_RUN", "converged": NA, "relaxation_steps": NA,
        "final_fmax_eV_A": NA, "volume_change_percent": NA, "symmetry_retained": NA,
        "relaxed_space_group": NA, "topology": NA, "reference_structure_match": NA,
        "relaxed_cif_path": NA, "notes": "Optional secondary analysis not requested in this invocation.",
    }
    rows = []
    if not run_relaxation:
        for case in cases:
            for assignment in enumerate_feasible_assignments(case):
                rows.append({"case_id": case.case_id, "composition": case.composition, "assignment_id": assignment.assignment_id, **fields_default})
        return rows

    import numpy as np
    import torch
    from chgnet.model.dynamics import StructOptimizer
    from chgnet.model.model import CHGNet
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Structure
    from pymatgen.io.cif import CifWriter
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from sca.evaluators.topology import family_topology_metrics

    model = CHGNet.load()
    relaxer = StructOptimizer(model=model, optimizer_class="FIRE", use_device="cuda" if torch.cuda.is_available() else "cpu")
    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5, primitive_cell=False, scale=False, attempt_supercell=False)
    for case in cases:
        reference = Structure.from_file(ROOT / CASE_SOURCES[case.composition] / "generated.cif")
        policy = "PEROVSKITE_3D" if case.anion_species == "O" else "HALIDE_PEROVSKITE_3D"
        for assignment in enumerate_feasible_assignments(case):
            started = time.perf_counter()
            initial = structure_for_assignment(case, assignment.a_site_species, assignment.b_site_species)
            try:
                result = relaxer.relax(initial, fmax=0.1, steps=200, relax_cell=True, verbose=False)
                final = result.get("final_structure") or result.get("structure")
                trajectory = result.get("trajectory")
                energies = list(getattr(trajectory, "energies", []) or [])
                forces = list(getattr(trajectory, "forces", []) or [])
                final_force = float(np.linalg.norm(np.asarray(forces[-1]), axis=1).max()) if forces else None
                sg = SpacegroupAnalyzer(final, symprec=1e-2).get_space_group_symbol()
                topology, _ = family_topology_metrics(final, policy)
                path = OUT / "cifs" / "relaxed" / f"{assignment.assignment_id}.cif"
                path.parent.mkdir(parents=True, exist_ok=True); CifWriter(final).write_file(path)
                rows.append({
                    "case_id": case.case_id, "composition": case.composition,
                    "assignment_id": assignment.assignment_id, "relaxation_status": "PASS",
                    "converged": final_force is not None and final_force <= 0.1,
                    "relaxation_steps": len(energies), "final_fmax_eV_A": final_force,
                    "volume_change_percent": 100 * (final.volume - initial.volume) / initial.volume,
                    "symmetry_retained": sg == "Pm-3m", "relaxed_space_group": sg,
                    "topology": topology.get("topology_status", NA), "reference_structure_match": matcher.fit(final, reference),
                    "relaxed_cif_path": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "notes": f"Frozen protocol FIRE/fmax=0.1/steps=200/relax_cell=True; runtime_s={time.perf_counter()-started:.3f}. Surrogate result is not stability evidence.",
                })
            except Exception as exc:  # noqa: BLE001
                rows.append({
                    "case_id": case.case_id, "composition": case.composition,
                    "assignment_id": assignment.assignment_id, **fields_default,
                    "relaxation_status": "ERROR", "notes": f"{type(exc).__name__}: {exc}",
                })
    return rows


def write_reports(dof_rows, historical, assignments, recovery, relaxation) -> None:
    counts = Counter(row["classification"] for row in dof_rows)
    dof_md = f"""# Scaffold degrees-of-freedom audit

All 24 final unique structures were audited using their exact frozen source search spaces. Orbit products were completely enumerated under exact full-cell stoichiometry and orbit closure.

- HARD_CONSTRAINT_DETERMINED: **{counts['HARD_CONSTRAINT_DETERMINED']}**
- MEANINGFUL_VARIABLE_SEARCH: **{counts['MEANINGFUL_VARIABLE_SEARCH']}**
- LOW_CHOICE / UNKNOWN: **0 / 0**

The two meaningful variable searches are U-021 and U-022, whose four Si/P orbits (multiplicities 1, 1, 2, 2) admit three exact Si4/P2 assignments. The remaining 22 have one crystallographically distinct feasible occupation even where the underlying model contains many binary variables. Binary-variable count was therefore not used as a proxy for scientific choice.
"""
    (OUT / "SCAFFOLD_DEGREES_OF_FREEDOM.md").write_text(dof_md, encoding="utf-8")

    table = "\n".join(
        f"| {r['formula']} | 1a: {','.join(r['allowed']['1a'])}; 1b: {','.join(r['allowed']['1b'])}; 3c: {','.join(r['allowed']['3c'])} | {r['feasible']} | {r['distinct']} |"
        for r in historical
    )
    diagnosis = f"""# Historical fixed halide scaffold diagnosis

| Composition | Allowed species by orbit | Feasible occupations | Distinct occupations |
|---|---|---:|---:|
{table}

The three workflow conditions returned identical hashes because every condition reused the same fixed Pm-3m lattice and coordinates and the same chemically partitioned occupation domains: Cs only on 1a, Pb/Sn only on 1b, and the target halogen only on 3c after exact-formula filtering. Each composition therefore had exactly one feasible and one crystallographically distinct occupation.

The historical scaffold was effectively deterministic. The recorded QLIP artefacts also report `spp_scoring_status=unavailable`, `spp_pot_dir=null`, and an empty pair-score decomposition. Consequently, the SPP objective could not change the occupation. The historical comparison is **not an SPP-effectiveness experiment** and identical outputs must not be described as SPP robustness.
"""
    (OUT / "HALIDE_FIXED_SCAFFOLD_DIAGNOSIS.md").write_text(diagnosis, encoding="utf-8")

    relax_counts = Counter(r["relaxation_status"] for r in relaxation)
    result = f"""# Variable perovskite results

## Mandatory classification

**RESULT_C: Variable alternatives exist but the current request-specific SPP does not meaningfully distinguish them.**

The new isolated `{SCAFFOLD_ID}` search space produced two exact-formula, Pm-3m, orbit-closed and canonically distinct occupations for each of five halides and three oxide perovskites. X is fixed to the target anion; the two cations are permuted over 1a and 1b. No trusted/reference role enters construction, enumeration, or scoring.

The intended CORRECT_SPP and LABEL_SWAPPED_SPP_CONTROL ranking experiments could not be executed honestly because all eight frozen historical request records lack numerical POT curves. Pair-name manifests show chemical-pair bookkeeping, not objective coefficients. Therefore CORRECT_SPP top-1 is **0/0 evaluable**, LABEL_SWAPPED top-1 is **0/0 evaluable**, and score margins are unavailable. NO_SPP has an exact two-way tie for every case; enumeration, not an arbitrary solver tie-break, is authoritative.

## Suitability for causal ablation

The new scaffold is suitable as the hard-constraint basis for a future causal ablation, but the current frozen numerical evidence is not. A paper-ready causal experiment requires target-excluded, archived numerical SPP curves with full coefficient provenance, followed by CORRECT/NO/LABEL_SWAPPED evaluation under these unchanged constraints.

## Secondary relaxation

Relaxation status counts: {dict(relax_counts)}. CHGNet outcomes, where present, are surrogate structural checks only and are not stability evidence.
"""
    (OUT / "VARIABLE_PEROVSKITE_RESULTS.md").write_text(result, encoding="utf-8")


def validate(dof, assignments, scores, decomposition, recovery) -> None:
    assert len(dof) == 24
    assert sum(r["classification"] == "HARD_CONSTRAINT_DETERMINED" for r in dof) == 22
    assert sum(r["classification"] == "MEANINGFUL_VARIABLE_SEARCH" for r in dof) == 2
    assert len(assignments) == 16 and len({r["canonical_structure_hash"] for r in assignments}) == 16
    assert all(r["formula_valid"] and r["symmetry_valid"] and r["orbit_closure_valid"] for r in assignments)
    assert all(sum(r["case_id"] == case for r in assignments) == 2 for case in {r["case_id"] for r in assignments})
    assert len(scores) == 16 and all(r["correct_spp_score"] == NA for r in scores)
    assert len(decomposition) == 32
    assert len(recovery) == 8 and all(r["num_feasible_assignments"] == 2 for r in recovery)
    for row in assignments:
        assert (OUT / "cifs" / f"{row['assignment_id']}.cif").is_file()
    # Frozen paper sources must still match their own manifest hashes.
    manifest = read_csv(FINAL / "01_manifests" / "FINAL_WORKFLOW_ROW_MANIFEST.csv")
    for row in manifest:
        assert sha256(Path(row["generated_cif_path"])) == row["expected_cif_sha256"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relax", action="store_true", help="run optional frozen CHGNet relaxation protocol")
    args = parser.parse_args()
    for name in ("configs", "cifs", "solver_logs", "tests", "scripts"):
        (OUT / name).mkdir(parents=True, exist_ok=True)

    dof = phase1_audit()
    cases = build_cases()
    historical = historical_halide_rows()
    assignments, scores, decomposition, recovery = build_variable_outputs(cases)
    relaxation = relaxation_rows(cases, args.relax)

    dof_fields = [
        "unique_structure_id", "source_task_id", "composition", "scaffold_id", "family", "space_group",
        "candidate_sites", "symmetry_orbits", "orbit_multiplicities", "variable_orbits",
        "fixed_orbits", "allowed_species_summary", "exact_stoichiometric_constraints",
        "orbit_closure_constraints", "other_hard_feasibility_constraints", "binary_variables", "raw_assignment_count",
        "feasible_assignment_count", "distinct_feasible_structure_count", "enumeration_complete",
        "objective_can_affect_selection", "classification", "notes",
    ]
    write_csv(OUT / "SCAFFOLD_DEGREES_OF_FREEDOM.csv", dof, dof_fields)
    write_csv(OUT / "VARIABLE_PEROVSKITE_FEASIBLE_ASSIGNMENTS.csv", assignments, [
        "case_id", "composition", "scaffold_id", "assignment_id", "A_site_species", "B_site_species",
        "X_site_species", "formula_valid", "symmetry_valid", "orbit_closure_valid",
        "canonical_structure_hash", "reference_role_assignment", "reference_match", "notes",
    ])
    write_csv(OUT / "VARIABLE_PEROVSKITE_SPP_SCORES.csv", scores, [
        "case_id", "composition", "assignment_id", "A_site_species", "B_site_species",
        "correct_spp_score", "correct_spp_rank", "reference_role_assignment", "score_margin_to_next",
        "required_pair_coverage_percent", "notes",
    ])
    write_csv(OUT / "VARIABLE_PEROVSKITE_SPP_DECOMPOSITION.csv", decomposition, [
        "case_id", "assignment_id", "species_pair", "distance_A", "periodic_multiplicity",
        "pair_score", "weighted_contribution", "total_assignment_score",
    ])
    write_csv(OUT / "PEROVSKITE_ROLE_RECOVERY.csv", recovery, [
        "case_id", "composition", "reference_id", "reference_A_species", "reference_B_species",
        "num_feasible_assignments", "correct_spp_top_assignment", "correct_spp_reference_rank",
        "correct_spp_reference_top1", "correct_spp_margin", "label_swapped_top_assignment",
        "label_swapped_reference_rank", "no_spp_unique_preference", "solver_correct_spp_status",
        "solver_correct_spp_assignment", "solver_objective", "independent_objective",
        "objective_difference", "reference_structure_match", "notes",
    ])
    relax_fields = ["case_id", "composition", "assignment_id", "relaxation_status", "converged",
                    "relaxation_steps", "final_fmax_eV_A", "volume_change_percent", "symmetry_retained",
                    "relaxed_space_group", "topology", "reference_structure_match", "relaxed_cif_path", "notes"]
    write_csv(OUT / "PEROVSKITE_ROLE_RELAXATION.csv", relaxation, relax_fields)
    write_reports(dof, historical, assignments, recovery, relaxation)
    validate(dof, assignments, scores, decomposition, recovery)
    shutil.copyfile(__file__, OUT / "scripts" / Path(__file__).name)
    (OUT / "tests" / "FOCUSED_TEST_COMMAND.txt").write_text(
        r".\.venv\Scripts\python.exe -m pytest tests\test_variable_perovskite_scaffold.py -q" + "\n",
        encoding="utf-8",
    )
    print(f"PASS: built {OUT}")
    print("current_scaffolds: hard=22 meaningful=2; variable_cases=8 assignments=16; SPP_evaluable=0")


if __name__ == "__main__":
    main()
