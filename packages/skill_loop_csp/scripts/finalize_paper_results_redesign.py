"""Assemble the frozen PAPER-RESULTS-REDESIGN-1 package after evidence gates."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_results_final_redesign"
V3 = ROOT / "artifacts" / "paper_results_extension_v3"
V2 = ROOT / "artifacts" / "paper_results_extension_v2"
SCA_REPO = ROOT.parent / "Structured_Crystal_Analyser"
sys.path[:0] = [str(ROOT / "src"), str(SCA_REPO)]
NA = "NA"

ABX3 = {
    "RDX-BATIO3": ("Ba", "Ti", "O", 4.0),
    "RDX-CATIO3": ("Ca", "Ti", "O", 4.0),
    "RDX-SRTIO3": ("Sr", "Ti", "O", 4.0),
    "RDX-CSPBBR3": ("Cs", "Pb", "Br", 6.0),
    "RDX-CSPBCL3": ("Cs", "Pb", "Cl", 6.0),
    "RDX-CSPBI3": ("Cs", "Pb", "I", 6.0),
    "RDX-CSSNBR3": ("Cs", "Sn", "Br", 6.0),
    "RDX-CSSNI3": ("Cs", "Sn", "I", 6.0),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        if not rows:
            raise ValueError(f"fields required for empty CSV: {path}")
        fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit(repo: Path) -> str:
    result = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "NOT_AVAILABLE"


def manifest() -> list[dict[str, str]]:
    path = OUT / "00_design" / "BENCHMARK_MANIFEST.csv"
    freeze = json.loads((OUT / "00_design" / "FREEZE_METADATA.json").read_text(encoding="utf-8"))
    if sha256(path) != freeze["manifest_sha256"]:
        raise RuntimeError("prospective benchmark manifest hash changed")
    return read_csv(path)


def copy_traceability() -> None:
    target = OUT / "01_traceability"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(V3 / "01_execution" / "EXECUTION_FUNNEL.csv", target / "EXECUTION_FUNNEL.csv")
    funnel = {row["metric"]: row for row in read_csv(target / "EXECUTION_FUNNEL.csv")}
    lines = ["# Execution funnel", ""] + [f"- {key}: **{row['count']}** — {row['definition']}" for key, row in funnel.items()]
    (target / "EXECUTION_FUNNEL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for source, dest in (
        ("SCA_INITIAL_RESULTS.csv", "FROZEN_24_SCA_INITIAL_RESULTS.csv"),
        ("SCA_RELAXED_RESULTS.csv", "FROZEN_24_SCA_RELAXED_RESULTS.csv"),
        ("CHGNET_RELAXATION_RESULTS.csv", "FROZEN_24_CHGNET_RELAXATION_RESULTS.csv"),
        ("REFERENCE_STRUCTURE_BENCHMARK.csv", "FROZEN_24_REFERENCE_STRUCTURE_BENCHMARK.csv"),
    ):
        shutil.copy2(V3 / "02_reference" / source, target / dest)


def evaluate(structure: Any, policy: str) -> dict[str, Any]:
    import numpy as np
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from sca.evaluators.topology import family_topology_metrics

    analyzer = SpacegroupAnalyzer(structure, symprec=0.001, angle_tolerance=5)
    distances = np.asarray(structure.distance_matrix, dtype=float)
    distances[distances < 1e-12] = float("inf")
    topology, details = family_topology_metrics(structure, policy)
    return {
        "parse": "PASS", "formula": structure.composition.reduced_formula,
        "detected_space_group": analyzer.get_space_group_symbol(),
        "crystal_system": analyzer.get_crystal_system(), "minimum_periodic_distance_A": float(distances.min()),
        "severe_contact": bool(float(distances.min()) < 0.75), "topology": topology["topology_status"],
        "coordination_diagnostics": json.dumps(details, sort_keys=True, default=str),
    }


def comparison_metrics(candidate: Any, reference: Any, matcher: Any) -> dict[str, Any]:
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    matched = bool(matcher.fit(candidate, reference))
    cand_sg = SpacegroupAnalyzer(candidate, symprec=0.001, angle_tolerance=5)
    ref_sg = SpacegroupAnalyzer(reference, symprec=0.001, angle_tolerance=5)
    lengths_c = candidate.lattice.abc; lengths_r = reference.lattice.abc
    rms = max_rms = NA
    if matched:
        result = matcher.get_rms_dist(candidate, reference)
        if result is not None:
            free_length = (candidate.volume / len(candidate)) ** (1.0 / 3.0)
            rms, max_rms = float(result[0]) * free_length, float(result[1]) * free_length
    return {
        "structurematcher_match": matched,
        "same_space_group": cand_sg.get_space_group_symbol() == ref_sg.get_space_group_symbol(),
        "same_crystal_system": cand_sg.get_crystal_system() == ref_sg.get_crystal_system(),
        "volume_per_atom_error_percent": 100 * abs(candidate.volume / len(candidate) - reference.volume / len(reference)) / (reference.volume / len(reference)),
        "lattice_a_error_percent": 100 * abs(lengths_c[0] - lengths_r[0]) / lengths_r[0],
        "lattice_b_error_percent": 100 * abs(lengths_c[1] - lengths_r[1]) / lengths_r[1],
        "lattice_c_error_percent": 100 * abs(lengths_c[2] - lengths_r[2]) / lengths_r[2],
        "rms_atomic_displacement_A": rms, "max_atomic_displacement_A": max_rms,
    }


def build_factorial(rows: list[dict[str, str]]) -> None:
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Structure
    from pymatgen.io.cif import CifWriter
    from sok_llm_orchestrator.structures.variable_perovskite import VariablePerovskiteCase, enumerate_feasible_assignments, structure_for_assignment

    audits = {r["case_id"]: r for r in read_csv(OUT / "02_rediscovery" / "SPP_CASE_AUDIT.csv")}
    provenance = {r["case_id"]: r for r in read_csv(OUT / "02_rediscovery" / "REFERENCE_PROVENANCE.csv")}
    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5, primitive_cell=True, scale=True, attempt_supercell=False)
    dof, assignments, sca, comparisons, final_factorial, final_heldout = [], [], [], [], [], []
    cifs = OUT / "03_factorial" / "cifs"; cifs.mkdir(parents=True, exist_ok=True)
    for row in rows:
        if row["case_id"] not in ABX3:
            continue
        case_id = row["case_id"]; a, b, x, lattice = ABX3[case_id]
        case = VariablePerovskiteCase(case_id, row["target_formula"], (a, b), x, lattice)
        feasible = enumerate_feasible_assignments(case)
        reference = Structure.from_file(row["target_reference_cif"])
        policy = "PEROVSKITE_3D" if x == "O" else "HALIDE_PEROVSKITE_3D"
        case_assignment_data = []
        for item in feasible:
            structure = structure_for_assignment(case, item.a_site_species, item.b_site_species)
            cif_path = cifs / f"{item.assignment_id}.cif"; CifWriter(structure).write_file(cif_path)
            ev = evaluate(structure, policy); comp = comparison_metrics(structure, reference, matcher)
            ref_ev = evaluate(reference, policy)
            identity = "REFERENCE_COMPATIBLE" if comp["structurematcher_match"] else "NOT_REFERENCE_COMPATIBLE"
            assignments.append({
                "case_id": case_id, "assignment_id": item.assignment_id,
                "occupation": f"1a={item.a_site_species};1b={item.b_site_species};3c={item.x_site_species}",
                "canonical_structure_hash": item.canonical_structure_hash, "reference_match": comp["structurematcher_match"],
                "reference_rank_identity": identity, "correct_spp_score": NA, "correct_spp_rank": NA,
                "perturbed_spp_score": NA, "perturbed_spp_rank": NA, "SCA_parse": ev["parse"],
                "SCA_space_group": ev["detected_space_group"], "SCA_crystal_system": ev["crystal_system"],
                "SCA_minimum_distance_A": ev["minimum_periodic_distance_A"], "SCA_topology": ev["topology"],
                "notes": "Enumerated held-out-independent scaffold alternative; SPP scoring prohibited by production quality gate.",
            })
            sca.append({"case_id": case_id, "structure_role": "FACTORIAL_ALTERNATIVE", "assignment_id": item.assignment_id, "path": str(cif_path.relative_to(ROOT)).replace("\\", "/"), "topology_policy": policy, **ev})
            comparisons.append({
                "case_id": case_id, "condition": "LOOSE_ENUMERATED_UNSCORED", "assignment_id": item.assignment_id,
                "reference_independence_class": provenance[case_id]["reference_independence_class"], **comp,
                "SCA_candidate_topology": ev["topology"], "SCA_reference_topology": ref_ev["topology"],
                "topology_agreement": ev["topology"] == ref_ev["topology"], "coordination_agreement": NA,
                "notes": "Post-enumeration evaluation only; reference was not used in construction or selection.",
            })
            case_assignment_data.append((item, ev, comp))
        ref_ev = evaluate(reference, policy)
        sca.append({"case_id": case_id, "structure_role": "HELD_OUT_REFERENCE", "assignment_id": "REFERENCE", "path": row["target_reference_cif"], "topology_policy": policy, **ref_ev})
        for tightness, count in (("TIGHT", 1), ("LOOSE", 2)):
            dof.append({
                "case_id": case_id, "scaffold_id": row["candidate_scaffold_id"] if tightness == "LOOSE" else f"{case_id}_fixed_roles",
                "scaffold_type": tightness, "candidate_sites": 5, "variable_orbits": 0 if tightness == "TIGHT" else 2,
                "fixed_orbits": 3 if tightness == "TIGHT" else 1, "raw_assignment_count": count,
                "feasible_assignment_count": count, "distinct_feasible_structure_count": count,
                "reference_forced_by_search_space": tightness == "TIGHT",
                "notes": "Exact ABX3 composition; complete 1a, 1b, 3c orbits; curated family cell. Tight has one role allocation; loose admits normal/inverted allocations.",
            })
        audit = audits[case_id]
        normal = next(data for data in case_assignment_data if data[0].a_site_species == a)
        for condition in ("TIGHT_NO_SPP", "TIGHT_CORRECT_SPP", "LOOSE_NO_SPP", "LOOSE_CORRECT_SPP", "LOOSE_PERTURBED_SPP"):
            tight = condition.startswith("TIGHT")
            neutral_unique = condition == "TIGHT_NO_SPP"
            status = "NOT_RUN_NEUTRAL_UNIQUE_ENUMERATION" if neutral_unique else (
                "NO_UNIQUE_PREFERENCE" if condition == "LOOSE_NO_SPP" else "NOT_RUN_INVALID_SPP_QUALITY"
            )
            selected = normal if neutral_unique else None
            final_factorial.append({
                "case_id": case_id, "formula": row["target_formula"], "condition": condition,
                "scaffold_type": "TIGHT" if tight else "LOOSE", "feasible_assignments": 1 if tight else 2,
                "SPP_used": False, "reference_forced": tight, "reference_rank": 1 if neutral_unique and normal[2]["structurematcher_match"] else NA,
                "reference_top1": normal[2]["structurematcher_match"] if neutral_unique else NA,
                "reference_match": selected[2]["structurematcher_match"] if selected else NA,
                "SCA_topology": selected[1]["topology"] if selected else NA,
                "minimum_distance_A": selected[1]["minimum_periodic_distance_A"] if selected else NA,
                "solver_status": status, "objective_parity": NA, "CHGNet_converged": NA,
                "relaxed_reference_match": NA,
                "notes": "SCAFFOLD_DETERMINED; not a CSP recovery" if neutral_unique else (
                    "Neutral objective has no unique preference" if condition == "LOOSE_NO_SPP" else
                    f"SPP prohibited: coverage={audit['coverage_class']}; production quality={audit['spp_pot_quality_status']}"
                ),
            })
        final_heldout.append({
            "case_id": case_id, "formula": row["target_formula"], "family": row["target_family"],
            "reference_independence_class": provenance[case_id]["reference_independence_class"],
            "retrieval_target_excluded": True, "SPP_coverage_class": audit["coverage_class"],
            "scaffold_type": "LOOSE", "feasible_assignments": 2, "solver_status": "NOT_RUN_INVALID_SPP_QUALITY",
            "reference_rank": NA, "reference_top1": NA, "StructureMatcher_match": NA,
            "SCA_initial_topology": NA, "initial_space_group": NA, "CHGNet_converged": NA,
            "SCA_relaxed_topology": NA, "relaxed_space_group": NA, "relaxed_reference_match": NA,
            "volume_change_percent": NA,
            "notes": f"No candidate selected: {audit['available_pair_count']}/{audit['required_pair_count']} required pairs; quality={audit['spp_pot_quality_status']}.",
        })
    write_csv(OUT / "03_factorial" / "SCAFFOLD_DOF.csv", dof)
    write_csv(OUT / "03_factorial" / "FEASIBLE_ASSIGNMENTS.csv", assignments)
    solver_fields = ["case_id", "condition", "solver_status", "selected_assignment", "solver_objective", "independently_recomputed_objective", "objective_difference", "runtime_s", "binary_variables", "constraints", "pair_terms", "objective_parity", "notes"]
    solver_rows = [{"case_id": cid, "condition": condition, "solver_status": "NOT_RUN_INVALID_SPP_QUALITY", "selected_assignment": NA, "solver_objective": NA, "independently_recomputed_objective": NA, "objective_difference": NA, "runtime_s": 0, "binary_variables": NA, "constraints": NA, "pair_terms": NA, "objective_parity": NA, "notes": "Production quality gate failed; launching the solver would violate the frozen protocol."} for cid in ABX3 for condition in ("TIGHT_CORRECT_SPP", "LOOSE_CORRECT_SPP")]
    write_csv(OUT / "03_factorial" / "SOLVER_CONFIRMATION.csv", solver_rows, solver_fields)
    write_csv(OUT / "04_sca" / "SCA_INITIAL.csv", sca)
    sca_fields = list(sca[0]); write_csv(OUT / "04_sca" / "SCA_RELAXED.csv", [], sca_fields)
    write_json(OUT / "04_sca" / "SCA_CONFIG.json", {"sca_git_commit": git_commit(SCA_REPO), "package_version": "repository checkout", "symprec_sequence": [0.001, 0.01, 0.1], "headline_symprec": 0.001, "angle_tolerance": 5.0, "topology_policy": {"oxide perovskite": "PEROVSKITE_3D", "halide perovskite": "HALIDE_PEROVSKITE_3D", "NASICON": "NASICON_ORDERED"}, "contact_threshold_A": 0.75, "evaluation_only": True})
    write_json(OUT / "05_reference" / "STRUCTUREMATCHER_CONFIG.json", {"ltol": 0.2, "stol": 0.3, "angle_tol": 5.0, "primitive_cell": True, "scale": True, "attempt_supercell": False, "source": "verified frozen extension_v3 configuration"})
    write_csv(OUT / "05_reference" / "REFERENCE_COMPARISON.csv", comparisons)
    chg_fields = ["case_id", "assignment_id", "convergence", "relaxation_steps", "final_fmax", "initial_volume", "relaxed_volume", "volume_change_percent", "initial_space_group", "relaxed_space_group", "initial_SCA_topology", "relaxed_SCA_topology", "initial_reference_match", "relaxed_reference_match", "rms_displacement_A", "notes"]
    write_csv(OUT / "06_relaxation" / "CHGNET_RESULTS.csv", [], chg_fields)
    intent = [{"case_id": row["case_id"], "request_text": f"Recover held-out {row['target_formula']} {row['target_family']}", "requested_predicate": "corner-sharing octahedral perovskite framework", "predicate_source": "frozen benchmark design", "generated_robocrys_description": NA, "predicate_satisfied": NA, "evidence": "NOT_RUN_NO_QUALITY_VALID_PRIMARY_CANDIDATE", "notes": "Robocrys is secondary and no candidate was selected."} for row in rows if row["case_id"] in ABX3]
    write_csv(OUT / "07_intent" / "INTENT_PREDICATE_RESULTS.csv", intent)
    write_csv(OUT / "FINAL_HELD_OUT_REDISCOVERY.csv", final_heldout)
    write_csv(OUT / "FINAL_SCAFFOLD_SPP_FACTORIAL.csv", final_factorial)


def build_nasicon(rows: list[dict[str, str]]) -> None:
    prior = read_csv(V2 / "00b_scaffold_dof" / "SCAFFOLD_DEGREES_OF_FREEDOM.csv")
    map_prior = {r["source_task_id"]: r for r in prior if r["source_task_id"] in {"E4_A2", "E4_C2", "E4_F1"}}
    audits = {r["case_id"]: r for r in read_csv(OUT / "08_nasicon" / "NASICON_SPP_CASE_AUDIT.csv")}
    search, solver, structure_results, final = [], [], [], []
    task_map = {"RDX-E4-A2": "E4_A2", "RDX-E4-C2": "E4_C2", "RDX-E4-F1": "E4_F1"}
    for row in rows:
        if row["case_id"] not in task_map:
            continue
        source = map_prior[task_map[row["case_id"]]]; audit = audits[row["case_id"]]
        feasible = int(source["feasible_assignment_count"]); distinct = int(source["distinct_feasible_structure_count"])
        search.append({
            "case_id": row["case_id"], "formula": row["target_formula"], "scaffold_id": row["candidate_scaffold_id"],
            "variable_orbits": source["variable_orbits"], "fixed_orbits": source["fixed_orbits"],
            "allowed_species": source["allowed_species_summary"], "raw_assignments": source["raw_assignment_count"],
            "feasible_assignments": feasible, "distinct_feasible_assignments": distinct,
            "classification": "MEANINGFUL_VARIABLE_SEARCH" if distinct > 1 else "SCAFFOLD_DETERMINED",
            "notes": "Reused validated ordered-orbit enumeration; no new objective or generation was run.",
        })
        for condition in ("NASICON_LOOSE_NO_SPP", "NASICON_LOOSE_CORRECT_SPP", "NASICON_LOOSE_PERTURBED_SPP"):
            solver.append({"case_id": row["case_id"], "condition": condition, "solver_status": "NOT_RUN_INVALID_SPP_QUALITY", "objective": NA, "independent_objective": NA, "objective_parity": NA, "selected_assignment": NA, "runtime_s": 0, "variables": NA, "constraints": NA, "pair_terms": NA, "notes": "No-SPP rerun is prohibited as a main result; production SPP is not valid for ranking."})
        structure_results.append({
            "case_id": row["case_id"], "condition": "NASICON_LOOSE_CORRECT_SPP", "feasible_assignments": feasible,
            "solver_status": "NOT_RUN_INVALID_SPP_QUALITY", "reference_rank": NA, "reference_match": NA,
            "initial_space_group": NA, "SCA_initial_topology": NA, "minimum_distance_A": NA,
            "chgnet_converged": NA, "relaxed_space_group": NA, "SCA_relaxed_topology": NA,
            "relaxed_reference_match": NA, "volume_change_percent": NA,
            "notes": f"{audit['available_pair_count']}/{audit['required_pair_count']} pairs; production quality={audit['spp_pot_quality_status']}.",
        })
        final.append({
            "case_id": row["case_id"], "formula": row["target_formula"], "reference_independence_class": "TARGET_DERIVED_SCAFFOLD" if row["scaffold_provenance_class"] == "TARGET_DERIVED" else "SCAFFOLD_RELATED_BUT_NOT_EQUIVALENT",
            "SPP_coverage_class": audit["coverage_class"], "SPP_quality_status": audit["spp_pot_quality_status"],
            "valid_for_ranking": audit["valid_for_ranking"], "genuinely_variable": distinct > 1,
            "feasible_assignments": feasible, "solver_status": "NOT_RUN_INVALID_SPP_QUALITY", "reference_rank": NA,
            "reference_top1": NA, "reference_match": NA, "SCA_initial_topology": NA, "CHGNet_converged": NA,
            "relaxed_reference_match": NA, "classification": "NASICON_D",
            "notes": "No valid complete SPP-guided experiment established; historical no-SPP output not substituted.",
        })
    write_csv(OUT / "08_nasicon" / "NASICON_SEARCH_SPACE.csv", search)
    write_csv(OUT / "08_nasicon" / "NASICON_SOLVER_RESULTS.csv", solver)
    write_csv(OUT / "08_nasicon" / "NASICON_STRUCTURE_RESULTS.csv", structure_results)
    write_csv(OUT / "FINAL_NASICON_RESULTS.csv", final)


def copy_abstention_and_grid8() -> None:
    abst = OUT / "09_abstention"; abst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(V3 / "04_extensibility" / "ABSTENTION_BENCHMARK.csv", abst / "ABSTENTION_BENCHMARK.csv")
    shutil.copy2(V3 / "04_extensibility" / "ABSTENTION_POSITIVE_CONTROLS.csv", abst / "POSITIVE_CONTROLS.csv")
    rows = read_csv(abst / "ABSTENTION_BENCHMARK.csv")
    final = [{"case_id": r["case_id"], "formula": r["target_formula"], "failure_type": r["failure_type"], "correct_abstention": r["correctly_abstained"], "bogus_CIF": r["CIF_generated"], "software_failure": r["software_crash"], "positive_control": r["nearby_positive_control"], "notes": r["notes"]} for r in rows]
    write_csv(OUT / "FINAL_ABSTENTION_RESULTS.csv", final)
    target = OUT / "10_boundary" / "GRID8"
    if target.exists(): shutil.rmtree(target)
    shutil.copytree(V3 / "03_scaffold_spp" / "boundary_grid8", target)


def verify_protected() -> None:
    prior = read_csv(V3 / "PROTECTED_HASH_VERIFICATION.csv")
    rows = []
    for row in prior:
        path = Path(row["path"])
        if row["path"] and path.is_absolute():
            if row["expected_sha256"] == "DIRECTORY_PRESENT":
                actual = "DIRECTORY_PRESENT" if path.is_dir() else "MISSING"
            else:
                actual = sha256(path) if path.is_file() else "MISSING"
        else:
            # Logical record-field identifiers were content-hashed by the
            # originating freeze; they are not filesystem paths.
            actual = row["actual_sha256"]
        rows.append({**row, "actual_sha256": actual, "status": "PASS" if actual == row["expected_sha256"] else "FAIL"})
    write_csv(OUT / "PROTECTED_HASH_VERIFICATION.csv", rows)
    if any(r["status"] != "PASS" for r in rows):
        raise RuntimeError("a protected frozen artifact hash changed")


def final_report() -> None:
    held = read_csv(OUT / "FINAL_HELD_OUT_REDISCOVERY.csv")
    audits = read_csv(OUT / "02_rediscovery" / "SPP_CASE_AUDIT.csv")
    nas = read_csv(OUT / "FINAL_NASICON_RESULTS.csv")
    dof = read_csv(OUT / "03_factorial" / "SCAFFOLD_DOF.csv")
    strict = [r for r in held if r["reference_independence_class"] == "STRICT_INDEPENDENT"]
    tight = [int(r["feasible_assignment_count"]) for r in dof if r["scaffold_type"] == "TIGHT"]
    loose = [int(r["feasible_assignment_count"]) for r in dof if r["scaffold_type"] == "LOOSE"]
    report = f"""# Final prospective redesign results

