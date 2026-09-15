"""Build PAPER-RESULTS-FINAL-V2 from frozen evidence plus the declared factorial.

The script never runs retrieval, SPP fitting, GRID8, or CHGNet.  It reuses the
frozen archives, evaluates the two validated variable-perovskite occupations,
and runs only the requested tight/loose IP-CSP objective confirmations.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_results_extension_v3"
V1 = ROOT / "artifacts" / "paper_final_results_v1"
V2 = ROOT / "artifacts" / "paper_results_extension_v2"
DOF = V2 / "00b_scaffold_dof"
GRID8 = V2 / "00d_spp_dominant_search"
SCA_ARCHIVE = ROOT.parent / "Structured_Crystal_Analyser" / "artifacts" / "paper_full_sca_v1"
REF_MANIFEST = SCA_ARCHIVE / "reference" / "REFERENCE_CORPUS_MANIFEST.csv"
NA = "NA"

sys.path[:0] = [str(ROOT / "src"), str(ROOT.parent / "Structured_Crystal_Analyser")]

spec = importlib.util.spec_from_file_location("spp_dominant", ROOT / "scripts" / "run_spp_dominant_search.py")
assert spec and spec.loader
spp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spp)

from sok_llm_orchestrator.structures.variable_perovskite import (  # noqa: E402
    canonical_structure_hash,
    structure_for_assignment,
    VariablePerovskiteCase,
)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, data: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(data)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def boolish(value: Any) -> bool:
    return str(value).lower() == "true"


def pct_error(value: float, reference: float) -> float:
    return 100.0 * (value - reference) / reference


def git_commit(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "NOT_A_GIT_CHECKOUT"


def role_case(case_id: str) -> VariablePerovskiteCase:
    formula, c1, c2, x, source = spp.CASES[case_id]
    return VariablePerovskiteCase(
        case_id=case_id,
        composition=formula,
        cation_species=(c1, c2),
        anion_species=x,
        lattice_a=spp.case_lattice_a(case_id),
    )


def candidate_structure(case_id: str, assignment_id: str):
    case = role_case(case_id)
    inverted = assignment_id.endswith("02")
    a, b = case.cation_species
    return structure_for_assignment(case, b if inverted else a, a if inverted else b)


def objective_score(case_id: str, assignment_id: str, *, perturbed: bool = False) -> float:
    structure = candidate_structure(case_id, assignment_id)
    return spp.score_occupation(
        case_id,
        [tuple(float(v) for v in site.frac_coords) for site in structure],
        [str(site.specie) for site in structure],
        swapped=perturbed,
    )


def evaluate_structure(structure, case_id: str) -> dict[str, Any]:
    import numpy as np
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from sca.evaluators.topology import family_topology_metrics

    x = spp.CASES[case_id][3]
    policy = "PEROVSKITE_3D" if x == "O" else "HALIDE_PEROVSKITE_3D"
    topology, details = family_topology_metrics(structure, policy)
    distance_matrix = np.array(structure.distance_matrix, dtype=float)
    distance_matrix[distance_matrix < 1e-12] = np.inf
    analyzer = SpacegroupAnalyzer(structure, symprec=1e-3, angle_tolerance=5.0)
    minimum = float(distance_matrix.min())
    return {
        "parse_status": "PASS",
        "formula": structure.composition.reduced_formula,
        "detected_space_group": analyzer.get_space_group_symbol(),
        "crystal_system": analyzer.get_crystal_system(),
        "minimum_distance_A": minimum,
        "severe_contact_status": "PASS" if minimum >= 0.75 else "FAIL",
        "topology_status": topology["topology_status"],
        "geometry_coordination_diagnostics": json.dumps(details, sort_keys=True, default=str),
        "topology_policy": policy,
    }


def solve_role_model(case_id: str, *, tight: bool, raw_root: Path) -> dict[str, Any]:
    import gurobipy as gp
    from gurobipy import GRB

    formula, c1, c2, x, _ = spp.CASES[case_id]
    coords = [(0.0, 0.0, 0.0), (0.5, 0.5, 0.5), (0.5, 0.5, 0.0), (0.5, 0.0, 0.5), (0.0, 0.5, 0.5)]
    domains = [{c1}, {c2}, {x}, {x}, {x}] if tight else [{c1, c2}, {c1, c2}, {x}, {x}, {x}]
    species = (c1, c2, x)
    counts = {c1: 1, c2: 1, x: 3}
    raw_root.mkdir(parents=True, exist_ok=True)
    log_path = raw_root / ("tight_correct_spp.log" if tight else "loose_correct_spp.log")
    model = gp.Model(f"final_v2_{case_id}_{'tight' if tight else 'loose'}")
    model.Params.Seed = 0
    model.Params.Threads = 8
    model.Params.MIPGap = 0.0
    model.Params.NonConvex = 2
    model.Params.LogToConsole = 0
    model.Params.LogFile = str(log_path)
    variables = {
        (p, i): model.addVar(vtype=GRB.BINARY, name=f"x_{p}_{i}")
        for i, domain in enumerate(domains) for p in sorted(domain)
    }
    for p in species:
        model.addConstr(gp.quicksum(v for (q, _), v in variables.items() if q == p) == counts[p], name=f"count_{p}")
    for i in range(len(coords)):
        model.addConstr(gp.quicksum(v for (p, j), v in variables.items() if j == i) == 1, name=f"occupy_{i}")
    objective = gp.QuadExpr()
    linear_terms = 0
    pair_terms = 0
    for (p, i), variable in variables.items():
        objective += spp.coefficient_for_species(case_id, coords[i], coords[i], p, p, swapped=False, self_pair=True) * variable
        linear_terms += 1
    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            left = [(p, v) for (p, site), v in variables.items() if site == i]
            right = [(q, v) for (q, site), v in variables.items() if site == j]
            for p, v1 in left:
                for q, v2 in right:
                    coefficient = spp.coefficient_for_species(case_id, coords[i], coords[j], p, q, swapped=False, self_pair=False)
                    objective += coefficient * v1 * v2
                    pair_terms += 1
    model.setObjective(objective, GRB.MINIMIZE)
    model.update()
    input_path = raw_root / ("tight_solver_input.lp" if tight else "loose_solver_input.lp")
    model.write(str(input_path))
    start = time.perf_counter()
    model.optimize()
    elapsed = time.perf_counter() - start
    status = "OPTIMAL" if model.Status == GRB.OPTIMAL else f"GUROBI_STATUS_{model.Status}"
    if model.Status != GRB.OPTIMAL:
        raise RuntimeError(f"{case_id} {'tight' if tight else 'loose'} solver status {model.Status}")
    selected = []
    for i in range(len(coords)):
        chosen = [p for (p, site), v in variables.items() if site == i and v.X > 0.5]
        if len(chosen) != 1:
            raise RuntimeError(f"invalid occupation at {case_id}/{i}: {chosen}")
        selected.append(chosen[0])
    assignment = f"{case_id}-assignment-01" if selected[0] == c1 else f"{case_id}-assignment-02"
    independent = spp.score_occupation(case_id, coords, selected, swapped=False)
    difference = float(model.ObjVal) - independent
    payload = {
        "case_id": case_id,
        "composition": formula,
        "condition": "TIGHT_CORRECT_SPP" if tight else "LOOSE_CORRECT_SPP",
        "solver_backend": "Gurobi exact binary nonconvex MIQP",
        "solver_status": status,
        "selected_assignment": assignment,
        "solver_objective": float(model.ObjVal),
        "independently_recomputed_objective": independent,
        "absolute_objective_difference": abs(difference),
        "objective_parity": abs(difference) <= 1e-6,
        "solve_time_s": elapsed,
        "binary_variable_count": len(variables),
        "constraint_count": int(model.NumConstrs),
        "linear_self_term_count": linear_terms,
        "pair_term_count": pair_terms,
        "solver_input": rel(input_path),
        "solver_log": rel(log_path),
    }
    if not payload["objective_parity"]:
        raise RuntimeError(f"objective parity failed: {payload}")
    write_json(raw_root / ("tight_solver_result.json" if tight else "loose_solver_result.json"), payload)
    return payload


def build_execution_block() -> None:
    source = {row["metric"]: row for row in rows(V2 / "00_audit" / "EXECUTION_FUNNEL.csv")}
    mapping = [
        ("scientific_requests", "scientific_requests"),
        ("workflow_executions", "workflow_executions"),
        ("solver_or_selector_attempts", "solver_attempts"),
        ("explicit_OPTIMAL_solves", "optimal_solves"),
        ("legacy_generated_selections", "solver_outcome_not_formally_certified"),
        ("generated_CIF_executions", "cifs_generated"),
        ("parseable_CIF_executions", "cifs_parseable"),
        ("duplicate_generated_executions", "duplicate_generated_executions"),
        ("unique_generated_structures", "crystallographically_unique_generated_structures"),
        ("scientific_abstentions", "scientific_abstentions"),
        ("blocked_before_solver", "blocked_before_solver"),
        ("software_errors", "software_errors"),
    ]
    funnel = [{"metric": new, "count": source[old]["count"], "definition": source[old]["definition"]} for new, old in mapping]
    write_csv(OUT / "01_execution" / "EXECUTION_FUNNEL.csv", funnel, ["metric", "count", "definition"])
    write_text(OUT / "01_execution" / "EXECUTION_FUNNEL.md", "# Execution funnel\n\n" + "\n".join(f"- {r['metric']}: **{r['count']}** — {r['definition']}" for r in funnel))
    metric_rows = [
        ("CIF parse", "FORMULATION_OR_CONSTRAINT_CHECK", "software and serialization integrity"),
        ("exact formula", "FORMULATION_OR_CONSTRAINT_CHECK", "stoichiometry is hard constrained"),
        ("requested initial space group", "FORMULATION_OR_CONSTRAINT_CHECK", "symmetry is scaffold constrained"),
        ("solver feasibility", "FORMULATION_OR_CONSTRAINT_CHECK", "mathematical formulation check"),
        ("solver objective parity", "FORMULATION_OR_CONSTRAINT_CHECK", "implementation cross-check"),
        ("minimum periodic distance", "INDEPENDENT_STRUCTURAL_EVALUATION", "post-hoc in frozen campaign and factorial"),
        ("SCA topology", "INDEPENDENT_STRUCTURAL_EVALUATION", "post-generation evaluator"),
        ("CHGNet relaxation", "INDEPENDENT_STRUCTURAL_EVALUATION", "surrogate geometry QC; not stability"),
        ("reference StructureMatcher", "INDEPENDENT_STRUCTURAL_EVALUATION", "reference QC subject to provenance"),
        ("SPP factorial/ablation", "CAUSAL_METHOD_EVIDENCE", "same candidate domain with objective changed"),
    ]
    write_csv(OUT / "01_execution" / "METRIC_CLASSIFICATION.csv", [dict(metric=a, classification=b, rationale=c) for a, b, c in metric_rows], ["metric", "classification", "rationale"])
    task = ROOT / "artifacts" / "paper_diversity_v2" / "nasicon_demo" / "tasks" / "E4_A2"
    trace = [
        ("request_id", "E4_A2", "CURATED_CONFIGURATION"),
        ("request_text", "ordered Na3Zr2Si2PO12 in C2", "USER_TEXT"),
        ("structured_task", rel(task / "solve_request.json"), "DETERMINISTIC_PARSE;CURATED_CONFIGURATION"),
        ("field_provenance", rel(task / "request_validation.json"), "DETERMINISTIC_PARSE;SCAFFOLD_REGISTRY"),
        ("Crystal-DB corpus", "nasicon_specialist_all_targets_out_v3", "CURATED_CONFIGURATION"),
        ("retrieval", rel(task / "retrieval.json"), "CURATED_CONFIGURATION"),
        ("SPP artefact", rel(task / "retrieved_evidence.json"), "CURATED_CONFIGURATION"),
        ("scaffold", "nasicon_na3zr2si2po12_c2_ordered", "SCAFFOLD_REGISTRY"),
        ("solver request", rel(task / "solve_request.json"), "DETERMINISTIC_PARSE"),
        ("solver result", rel(task / "solve_result.json"), "DETERMINISTIC_PARSE"),
        ("candidate CIF", rel(task / "solution.cif"), "DETERMINISTIC_PARSE"),
        ("SCA output", rel(task / "sca_response.json"), "DETERMINISTIC_PARSE"),
        ("CHGNet output", "artifacts/paper_final_results_v1/03_sca/FINAL_RELAXATION_RESULTS.csv#U-022", "CURATED_CONFIGURATION"),
        ("relaxed CIF", "runs/paper_final_results_v1/U-022/relaxation/relaxed.cif", "DETERMINISTIC_PARSE"),
    ]
    write_csv(OUT / "01_execution" / "TRACE_EXAMPLE.csv", [dict(field=a, value=b, provenance=c) for a, b, c in trace], ["field", "value", "provenance"])
    write_text(OUT / "01_execution" / "TRACE_EXAMPLE.md", "# Complete trace example — E4_A2\n\nThe trace records deterministic and curated field provenance; it does not claim evaluated autonomous free-text parsing.\n\n" + "\n".join(f"- {a}: `{b}` ({c})" for a, b, c in trace))


def task_reference(source_task_id: str, manifest: list[dict[str, str]]) -> dict[str, str] | None:
    exact = [r for r in manifest if source_task_id.lower() in Path(r["reference_cif_path"]).parts[-3].lower()]
    if exact:
        return exact[0]
    if source_task_id == "nasicon_leave_target_out_v2":
        candidates = [r for r in manifest if r["reference_id"] == "frozen_ordered_nasicon_reference"]
        return candidates[0] if candidates else None
    return None


def compare_structures(generated, reference, matcher) -> dict[str, Any]:
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    ga = SpacegroupAnalyzer(generated, symprec=1e-3, angle_tolerance=5.0)
    ra = SpacegroupAnalyzer(reference, symprec=1e-3, angle_tolerance=5.0)
    gsg, rsg = ga.get_space_group_symbol(), ra.get_space_group_symbol()
    gcs, rcs = ga.get_crystal_system(), ra.get_crystal_system()
    match = matcher.fit(generated, reference)
    rms = matcher.get_rms_dist(generated, reference) if match else None
    lattice_errors = [NA, NA, NA]
    if gcs == rcs:
        gl = sorted(float(v) for v in ga.get_conventional_standard_structure().lattice.abc)
        rl = sorted(float(v) for v in ra.get_conventional_standard_structure().lattice.abc)
        lattice_errors = [pct_error(a, b) for a, b in zip(gl, rl)]
    return {
        "structurematcher_match": match,
        "generated_space_group": gsg,
        "reference_space_group": rsg,
        "same_space_group": gsg == rsg,
        "same_crystal_system": gcs == rcs,
        "generated_volume_per_atom_A3": generated.volume / len(generated),
        "reference_volume_per_atom_A3": reference.volume / len(reference),
        "volume_per_atom_error_percent": pct_error(generated.volume / len(generated), reference.volume / len(reference)),
        "lattice_a_error_percent": lattice_errors[0],
        "lattice_b_error_percent": lattice_errors[1],
        "lattice_c_error_percent": lattice_errors[2],
        "rms_atomic_displacement_A": rms[0] if rms else NA,
        "max_atomic_displacement_A": rms[1] if rms else NA,
    }


def build_reference_block() -> dict[str, Any]:
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Structure

    unique = rows(V1 / "07_tables" / "FINAL_UNIQUE_STRUCTURE_RESULTS.csv")
    manifest = rows(REF_MANIFEST)
    matcher_config = {"ltol": 0.2, "stol": 0.3, "angle_tol": 5.0, "primitive_cell": True, "scale": True, "attempt_supercell": False, "symprec": 0.001}
    write_json(OUT / "02_reference" / "STRUCTUREMATCHER_CONFIG.json", matcher_config)
    matcher = StructureMatcher(**{k: v for k, v in matcher_config.items() if k != "symprec"})
    provenance, benchmark, sca_initial, sca_relaxed, relaxation = [], [], [], [], []
    for row in unique:
        generated_path = Path(row["generated_cif_path"])
        generated = Structure.from_file(generated_path)
        reference_row = task_reference(row["source_task_id"], manifest)
        independence = "NO_REFERENCE"
        reference_path = None
        if reference_row:
            reference_path = Path(reference_row["reference_cif_path"])
            independence = "INDEPENDENT_REFERENCE" if row["source_task_id"] == "nasicon_leave_target_out_v2" else "RETRIEVAL_EXPOSED"
        provenance.append({
            "case_id": row["unique_structure_id"], "formula": row["target_formula"], "family": row["target_family"],
            "reference_source": reference_row["reference_source"] if reference_row else NA,
            "reference_id": reference_row["reference_id"] if reference_row else NA,
            "reference_cif": rel(reference_path) if reference_path else NA,
            "reference_space_group": NA, "reference_hash": reference_row["sha256"] if reference_row else NA,
            "scaffold_id": row["scaffold_id"], "scaffold_source_id": row["source_task_id"],
            "scaffold_derived_from_reference": False if independence == "INDEPENDENT_REFERENCE" else NA,
            "scaffold_equivalent_to_reference": NA,
            "reference_excluded_from_retrieval": independence == "INDEPENDENT_REFERENCE",
            "equivalent_reference_excluded_from_retrieval": independence == "INDEPENDENT_REFERENCE",
            "reference_independence_class": independence,
            "notes": "Frozen task-matched controlled reference; retrieval-exposed references are excluded from independent headline statistics." if reference_row else "No task-matched reference in the frozen controlled corpus.",
        })
        sca_initial.append({
            "case_id": row["unique_structure_id"], "formula": row["target_formula"], "parse_result": row["parse_ok"],
            "formula_result": row["formula_match"], "detected_space_group": row["detected_space_group"],
            "crystal_system": row["detected_crystal_system"], "minimum_periodic_distance_A": row["minimum_distance"],
            "severe_contact_result": row["contact_screen_pass"], "family_topology_result": row["topology_status"],
            "geometry_coordination_diagnostics": row["topology_details"], "SCA_version": "frozen paper_full_sca_v1",
            "SCA_git_commit": git_commit(ROOT.parent / "Structured_Crystal_Analyser"),
            "configuration": "paper_full_sca_v1", "symmetry_tolerances": "symprec=0.001,0.01,0.1; headline=0.001; angle=5",
            "topology_policy": row["topology_policy"], "minimum_distance_threshold_A": "frozen evaluator policy",
        })
        sca_relaxed.append({
            "case_id": row["unique_structure_id"], "formula": row["target_formula"], "parse_result": row["post_relax_status"],
            "detected_space_group": row["space_group_after"], "crystal_system_retained": row["crystal_system_retained"],
            "minimum_periodic_distance_A": row["minimum_distance_after"], "severe_contact_count": row["severe_contact_count_after"],
            "family_topology_result": row["topology_after"], "topology_retained": row["topology_retained"],
            "configuration": "same frozen paper_full_sca_v1 evaluator as initial",
        })
        relaxation.append({
            "case_id": row["unique_structure_id"], "formula": row["target_formula"], "initial_space_group": row["space_group_before"],
            "relaxed_space_group": row["space_group_after"], "space_group_retained": row["space_group_retained"],
            "initial_crystal_system": row["detected_crystal_system"], "relaxed_crystal_system": row["detected_crystal_system"] if boolish(row["crystal_system_retained"]) else "CHANGED",
            "crystal_system_retained": row["crystal_system_retained"], "initial_topology": row["topology_before"],
            "relaxed_topology": row["topology_after"], "initial_volume_A3": row["initial_volume"], "relaxed_volume_A3": row["final_volume"],
            "volume_change_percent": row["volume_change_percent"], "relaxation_steps": row["relaxation_steps"],
            "final_fmax_eV_A": row["final_max_force"], "convergence": row["converged"],
            "StructureMatcher_initial_relaxed": row["structure_match_initial_relaxed"],
            "StructureMatcher_relaxed_reference": NA, "rms_displacement_A": row["rms_dist_initial_relaxed"],
            "notes": "CHGNet force convergence is surrogate geometry QC, not thermodynamic stability.",
        })
        if reference_path:
            reference = Structure.from_file(reference_path)
            comp = compare_structures(generated, reference, matcher)
            provenance[-1]["reference_space_group"] = comp["reference_space_group"]
            provenance[-1]["scaffold_equivalent_to_reference"] = comp["structurematcher_match"]
            benchmark.append({
                "case_id": row["unique_structure_id"], "formula": row["target_formula"], "family": row["target_family"],
                "reference_id": reference_row["reference_id"], "reference_independence_class": independence,
                **comp, "SCA_generated_topology": row["topology_status"], "SCA_reference_topology": NA,
                "topology_agreement": NA, "coordination_agreement": NA,
                "notes": "Reference was retrieval-exposed; consistency only." if independence == "RETRIEVAL_EXPOSED" else "Strict leave-target-out reference.",
            })
            relaxed_path = Path(row["relaxed_cif_path"])
            if relaxed_path.exists():
                relaxed_comp = compare_structures(Structure.from_file(relaxed_path), reference, matcher)
                relaxation[-1]["StructureMatcher_relaxed_reference"] = relaxed_comp["structurematcher_match"]
    write_csv(OUT / "02_reference" / "REFERENCE_PROVENANCE.csv", provenance, list(provenance[0]))
    write_csv(OUT / "02_reference" / "SCA_INITIAL_RESULTS.csv", sca_initial, list(sca_initial[0]))
    write_csv(OUT / "02_reference" / "SCA_RELAXED_RESULTS.csv", sca_relaxed, list(sca_relaxed[0]))
    write_csv(OUT / "02_reference" / "CHGNET_RELAXATION_RESULTS.csv", relaxation, list(relaxation[0]))
    fields = [
        "case_id", "formula", "family", "reference_id", "reference_independence_class", "structurematcher_match",
        "generated_space_group", "reference_space_group", "same_space_group", "same_crystal_system",
        "generated_volume_per_atom_A3", "reference_volume_per_atom_A3", "volume_per_atom_error_percent",
        "lattice_a_error_percent", "lattice_b_error_percent", "lattice_c_error_percent", "rms_atomic_displacement_A",
        "max_atomic_displacement_A", "SCA_generated_topology", "SCA_reference_topology", "topology_agreement",
        "coordination_agreement", "notes",
    ]
    write_csv(OUT / "02_reference" / "REFERENCE_STRUCTURE_BENCHMARK.csv", benchmark, fields)
    def summary(cohort: list[dict[str, Any]], name: str) -> dict[str, Any]:
        volume = [abs(float(r["volume_per_atom_error_percent"])) for r in cohort]
        return {
            "cohort": name, "N": len(cohort),
            "StructureMatcher_matches": sum(boolish(r["structurematcher_match"]) for r in cohort),
            "exact_SG_matches": sum(boolish(r["same_space_group"]) for r in cohort),
            "crystal_system_matches": sum(boolish(r["same_crystal_system"]) for r in cohort),
            "topology_agreement": NA,
            "median_absolute_volume_error_percent": statistics.median(volume) if volume else NA,
            "IQR_absolute_volume_error_percent": (statistics.quantiles(volume, n=4)[2] - statistics.quantiles(volume, n=4)[0]) if len(volume) >= 4 else NA,
            "range_absolute_volume_error_percent": f"{min(volume)}..{max(volume)}" if volume else NA,
        }
    summaries = [summary(benchmark, "ALL_DEFENSIBLE_REFERENCES"), summary([r for r in benchmark if r["reference_independence_class"] == "INDEPENDENT_REFERENCE"], "INDEPENDENT_REFERENCES_ONLY")]
    write_text(OUT / "02_reference" / "REFERENCE_RESULTS.md", "# Known-crystal reference benchmark\n\n" + "\n".join(f"- {r['cohort']}: N={r['N']}, StructureMatcher={r['StructureMatcher_matches']}/{r['N']}, exact SG={r['exact_SG_matches']}/{r['N']}, crystal system={r['crystal_system_matches']}/{r['N']}, median |volume error|={r['median_absolute_volume_error_percent']}%." for r in summaries) + "\n\nRetrieval-exposed references are consistency checks and are not included in the independent headline denominator. Force convergence is not thermodynamic stability.")
    return {"provenance": provenance, "benchmark": benchmark, "summaries": summaries, "unique": unique}


def build_factorial_block() -> dict[str, Any]:
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Structure
    from pymatgen.io.cif import CifWriter

    assignment_archive = rows(DOF / "VARIABLE_PEROVSKITE_FEASIBLE_ASSIGNMENTS.csv")
    relax_archive = {r["assignment_id"]: r for r in rows(DOF / "PEROVSKITE_ROLE_RELAXATION.csv")}
    spp_manifest = {r["case_id"]: r for r in rows(GRID8 / "SPP_SOURCE_MANIFEST.csv")}
    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5.0, primitive_cell=False, scale=False, attempt_supercell=False)
    case_selection, score_rows, sca_rows, comparison_rows, solver_rows, factorial, relax_rows = [], [], [], [], [], [], []
    raw_root = OUT / "03_scaffold_spp" / "raw"
    for case_id in spp.CASES:
        formula, c1, c2, x, source = spp.CASES[case_id]
        manifest = spp_manifest[case_id]
        coverage = float(manifest["coverage_percent"])
        retrieval_path = GRID8 / "spp" / case_id / "retrieval.json"
        retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
        metadata_supplement = any(str(r.get("retrieval_purpose", "")).startswith("metadata_pair_coverage") for r in retrieval["selected"])
        coverage_class = "EXCLUDED_INSUFFICIENT_COVERAGE" if coverage < 100 else ("SUPPLEMENTED_PAIR_COVERAGE" if metadata_supplement else "STRICT_PRIMARY")
        included = coverage == 100
        case_selection.append({
            "case_id": case_id, "composition": formula, "family": "oxide perovskite" if x == "O" else "halide perovskite",
            "tight_scaffold_id": f"frozen_{case_id}_fixed_roles", "loose_scaffold_id": "cubic_perovskite_variable_cation_v1",
            "tight_feasible_count": 1, "loose_feasible_count": 2, "SPP_coverage_class": coverage_class,
            "reference_independence_class": "SCAFFOLD_SOURCE_OR_EQUIVALENT; exact composition excluded from SPP evidence",
            "included_strict_primary": coverage_class == "STRICT_PRIMARY", "included_supplementary": coverage_class == "SUPPLEMENTED_PAIR_COVERAGE",
            "exclusion_reason": "missing Sr-Ti target-excluded co-occurrence; no curve invented" if coverage < 100 else NA,
        })
        if not included:
            continue
        case_raw = raw_root / case_id
        case_raw.mkdir(parents=True, exist_ok=True)
        shutil.copy2(retrieval_path, case_raw / "retrieval_result.json")
        shutil.copy2(GRID8 / "spp" / case_id / "spp_generation.json", case_raw / "spp_fitter_result.json")
        write_json(case_raw / "request_task.json", {"case_id": case_id, "request": spp.query_text(case_id), "target_formula": formula, "reference_coordinates_used_for_objective": False})
        write_json(case_raw / "scaffold_definition.json", {"tight": {"id": f"frozen_{case_id}_fixed_roles", "feasible": 1}, "loose": {"id": "cubic_perovskite_variable_cation_v1", "positions": [[0,0,0],[0.5,0.5,0.5],[0.5,0.5,0],[0.5,0,0.5],[0,0.5,0.5]], "cation_domains": [c1,c2], "anion_orbit_fixed": x, "feasible": 2}})
        case_assignments = [r for r in assignment_archive if r["case_id"] == case_id]
        evaluations: dict[str, dict[str, Any]] = {}
        scores: dict[str, dict[str, float]] = {}
        reference = Structure.from_file(ROOT / source / "generated.cif")
        for assignment in case_assignments:
            aid = assignment["assignment_id"]
            structure = candidate_structure(case_id, aid)
            cif_path = case_raw / f"{aid}.cif"
            CifWriter(structure).write_file(cif_path)
            evaluation = evaluate_structure(structure, case_id)
            evaluations[aid] = evaluation
            correct = objective_score(case_id, aid)
            perturbed = objective_score(case_id, aid, perturbed=True)
            scores[aid] = {"correct": correct, "perturbed": perturbed}
        correct_order = sorted(case_assignments, key=lambda a: (scores[a["assignment_id"]]["correct"], a["assignment_id"]))
        perturbed_order = sorted(case_assignments, key=lambda a: (scores[a["assignment_id"]]["perturbed"], a["assignment_id"]))
        for assignment in case_assignments:
            aid = assignment["assignment_id"]
            structure = candidate_structure(case_id, aid)
            correct_rank = 1 + sum(scores[o["assignment_id"]]["correct"] < scores[aid]["correct"] - 1e-10 for o in case_assignments)
            perturbed_rank = 1 + sum(scores[o["assignment_id"]]["perturbed"] < scores[aid]["perturbed"] - 1e-10 for o in case_assignments)
            score_rows.append({
                "case_id": case_id, "assignment_id": aid, "occupation": f"1a={assignment['A_site_species']};1b={assignment['B_site_species']};3c={x}",
                "canonical_hash": canonical_structure_hash(structure), "reference_match": matcher.fit(structure, reference),
                "SCA_topology": evaluations[aid]["topology_status"], "SCA_minimum_distance_A": evaluations[aid]["minimum_distance_A"],
                "correct_spp_score": scores[aid]["correct"], "correct_spp_rank": correct_rank,
                "perturbed_spp_score": scores[aid]["perturbed"], "perturbed_spp_rank": perturbed_rank,
            })
            sca_rows.append({"case_id": case_id, "assignment_id": aid, "conditions_reusing_candidate": "TIGHT_NO_SPP;TIGHT_CORRECT_SPP" if aid.endswith("01") else "LOOSE_NO_SPP;LOOSE_CORRECT_SPP;LOOSE_PERTURBED_SPP", **evaluations[aid]})
            comparison_rows.append({"case_id": case_id, "assignment_id": aid, **compare_structures(structure, reference, matcher), "topology_agreement": evaluations[aid]["topology_status"] == "PASS", "notes": "Reference comparison performed only after objective and candidate domain were fixed."})
        tight_result = solve_role_model(case_id, tight=True, raw_root=case_raw)
        loose_result = solve_role_model(case_id, tight=False, raw_root=case_raw)
        solver_rows.extend([tight_result, loose_result])
        if loose_result["selected_assignment"] != correct_order[0]["assignment_id"]:
            raise RuntimeError(f"solver/enumeration selection mismatch for {case_id}")
        reference_aid = f"{case_id}-assignment-01"
        condition_data = [
            ("TIGHT_NO_SPP", "tight", 1, True, False, "NOT_RUN_NEUTRAL_UNIQUE_ENUMERATION", reference_aid, 1, True, "SCAFFOLD_DETERMINED"),
            ("TIGHT_CORRECT_SPP", "tight", 1, True, True, tight_result["solver_status"], tight_result["selected_assignment"], 1, True, "SPP_HAS_NO_SELECTION_DEGREE_OF_FREEDOM"),
            ("LOOSE_NO_SPP", "loose", 2, False, False, "NO_UNIQUE_PREFERENCE", NA, "NO_UNIQUE_PREFERENCE", NA, "All feasible assignments tied; solver tie-breaking is not a prediction."),
            ("LOOSE_CORRECT_SPP", "loose", 2, False, True, loose_result["solver_status"], loose_result["selected_assignment"], next(i+1 for i,a in enumerate(correct_order) if a["assignment_id"] == reference_aid), correct_order[0]["assignment_id"] == reference_aid, "Correct target-excluded SPP; lower score preferred."),
            ("LOOSE_PERTURBED_SPP", "loose", 2, False, True, "EXHAUSTIVE_CONTROL_ENUMERATION", perturbed_order[0]["assignment_id"], next(i+1 for i,a in enumerate(perturbed_order) if a["assignment_id"] == reference_aid), perturbed_order[0]["assignment_id"] == reference_aid, "PERTURBED_SPP_CONTROL swaps only cation-anion curve identities; it is not retrieval evidence."),
        ]
        for condition, tightness, feasible, forced, used, status, selected, ref_rank, ref_top1, note in condition_data:
            ev = evaluations.get(selected, {})
            relaxed = relax_archive.get(selected, {})
            factorial.append({
                "case_id": case_id, "composition": formula, "family": "oxide perovskite" if x == "O" else "halide perovskite",
                "condition": condition, "scaffold_id": f"frozen_{case_id}_fixed_roles" if tightness == "tight" else "cubic_perovskite_variable_cation_v1",
                "scaffold_tightness": tightness.upper(), "feasible_structure_count": feasible, "reference_forced_by_search_space": forced,
                "spp_used": used, "spp_coverage_class": coverage_class, "solver_status": status, "selected_assignment": selected,
                "reference_rank": ref_rank, "reference_top1": ref_top1, "reference_match": matcher.fit(candidate_structure(case_id, selected), reference) if selected != NA else NA,
                "SCA_parse": ev.get("parse_status", NA), "SCA_space_group": ev.get("detected_space_group", NA), "SCA_topology": ev.get("topology_status", NA),
                "SCA_minimum_distance_A": ev.get("minimum_distance_A", NA), "CHGNet_converged": relaxed.get("converged", NA),
                "relaxed_reference_match": relaxed.get("reference_structure_match", NA), "volume_change_percent": relaxed.get("volume_change_percent", NA),
                "solve_time_s": loose_result["solve_time_s"] if condition == "LOOSE_CORRECT_SPP" else (tight_result["solve_time_s"] if condition == "TIGHT_CORRECT_SPP" else 0.0), "notes": note,
            })
        for aid in sorted({reference_aid, correct_order[0]["assignment_id"], perturbed_order[0]["assignment_id"]}):
            archived = relax_archive[aid]
            relax_rows.append({"case_id": case_id, "assignment_id": aid, "roles": ";".join(c for c, a in (("reference-compatible", reference_aid), ("correct-SPP-selected", correct_order[0]["assignment_id"]), ("perturbed-SPP-selected", perturbed_order[0]["assignment_id"])) if a == aid), **archived, "SCA_relaxed_topology": archived["topology"], "StructureMatcher_relaxed_reference": archived["reference_structure_match"]})
        hashes = []
        for path in sorted(case_raw.rglob("*")):
            if path.is_file() and path.name != "hashes.csv":
                hashes.append({"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size})
        write_csv(case_raw / "hashes.csv", hashes, ["path", "sha256", "bytes"])
        write_json(case_raw / "software_versions.json", {"Skill-Loop-CSP_commit": git_commit(ROOT), "QLIP_commit": git_commit(ROOT.parent / "qlip"), "SCA_commit": git_commit(ROOT.parent / "Structured_Crystal_Analyser"), "Gurobi": gp_version()})
    write_csv(OUT / "03_scaffold_spp" / "CASE_SELECTION.csv", case_selection, list(case_selection[0]))
    write_csv(OUT / "03_scaffold_spp" / "FEASIBLE_ASSIGNMENT_SCORES.csv", score_rows, list(score_rows[0]))
    write_csv(OUT / "03_scaffold_spp" / "SCA_CANDIDATE_RESULTS.csv", sca_rows, list(sca_rows[0]))
    write_csv(OUT / "03_scaffold_spp" / "CANDIDATE_REFERENCE_COMPARISON.csv", comparison_rows, list(comparison_rows[0]))
    write_csv(OUT / "03_scaffold_spp" / "SOLVER_CONFIRMATION.csv", solver_rows, list(solver_rows[0]))
    write_csv(OUT / "03_scaffold_spp" / "SCAFFOLD_SPP_FACTORIAL.csv", factorial, list(factorial[0]))
    write_csv(OUT / "03_scaffold_spp" / "ABLATION_RELAXATION_RESULTS.csv", relax_rows, list(relax_rows[0]))
    build_retrieval_audit(case_selection)
    return {"case_selection": case_selection, "scores": score_rows, "factorial": factorial, "solver": solver_rows, "relaxation": relax_rows}


def gp_version() -> str:
    try:
        import gurobipy as gp
        return ".".join(map(str, gp.gurobi.version()))
    except Exception as exc:
        return f"unavailable:{exc}"


def build_retrieval_audit(case_selection: list[dict[str, Any]]) -> None:
    retrieval_rows, pair_rows = [], []
    for case in case_selection:
        case_id = case["case_id"]
        retrieval_path = GRID8 / "spp" / case_id / "retrieval.json"
        retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
        selected = retrieval["selected"]
        for item in selected:
            retrieval_rows.append({
                "case_id": case_id, "query": spp.query_text(case_id), "retrieval_corpus_version": "Crystal-DB phase6_mp_10k / production BGE-M3 robocrys",
                "target_exclusion": retrieval["target_exclusion_protocol"], "eligible_count": NA, "retrieved_count": len(selected),
                "retrieved_id": item["structure_id"], "retrieval_score": item["score"], "SPP_structure_used": True,
                "fallback_supplementation_status": item["retrieval_purpose"], "exact_DB_ID_leakage": False,
                "raw_hash_duplicate_tested": False, "canonical_duplicate_tested": False, "StructureMatcher_equivalent_target_tested": False,
                "same_formula_different_polymorph": False, "same_family": NA,
                "notes": "Exact reduced-composition exclusion was enforced. Other leakage categories were not established by this run and are not called zero.",
            })
        manifest = next(r for r in rows(GRID8 / "SPP_SOURCE_MANIFEST.csv") if r["case_id"] == case_id)
        required = manifest["required_pairs"].split(";")
        covered = set(manifest["covered_pairs"].split(";"))
        for pair in required:
            matching = [i for i in selected if pair in chemical_pairs(i["reduced_formula"])]
            pair_rows.append({
                "case_id": case_id, "pair": pair, "covered": pair in covered, "evidence_record_count": len(matching),
                "evidence_ids": ";".join(i["structure_id"] for i in matching),
                "coverage_class": case["SPP_coverage_class"], "invented_or_zeroed": False,
                "notes": "Numerical POT exists" if pair in covered else "Missing target-excluded co-occurrence; case excluded.",
            })
    write_csv(OUT / "03_scaffold_spp" / "RETRIEVAL_RESULTS.csv", retrieval_rows, list(retrieval_rows[0]))
    write_csv(OUT / "03_scaffold_spp" / "SPP_PAIR_COVERAGE.csv", pair_rows, list(pair_rows[0]))


def chemical_pairs(formula: str) -> set[str]:
    from pymatgen.core import Composition
    elements = [str(e) for e in Composition(formula).elements]
    return {spp.canonical_pair(a, b) for a in elements for b in elements}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    build_execution_block()
    reference = build_reference_block()
    factorial = build_factorial_block()
    write_json(OUT / "_build_state.json", {"reference": {"rows": len(reference["benchmark"])}, "factorial": {"rows": len(factorial["factorial"])}})
    print(f"PASS core build: {OUT}")


if __name__ == "__main__":
    main()
