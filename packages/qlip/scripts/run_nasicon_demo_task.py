"""Run and validate one protected NASICON demonstration task."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure

from qlip.core.solve import solve
from qlip.core.validate import validate_request
from qlip.paper_diversity.record_identity import canonical_record_key
from qlip.paper_diversity.smoke_preparation import (
    explicit_charge_assumptions as charge_assumptions,
    load_frozen_e4_tasks,
    resolve_skill_loop_root,
    sha256_file as sha_file,
    sha256_text as sha_text,
    structured_intent_hash,
    task_orbits,
)
from qlip.scaffolds import get_scaffold
from qlip.scaffolds.occupation import preflight_ordered_occupation


TASK_ORDER = ("E4_A2", "E4_C2", "E4_F1")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_json(command: list[str], workdir: Path, timeout: int = 180) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=workdir, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Command returned non-JSON output: {' '.join(command)}\n{completed.stdout}\n{completed.stderr}") from exc


def expanded_formula(counts: dict[str, int]) -> str:
    order = ("Li", "Na", "Zr", "Ti", "Sc", "Hf", "Si", "P", "O")
    return "".join(symbol + (str(counts[symbol]) if counts[symbol] != 1 else "") for symbol in order if counts.get(symbol))


def retrieval(skill: Path, task: dict[str, str], task_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    crystal = skill.parent / "Crystal-DB"
    python = crystal / ".venv" / "Scripts" / "python.exe"
    db_path = skill / "data" / "corpora" / "nasicon_specialist_all_targets_out_v3" / "crystaldb.sqlite"
    result = run_json([
        str(python), "-m", "crystal_db", "text-search", "--db", str(db_path), "--query", task["natural_language_request"],
        "--k", "10", "--engine", "lmstudio", "--model", "text-embedding-bge-m3", "--model-version", "lmstudio_v1",
        "--text-engine", "robocrys", "--text-view", "robocrys", "--hybrid", "false", "--show-text-top", "0", "--format", "json",
    ], crystal)
    (task_dir / "retrieval.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    evidence: list[dict[str, Any]] = []
    manifest = [json.loads(line) for line in (db_path.parent / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    by_key = {canonical_record_key(row["source"], row["source_id"]): row for row in manifest}
    for neighbor in result.get("neighbors", []):
        row = conn.execute("select p.source,p.source_id from provenance p where p.structure_id=?", (neighbor["structure_id"],)).fetchone()
        if row is None:
            raise RuntimeError(f"Retrieved database ID lacks provenance: {neighbor['structure_id']}")
        record = by_key.get(canonical_record_key(row["source"], row["source_id"]))
        if record is None:
            raise RuntimeError(f"Retrieved database ID cannot resolve to corpus manifest: {neighbor['structure_id']}")
        evidence.append({
            "database_structure_id": neighbor["structure_id"], "record_id": record["internal_id"], "score": neighbor["score"],
            "reduced_formula": record["reduced_formula"], "cif_sha256": record["cif_sha256"],
            "cif_path": str(db_path.parent / "cifs" / f"{record['internal_id']}.cif"),
        })
    conn.close()
    (task_dir / "retrieved_evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result, evidence


def leakage_audit(task: dict[str, str], scaffold: Any, evidence: list[dict[str, Any]], task_dir: Path) -> dict[str, Any]:
    target_formula = Composition(task["target_formula"]).reduced_formula
    exact_formula = [row["record_id"] for row in evidence if Composition(row["reduced_formula"]).reduced_formula == target_formula]
    reference = Structure.from_file(scaffold.source_cif_path)
    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5.0, primitive_cell=True, scale=True, attempt_supercell=False)
    exact_structure = []
    for row in evidence:
        candidate = Structure.from_file(row["cif_path"])
        if matcher.fit(reference, candidate):
            exact_structure.append(row["record_id"])
    payload = {"exact_formula_leakage_count": len(exact_formula), "exact_formula_record_ids": exact_formula, "exact_structure_leakage_count": len(exact_structure), "exact_structure_record_ids": exact_structure, "status": "PASS" if not exact_formula and not exact_structure else "FAIL"}
    (task_dir / "leakage_audit.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if payload["status"] != "PASS":
        raise RuntimeError(f"Exact target leakage detected: {payload}")
    return payload


def build_request(task: dict[str, str], scaffold: Any, occupation: Any, task_dir: Path) -> dict[str, Any]:
    represented = {key: int(value) for key, value in occupation.representable_composition.items() if key != "VACANCY" and int(value)}
    formula = expanded_formula(represented)
    charge = charge_assumptions(task["target_formula"])["chemistry"]
    charge["formula"] = formula
    orbits = task_orbits(task, scaffold)
    lattice = scaffold.lattice
    request = {
        "version": "1.0",
        "problem": {
            "chemistry": charge,
            "design_space": {
                "template": {"name": scaffold.scaffold_id, "lattice": {**lattice, "units": "angstrom"}},
                "sites": {
                    "mode": "explicit_fractional_sites",
                    "explicit_fractional_sites": [list(point) for point in scaffold.fractional_candidate_sites],
                    "ordered_orbits": [{"orbit_id": orbit["orbit_id"], "site_indices": list(orbit["site_indices"]), "allowed_species": list(orbit["allowed_species"]), "required_occupancy": True} for orbit in orbits],
                },
            },
            "objective": {"type": "none"},
        },
        "constraints": [], "guidance": [], "guidance_mode": "weighted_sum",
        "solver": {"name": "gurobi", "time_limit_s": 300, "mip_gap": 0.0, "threads": 1, "seed": 0, "parameters": {}},
        "artifacts": {"return_cif": True, "return_decoder_debug": False},
        "runtime": {"max_sites": len(scaffold.fractional_candidate_sites), "max_binary_vars": len(scaffold.fractional_candidate_sites) * (len(represented) + 1), "max_constraints": 5000},
        "context": {"run_id": f"nasicon_demo_{task['task_id']}", "tags": ["nasicon_demo", task["task_id"], "NO_SPP"]},
    }
    (task_dir / "solve_request.json").write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def occupation_assignment(solution: Structure, scaffold: Any) -> dict[str, str]:
    assigned: dict[int, str] = {}
    for index, frac in enumerate(scaffold.fractional_candidate_sites):
        best = None
        for site in solution:
            delta = np.asarray(site.frac_coords) - np.asarray(frac)
            delta -= np.round(delta)
            distance = float(np.linalg.norm(delta @ solution.lattice.matrix))
            candidate = (distance, site.specie.symbol)
            if best is None or candidate < best:
                best = candidate
        if best is None or best[0] > 1e-4:
            raise RuntimeError(f"Solved CIF coordinate cannot be mapped to scaffold site {index}: {best}")
        assigned[index] = best[1]
    result: dict[str, str] = {}
    for orbit in scaffold.symmetry_orbits:
        species = {assigned[int(index)] for index in orbit["site_indices"]}
        if len(species) != 1:
            raise RuntimeError(f"Decoded orbit is not symmetry closed: {orbit['orbit_id']}: {species}")
        result[orbit["orbit_id"]] = next(iter(species))
    return result


def aggregate(out: Path) -> None:
    rows = []
    for task_id in TASK_ORDER:
        path = out / "tasks" / task_id / "result.json"
        if path.is_file(): rows.append(json.loads(path.read_text(encoding="utf-8")))
    if not rows: return
    write_csv(out / "NASICON_DEMO_RESULTS.csv", rows)
    (out / "NASICON_DEMO_RESULTS.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    (out / "NASICON_DEMO_REPORT.md").write_text(
        "# Minimal NASICON demonstration\n\n" + "\n".join(
            f"- `{row['task_id']}`: **{row['engineering_smoke_status']}**, solver `{row['solver_status']}`, formula `{row['detected_formula']}`, topology `{row['topology_status']}`."
            for row in rows
        ) + "\n\nSPP status is explicitly `NO_SPP`; objectives are zero-valued feasibility objectives, not energy or stability claims.\n",
        encoding="utf-8",
    )


def run_task(task_id: str) -> dict[str, Any]:
    if task_id not in TASK_ORDER: raise ValueError(f"Unauthorized demo task: {task_id}")
    skill = resolve_skill_loop_root(); qlip = skill.parent / "qlip"; out = skill / "artifacts" / "paper_diversity_v2" / "nasicon_demo"
    prior = read_csv(out / "PRE_GENERATION_HASH_CHECK.csv")
    if not prior or any(row["status"] != "PASS" for row in prior): raise RuntimeError("Protected pre-generation gate is not green")
    tasks = load_frozen_e4_tasks(skill); task = tasks[task_id]
    manifest = {row["task_id"]: row for row in read_csv(out / "NASICON_DEMO_TASKS.csv")}; expected = manifest[task_id]
    if structured_intent_hash(task) != expected["structured_intent_hash"]: raise RuntimeError("Frozen structured intent hash changed")
    scaffold = get_scaffold(expected["scaffold_id"])
    if sha_file(Path(scaffold.source_cif_path)) != expected["scaffold_source_hash"]: raise RuntimeError("Scaffold source hash mismatch")
    orbits = task_orbits(task, scaffold)
    occupation = preflight_ordered_occupation(task["target_formula"], len(scaffold.fractional_candidate_sites), orbits)
    if not occupation.stoichiometry_representable: raise RuntimeError(f"Orbit multiplicity preflight failed: {occupation.to_dict()}")
    task_dir = out / "tasks" / task_id; task_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter(); _, evidence = retrieval(skill, task, task_dir); leakage = leakage_audit(task, scaffold, evidence, task_dir)
    request = build_request(task, scaffold, occupation, task_dir)
    validation = validate_request(request, strict=True)
    (task_dir / "request_validation.json").write_text(json.dumps(validation.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not validation.valid: raise RuntimeError(f"QLIP request validation failed: {validation.to_dict()}")
    solve_started = time.perf_counter(); result = solve(request); solve_time = time.perf_counter() - solve_started
    payload = result.to_dict(); (task_dir / "solve_result.json").write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if result.status not in {"OPTIMAL", "FEASIBLE"} or not result.outputs.cif: raise RuntimeError(f"QLIP solve failed: {payload}")
    solution_path = task_dir / "solution.cif"; solution_path.write_text(result.outputs.cif, encoding="latin-1")
    solution = Structure.from_file(solution_path)
    detected_formula = solution.composition.reduced_formula; target_formula = Composition(task["target_formula"]).reduced_formula
    if detected_formula != target_formula: raise RuntimeError(f"Formula mismatch: expected {target_formula}, found {detected_formula}")
    assignment = occupation_assignment(solution, scaffold)
    sca = skill.parent / "Structured_Crystal_Analyser"; crystal = skill.parent / "Crystal-DB"
    geometry = run_json([str(sca / ".venv" / "Scripts" / "python.exe"), "scripts/validate_nasicon_demo_geometry.py", "--cif", str(solution_path)], sca)
    topology = run_json([str(crystal / ".venv" / "Scripts" / "python.exe"), "scripts/validate_nasicon_demo_topology.py", "--cif", str(solution_path)], crystal)
    detected_space_group = geometry["detected_space_groups"]["0.01"]
    if geometry["status"] != "PASS" or int(geometry["bonds"]["num_bad_contacts"]) != 0: raise RuntimeError(f"Geometry/contact validation failed: {geometry}")
    if topology["topology_status"] != "PASS": raise RuntimeError(f"Topology validation failed: {topology}")
    solver_objective = float(result.summary.objective_value or 0.0); recomputed = 0.0; difference = abs(solver_objective - recomputed)
    if difference > 1e-9: raise RuntimeError(f"NO_SPP objective parity failed: {solver_objective} vs {recomputed}")
    certificate_path = task_dir / "solver_certificate.json"; certificate_path.write_text(json.dumps(result.certificates, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    trace_files = ["retrieval.json", "retrieved_evidence.json", "leakage_audit.json", "solve_request.json", "request_validation.json", "solve_result.json", "solution.cif", "solver_certificate.json"]
    trace_complete = all((task_dir / name).is_file() for name in trace_files)
    if not trace_complete: raise RuntimeError("Trace bundle incomplete")
    diagnostics = result.certificates.get("diagnostics", {}); stats = diagnostics.get("model_stats", {})
    record = {
        "task_id": task_id, "request_hash": sha_text(task["natural_language_request"]), "structured_intent_hash": structured_intent_hash(task),
        "search_space_hash": expected["search_space_hash"], "scaffold_id": scaffold.scaffold_id, "scaffold_version": scaffold.scaffold_version,
        "scaffold_source_hash": scaffold.source_cif_sha256, "target_formula": task["target_formula"], "requested_space_group": task["allowed_space_groups"],
        "scaffold_space_group": scaffold.source_space_group, "orbit_multiplicities": json.dumps(scaffold.orbit_multiplicities, sort_keys=True, separators=(",", ":")),
        "selected_occupation": json.dumps(assignment, sort_keys=True, separators=(",", ":")), "retrieval_database": "nasicon_specialist_all_targets_out_v3",
        "retrieved_record_ids": ";".join(row["record_id"] for row in evidence), "retrieved_cif_hashes": ";".join(row["cif_sha256"] for row in evidence),
        "exact_formula_leakage_count": leakage["exact_formula_leakage_count"], "exact_structure_leakage_count": leakage["exact_structure_leakage_count"],
        "spp_status": "NO_SPP", "spp_support_summary": "No frozen row-specific complete SPP artifact; real feasibility MILP used with zero objective.", "spp_artifact_hash": "",
        "variable_count": stats.get("variables"), "constraint_count": stats.get("constraints"), "solver_status": result.status,
        "optimality_gap": result.summary.mip_gap if result.summary.mip_gap is not None else (0.0 if result.status == "OPTIMAL" else ""),
        "solver_objective": solver_objective, "recomputed_objective": recomputed, "objective_difference": difference, "objective_parity": True,
        "solve_time_seconds": solve_time, "generated_cif_path": str(solution_path), "generated_cif_sha256": sha_file(solution_path),
        "detected_formula": detected_formula, "formula_match": True, "detected_space_group": detected_space_group,
        "severe_contact_count": geometry["bonds"]["num_bad_contacts"], "topology_status": topology["topology_status"],
        "topology_details": json.dumps(topology, sort_keys=True, separators=(",", ":")), "trace_complete": trace_complete,
        "engineering_smoke_status": "PASS", "failure_reason": "", "wall_time_seconds": time.perf_counter() - started,
    }
    (task_dir / "result.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    aggregate(out)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--task-id", required=True, choices=TASK_ORDER); args = parser.parse_args()
    print(json.dumps(run_task(args.task_id), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