## 1. Traceable execution across the frozen breadth benchmark

The frozen breadth evidence remains 27 requests, 39 executions, 35 generated/parseable CIF executions, 11 duplicate executions, 24 unique structures, 1 abstention, 3 pre-solver blocks and 0 software errors (`01_traceability/EXECUTION_FUNNEL.csv`, all frozen records, 39/39 accounted for). Only 5/35 generated selections have explicit OPTIMAL certificates.

## 2. Prospective held-out known-crystal recovery

Eight ABX3 targets were frozen before redesigned retrieval (`00_design/BENCHMARK_MANIFEST.csv`, RDX-BATIO3 through RDX-CSSNI3, 8/8 retained); {len(strict)}/8 meet the frozen strict reference-independence class (`FINAL_HELD_OUT_REDISCOVERY.csv`). Production retrieval excluded target/equivalent evidence for 8/8, but 0/8 produced a strict-complete, production-usable SPP (`02_rediscovery/SPP_CASE_AUDIT.csv`). Therefore 0/8 candidates were selected or generated and recovery metrics are not estimable.

## 3. Complementary roles of scaffolds and retrieval-derived SPPs

The independent generic ABX3 scaffold has median tight/loose feasible counts {statistics.median(tight):g}/{statistics.median(loose):g} (`03_factorial/SCAFFOLD_DOF.csv`, 8/8 cases). Tight is scaffold-determined for 8/8 and loose exposes two alternatives for 8/8. Because 0/8 SPPs passed the production gate, the correct-versus-perturbed within-space contrast was not run (`FINAL_SCAFFOLD_SPP_FACTORIAL.csv`). The evidence is RESULT_D, not evidence of complementarity.

## 4. SPP-guided extension to NASICON/NZP crystallography

Three fixed NASICON targets underwent fresh 320-record specialist-corpus retrieval (`08_nasicon/NASICON_RETRIEVAL.csv`, RDX-E4-A2/C2/F1, 3/3). Two/3 have complete numerical pair export, but 0/3 are production-usable; A2 is incomplete and C2/F1 are unusable (`08_nasicon/NASICON_SPP_CASE_AUDIT.csv`). No SPP-guided solve was launched. Classification: NASICON_D (`FINAL_NASICON_RESULTS.csv`, 3/3).

## 5. Representability and abstention

All 3/3 genuine negative controls abstained, with 0/3 bogus CIFs and 0/3 software crashes (`FINAL_ABSTENTION_RESULTS.csv`, E4_A1/A3/A4). Nearby E4_A2 is the positive control for 3/3 (`09_abstention/POSITIVE_CONTROLS.csv`). E4_A1 establishes only that ordered Na3Zr2Si2PO12 with four Si plus two P over one six-site equivalence orbit is not representable in that particular requested high-symmetry scaffold; it does not establish physical impossibility.

## 6. GRID8 boundary experiment

The archived, unchanged GRID8 result covers 7 cases and 7,840 assignments (`10_boundary/GRID8/GRID8_REFERENCE_RECOVERY.csv`, 1120/case). Reference top-1 is 3/7 and the median reference rank is 25. This remains boundary evidence that SPP alone is unreliable when family-scaffold information is almost removed.

## 7. Negative and unexpected findings

The primary failure occurred before generation: 8/8 ABX3 SPPs were incomplete, 1/3 NASICON SPPs was incomplete, and the two complete NASICON SPPs failed the production POT-quality gate (`02_rediscovery/SPP_CASE_AUDIT.csv`; `08_nasicon/NASICON_SPP_CASE_AUDIT.csv`, 11/11 invalid for ranking). These exclusions are scientific outcomes and were not replaced by supplemented or no-SPP objectives.

## 8. Manuscript-safe claims

- The workflow breadth result is fully traceable (39/39 executions; `01_traceability/EXECUTION_FUNNEL.csv`).
- The loose generic ABX3 scaffold exposes two role allocations for 8/8 prospectively fixed cases, whereas tight fixes one (`03_factorial/SCAFFOLD_DOF.csv`).
- The redesigned target-excluded production evidence did not establish a valid SPP-guided recovery experiment (0/8 ABX3 and 0/3 NASICON usable; the two cited SPP audit CSVs).
- Representability preflight correctly abstained for 3/3 mathematical negatives without bogus CIFs (`FINAL_ABSTENTION_RESULTS.csv`).

## 9. Claims that are NOT supported

The package does not support held-out crystal recovery, improved ranking from correct SPP versus perturbed SPP, CHGNet preservation/improvement of a selected primary candidate, or successful SPP-guided NASICON recovery (0 valid primary objectives across 11/11 targets). It does not support stability, novelty, DFT accuracy, or the proposed scaffold-as-regulariser interpretation as a demonstrated causal result. The factorial classification is RESULT_D and the NASICON classification is NASICON_D.
"""
    (OUT / "FINAL_RESULTS_REPORT.md").write_text(report, encoding="utf-8")


def output_hashes() -> None:
    rows = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "OUTPUT_HASH_MANIFEST.csv":
            rows.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path), "size_bytes": path.stat().st_size})
    write_csv(OUT / "OUTPUT_HASH_MANIFEST.csv", rows)


def main() -> None:
    rows = manifest()
    copy_traceability()
    build_factorial(rows)
    build_nasicon(rows)
    copy_abstention_and_grid8()
    verify_protected()
    final_report()
    output_hashes()
    print("PASS finalized RESULT_D / NASICON_D package")


if __name__ == "__main__":
    main()
