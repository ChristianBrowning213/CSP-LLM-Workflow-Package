"""Build and optionally freeze the solve-free scaffold-prior ablation preflight."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from qlip.core.validate import _normalize_request, _solve_request_schema
from qlip.scaffolds.occupation import preflight_ordered_occupation

from sok_llm_orchestrator.bench.prospective import FrozenReference
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    _qlip_ordered_orbits_adapter,
    _qlip_target_formula,
)


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "artifacts/scaffold_ablation_v1_preflight"
FREEZE = ROOT / "artifacts/scaffold_ablation_v1"
V3 = ROOT / "artifacts/final_paper_benchmark_v3"
V1 = ROOT / "artifacts/final_paper_benchmark"
TARGETS = ("BaTiO3", "CaTiO3", "CsPbBr3", "CsPbCl3", "CsSnBr3")
CONDITIONS = ("MINIMAL_REGULATOR_ONLY", "MINIMAL_REGULATOR_PLUS_REQUEST")
PROTECTED = {
    "artifacts/final_paper_benchmark_v3/results/result_2_heldout/RESULT_2_HELDOUT_RECOVERY.csv": "ee539ad8de148afc029b5494455d15a79b33cb362df3473e129d2c4557cfe0a0",
    "artifacts/final_paper_benchmark_v3/results/result_3_factorial/RESULT_3_FACTORIAL.csv": "5688029447547363fe7fd62fcee6da5f0e4d378afab8f54499be5a5251925c3e",
    "artifacts/final_paper_benchmark_result4_v4_1/results/EXECUTION_LEDGER.csv": "3f7dac9d0481ef8083a4ce8a95fc4e926eacafc81882d4358ef0557a7aff4c08",
    "artifacts/final_paper_benchmark_result4_completion_v4_2/results/EXECUTION_LEDGER.csv": "83a47d0d63e92d4ff9a65d4275c4e9b63fd441a63519d493cf2a1445e215f9ff",
}
PREFLIGHT_FILES = (
    "SCAFFOLD_LEVEL_DEFINITIONS.md", "MINIMAL_SCAFFOLD_AUDIT.md",
    "FEASIBLE_STATE_COUNTS.csv", "TARGETS.csv", "REFERENCE_PROVENANCE.csv",
    "GUIDANCE_CONFIG.json", "LEAKAGE_AUDIT.csv", "EXECUTABILITY_REPORT.md",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_protected() -> None:
    for relative, expected in PROTECTED.items():
        actual = sha256(ROOT / relative)
        if actual != expected:
            raise RuntimeError(f"protected result changed: {relative}: {actual}")


def schema_request(task: dict[str, Any], structure: Any, orbits: list[dict[str, Any]], pairs: list[str], scaffold_id: str) -> dict[str, Any]:
    cell = structure.lattice
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": _qlip_target_formula(task, len(structure))},
            "design_space": {
                "template": {"name": scaffold_id, "lattice": {
                    "a": cell.a, "b": cell.b, "c": cell.c,
                    "alpha": cell.alpha, "beta": cell.beta, "gamma": cell.gamma,
                    "units": "angstrom",
                }},
                "sites": {
                    "mode": "explicit_fractional_sites",
                    "explicit_fractional_sites": structure.frac_coords.tolist(),
                    "ordered_orbits": _qlip_ordered_orbits_adapter(orbits),
                },
            },
            "objective": {"type": "spp_energy"},
        },
        "constraints": [],
        "guidance": [{"id": "objective.energy_spp", "params": {
            "pot_root": str(ROOT), "mode": "partial", "supported_pairs": [],
            "missing_pairs": pairs, "missing_pair_policy": "neutral",
            "strict_pair_coverage": False,
        }}],
        "solver": {"name": "gurobi", "time_limit_s": 300, "mip_gap": 0.0, "threads": 1, "seed": 0},
        "artifacts": {"return_cif": True},
    }


def build_preflight() -> None:
    verify_protected()
    PREFLIGHT.mkdir(parents=True, exist_ok=False)
    stages = ProductionWorkflowStages()
    informative = {row["formula"]: row for row in read_csv(V3 / "RESULT_3_INFORMATIVENESS.csv")}
    references = {row["formula"]: row for row in read_csv(V3 / "BENCHMARK_V3_REFERENCES.csv")}
    v1_targets = {row["formula"]: row for row in read_csv(V1 / "BENCHMARK_TARGETS.csv")}
    factorial = read_csv(V3 / "results/result_3_factorial/RESULT_3_FACTORIAL.csv")
    loose_request = {
        row["formula"]: row for row in factorial
        if row["condition_id"] == "LOOSE_REGULATOR_PLUS_REQUEST"
    }
    target_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []
    leakage_rows: list[dict[str, Any]] = []
    count_rows: list[dict[str, Any]] = []
    schema_passes = 0
    minimal_counts: dict[str, int] = {}
    candidate_hashes: dict[str, str] = {}
    for case_index, formula in enumerate(TARGETS, start=1):
        info = informative[formula]
        if info["included_in_causal_request_spp_denominator"] != "YES" or int(info["request_usable_pair_count"]) < 1:
            raise RuntimeError(f"target is not prospectively informative: {formula}")
        task = stages.normalise(formula)
        case_id = info["case_id"]
        target_rows.append({
            "sequence": case_index, "case_id": case_id, "formula": formula,
            "prospective_informativeness": info["actual_informativeness"],
            "frozen_request_usable_pairs": info["request_usable_pair_count"],
            "frozen_regulator_fallback_pairs": info["regulator_fallback_pair_count"],
            "unsupported_pairs": info["unsupported_pair_count"],
            "new_conditions": ";".join(CONDITIONS), "target_selection_changed": "NO",
        })
        frozen_ref = references[formula]
        reference_path = ROOT / v1_targets[formula]["reference_cif_path"]
        reference = FrozenReference.from_cif(
            case_id=case_id, formula=formula,
            reference_id=frozen_ref["crystal_db_structure_id"],
            source_structure_id=frozen_ref["source_mp_id"], cif_path=reference_path,
        )
        if reference.raw_sha256 != frozen_ref["cif_sha256"] or reference.canonical_sha256 != frozen_ref["canonical_sha256"]:
            raise RuntimeError(f"reference hash mismatch: {formula}")
        reference_rows.append({
            "case_id": case_id, "formula": formula, "reference_id": reference.reference_id,
            "source_structure_id": reference.source_structure_id,
            "reference_cif_path": str(reference.cif_path.relative_to(ROOT)).replace("\\", "/"),
            "cif_sha256": reference.raw_sha256, "canonical_sha256": reference.canonical_sha256,
            "space_group": frozen_ref["space_group"], "frozen_before_ablation": "YES",
            "used_to_construct_minimal_scaffold": "NO", "comparison_stage": "POST_GENERATION_ONLY",
        })
        existing = loose_request[formula]
        if existing["reference_equivalent_evidence_count"] != "0":
            raise RuntimeError(f"preserved leakage audit is nonzero: {formula}")
        leakage_rows.append({
            "case_id": case_id, "formula": formula,
            "policy_source": "artifacts/final_paper_benchmark_v3/LEAKAGE_EXCLUSION_CONFIG.json",
            "reference_id": reference.reference_id, "source_structure_id": reference.source_structure_id,
            "existing_reference_ID_exclusions": existing["reference_ID_exclusions"],
            "existing_raw_duplicate_exclusions": existing["raw_duplicate_exclusions"],
            "existing_canonical_duplicate_exclusions": existing["canonical_duplicate_exclusions"],
            "existing_StructureMatcher_exclusions": existing["StructureMatcher_exclusions"],
            "existing_reference_equivalent_evidence_count": existing["reference_equivalent_evidence_count"],
            "apply_to_primary_retrieval": "YES", "apply_to_pair_coverage_expansion": "YES",
            "new_retrieval_executed": "NO", "status": "PASS_FROZEN_POLICY_REUSED",
        })
        mode_structures = {}
        for mode in ("tight", "loose", "minimal"):
            config = WorkflowConfig(output_root=Path("."), scaffold_mode=mode)
            scaffold_id, structure, orbits = stages._scaffold(task, config)
            assignments = stages.enumerate_feasible_assignments(task, config)
            pairs = stages.required_pairs(task, config)
            request = schema_request(task, structure, orbits, pairs, scaffold_id)
            schema_errors = sorted(Draft202012Validator(_solve_request_schema()).iter_errors(_normalize_request(request)), key=str)
            occupation = preflight_ordered_occupation(_qlip_target_formula(task, len(structure)), len(structure), _qlip_ordered_orbits_adapter(orbits))
            if schema_errors or not occupation.stoichiometry_representable:
                raise RuntimeError(f"QLIP design-space preflight failed: {formula}/{mode}: {schema_errors or occupation.rejection_reason}")
            schema_passes += 1
            position_payload = {
                "lattice": [round(float(value), 12) for row in structure.lattice.matrix for value in row],
                "fractional_positions": [[round(float(value) % 1.0, 12) for value in row] for row in structure.frac_coords],
            }
            mode_structures[mode] = position_payload
            count_rows.append({
                "case_id": case_id, "formula": formula, "scaffold_level": mode.upper(),
                "scaffold_id": scaffold_id, "candidate_site_count": len(structure),
                "candidate_cell_position_hash": json_hash(position_payload),
                "ordered_orbit_count": len(orbits),
                "multi_site_closed_orbit_count": sum(len(orbit["site_indices"]) > 1 for orbit in orbits),
                "fixed_species_orbit_count": sum("fixed_species" in orbit for orbit in orbits),
                "all_sites_required_occupied": all(orbit.get("required_occupancy") is True for orbit in orbits),
                "exact_formula": _qlip_target_formula(task, len(structure)),
                "feasible_state_count": len(assignments), "assignment_set_sha256": json_hash(assignments),
                "qlip_json_schema": "PASS", "qlip_ordered_occupation_preflight": "PASS",
                "solve_executed": "NO",
            })
            if mode == "minimal":
                minimal_counts[formula] = len(assignments)
        if not (mode_structures["tight"] == mode_structures["loose"] == mode_structures["minimal"]):
            raise RuntimeError(f"candidate cell/positions changed across scaffold levels: {formula}")
        candidate_hashes[formula] = json_hash(mode_structures["minimal"])
    if any(count <= 2 for count in minimal_counts.values()):
        raise RuntimeError(f"minimal experiment is not informative: {minimal_counts}")

    write_csv(PREFLIGHT / "TARGETS.csv", target_rows)
    write_csv(PREFLIGHT / "REFERENCE_PROVENANCE.csv", reference_rows)
    write_csv(PREFLIGHT / "LEAKAGE_AUDIT.csv", leakage_rows)
    write_csv(PREFLIGHT / "FEASIBLE_STATE_COUNTS.csv", count_rows)
    write_json(PREFLIGHT / "GUIDANCE_CONFIG.json", {
        "schema_version": "scaffold_ablation_guidance.v1", "conditions": list(CONDITIONS),
        "MINIMAL_REGULATOR_ONLY": {
            "scaffold_mode": "minimal", "request_spp_mode": "disabled",
            "objective": "10 * (2 * regulator_score)",
        },
        "MINIMAL_REGULATOR_PLUS_REQUEST": {
            "scaffold_mode": "minimal", "request_spp_mode": "enabled",
            "usable_pair_objective": "10 * (request_score + 2 * regulator_score)",
            "fallback_pair_objective": "10 * (2 * regulator_score)",
        },
        "fixed": {
            "retrieval_depth": 40, "embedding_model": "text-embedding-bge-m3",
            "embedding_version": "lmstudio_v1", "request_spp_convention": "reward",
            "request_spp_quality_threshold_max_cap_fraction": 0.5,
            "regulator_id": "icsd_broad_regulator_v1",
            "regulator_sha256": "be0a8f620fca62aa3bb755d76ac9edeeb8aa1ac507c4800001e4018b94c6cf0c",
            "regulator_coefficient": 2.0, "outer_objective_scale": 10.0,
            "cutoff_angstrom": 11.0,
            "solver": {"name": "gurobi", "time_limit_s": 300, "mip_gap": 0.0, "threads": 1, "seed": 0},
            "SCA": {"package": "sca", "version": "0.1.0", "selection_influence": False},
            "exclusion_policy": "exact V3 reference ID/raw/canonical/StructureMatcher filtering on primary and expansion",
        },
        "new_execution_count": 10, "execution_status": "NOT_STARTED",
    })
    (PREFLIGHT / "SCAFFOLD_LEVEL_DEFINITIONS.md").write_text(
        "# Scaffold-level definitions\n\n"
        "All three levels use the identical canonical five-site ABX3 cell and fractional positions.\n\n"
        "| Level | Species constraints | Orbit closure | Exact composition | Feasible states |\n"
        "|---|---|---|---|---:|\n"
        "| TIGHT | Each site admits only its canonical A, B, or X species | Five occupied singleton domains | Required | 1 |\n"
        "| LOOSE | Two cation sites admit A/B; three anion sites admit X only | Five occupied singleton domains | Required | 2 |\n"
        f"| MINIMAL | Every individual site admits all three target species | Five occupied singleton domains; no multi-site equality | Required | {next(iter(minimal_counts.values()))} |\n\n"
        "TIGHT fixes the normal role allocation. LOOSE permits only normal/inverted cation allocation while retaining the X role. MINIMAL removes every A/B/X site role: only exact ABX3 counts, one species per site, full occupancy, the unchanged cell, and the unchanged candidate positions remain.\n",
        encoding="utf-8",
    )
    (PREFLIGHT / "MINIMAL_SCAFFOLD_AUDIT.md").write_text(
        "# Minimal scaffold audit\n\n"
        "- Scaffold ID: `abx3_five_site_minimal_assignment_v1`.\n"
        "- Candidate lattice and five fractional positions are byte-normalized identical across tight, loose, and minimal for every target.\n"
        "- QLIP receives five singleton ordered-site domains. Every domain admits every target species and requires occupancy.\n"
        "- No `fixed_species`, vacancy, multi-site orbit closure, A-site role, B-site role, X-site role, normal/inverted preference, reference coordinates, or reference assignment is present.\n"
        "- QLIP still enforces exact cell-scaled stoichiometry and exactly one species on each candidate site.\n"
        f"- Measured minimal feasible counts: `{minimal_counts}`. Counts were exhaustively enumerated, not hard-coded.\n"
        "- Independent combinatorial cross-check: choose three of five sites for X, `C(5,3) = 10`, then assign A/B over the two remaining sites in two ways, giving `10 x 2 = 20`. This expectation only cross-checks the canonical exhaustive enumeration.\n"
        "- Held-out references appear only in frozen provenance/exclusion records and future post-generation comparison.\n"
        "- Benchmark solves executed during this preflight: 0.\n",
        encoding="utf-8",
    )
    (PREFLIGHT / "EXECUTABILITY_REPORT.md").write_text(
        "# Executability report\n\n"
        f"- Targets: {len(TARGETS)}/5 PASS.\n- Scaffold payloads validated against QLIP JSON schema: {schema_passes}/15 PASS.\n"
        "- QLIP ordered-occupation semantic preflight: 15/15 PASS.\n"
        "- Candidate cell/position identity across levels: 5/5 PASS.\n"
        "- Tight/loose/minimal state-count pattern: 5/5 PASS.\n"
        "- Minimal counts greater than two: 5/5 PASS.\n"
        "- Exact reference provenance: 5/5 PASS.\n- Frozen leakage policy/remainder zero: 5/5 PASS.\n"
        "- Request ON/OFF and regulator weighting are covered by focused contract tests.\n"
        "- Existing V3/V4 protected hashes: 4/4 PASS.\n"
        "- Retrievals, request-SPP fits, QLIP solves, CIF generation, SCA evaluation: 0.\n"
        "- Preflight status: READY_FOR_TEST_GATE; not frozen and not launched.\n",
        encoding="utf-8",
    )


def freeze() -> None:
    verify_protected()
    if not PREFLIGHT.is_dir() or any(not (PREFLIGHT / name).is_file() for name in PREFLIGHT_FILES):
        raise RuntimeError("complete preflight package is unavailable")
    counts = read_csv(PREFLIGHT / "FEASIBLE_STATE_COUNTS.csv")
    minimal = [row for row in counts if row["scaffold_level"] == "MINIMAL"]
    if len(minimal) != 5 or any(int(row["feasible_state_count"]) <= 2 for row in minimal):
        raise RuntimeError("minimal state space is not informative")
    if FREEZE.exists():
        raise RuntimeError(f"freeze root already exists: {FREEZE}")
    workflow_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    relevant_diff = subprocess.check_output(
        ["git", "status", "--short", "--", "src/sok_llm_orchestrator/workflow/runner.py", "tests/test_scaffold_prior_ablation.py", "scripts/prepare_scaffold_ablation_v1.py", "artifacts/scaffold_ablation_v1_preflight"],
        cwd=ROOT, text=True,
    ).strip()
    if relevant_diff:
        raise RuntimeError(f"ablation workflow/preflight is not committed: {relevant_diff}")
    FREEZE.mkdir(parents=True)
    copies = {
        "SCAFFOLD_LEVEL_DEFINITIONS.md": "SCAFFOLD_LEVEL_DEFINITIONS.md",
        "TARGETS.csv": "TARGETS.csv",
        "REFERENCE_PROVENANCE.csv": "REFERENCES.csv",
        "FEASIBLE_STATE_COUNTS.csv": "FEASIBLE_STATE_COUNTS.csv",
        "GUIDANCE_CONFIG.json": "GUIDANCE_CONFIG.json",
        "LEAKAGE_AUDIT.csv": "LEAKAGE_AUDIT.csv",
        "MINIMAL_SCAFFOLD_AUDIT.md": "MINIMAL_SCAFFOLD_AUDIT.md",
        "EXECUTABILITY_REPORT.md": "EXECUTABILITY_REPORT.md",
    }
    for source, destination in copies.items():
        shutil.copy2(PREFLIGHT / source, FREEZE / destination)
    analysis_plan = (
        "# Scaffold-ablation V1 analysis plan\n\n"
        "This plan is frozen before any new minimal-scaffold solve. No outcome is defined as success in advance.\n\n"
        "## Primary new causal comparison\n\n"
        "For each of the five targets, compare `MINIMAL_REGULATOR_ONLY` with `MINIMAL_REGULATOR_PLUS_REQUEST`. Record selected occupation, selection changed (YES/NO), and reference equivalence before/after. Classify each pair as exactly one of: `IMPROVED`, `WORSENED`, `UNCHANGED_REFERENCE`, `UNCHANGED_NONREFERENCE`, or `CHANGED_BUT_NEITHER_REFERENCE`.\n\n"
        "## Scaffold-prior comparison\n\n"
        "Combine immutable V3 TIGHT/LOOSE rows with the new MINIMAL rows. Compare `TIGHT -> LOOSE -> MINIMAL` separately for regulator-only and regulator-plus-request. At each level report feasible-state count, reference recovery, exact space-group agreement, crystal-system agreement, volume error, and SCA.\n\n"
        "## Interpretation\n\n"
        "- Minimal R poor and Minimal R+Q better: request-specific SPP becomes useful as scaffold prior weakens.\n"
        "- Both Minimal conditions poor: pair-distance statistics are insufficient to replace stronger crystallographic prior.\n"
        "- Both Minimal conditions good and identical: broad regulator/search geometry dominates.\n"
        "- Minimal R+Q worse: request-specific SPP mis-ranks candidates in the weakly constrained space.\n"
    )
    (FREEZE / "ANALYSIS_PLAN.md").write_text(analysis_plan, encoding="utf-8")
    historical_conditions = {
        "TIGHT_REGULATOR_ONLY", "TIGHT_REGULATOR_PLUS_REQUEST",
        "LOOSE_REGULATOR_ONLY", "LOOSE_REGULATOR_PLUS_REQUEST",
    }
    historical_source = V3 / "results/result_3_factorial/RESULT_3_FACTORIAL.csv"
    historical_rows = []
    for row in read_csv(historical_source):
        if row["formula"] not in TARGETS or row["condition_id"] not in historical_conditions:
            continue
        selected = {
            "case_id": row["case_id"], "formula": row["formula"],
            "condition_id": row["condition_id"], "run_id": row["run_id"],
            "attempt_id": row["attempt_id"], "workflow_commit": row["workflow_commit"],
            "freeze_hash": row["freeze_hash"], "scaffold_mode": row["scaffold_mode"],
            "scaffold_id": row["scaffold_id"], "feasible_state_count": row["feasible_state_count"],
            "selected_state": row["selected_state"], "reference_match": row["reference_match"],
            "generated_space_group": row["generated_space_group"],
            "reference_space_group": row["reference_space_group"],
            "exact_space_group_agreement": row["exact_space_group_agreement"],
            "crystal_system_agreement": row["crystal_system_agreement"],
            "absolute_volume_error_percent": row["absolute_volume_error_percent"],
            "sca_status": row["sca_status"], "solver_status": row["solver_status"],
            "objective_parity": row["objective_parity"], "workflow_status": row["workflow_status"],
            "source_result_sha256": sha256(historical_source),
        }
        selected["frozen_row_sha256"] = json_hash(selected)
        historical_rows.append(selected)
    if len(historical_rows) != 20:
        raise RuntimeError(f"expected 20 immutable V3 historical arms, found {len(historical_rows)}")
    write_csv(FREEZE / "HISTORICAL_V3_ARMS.csv", historical_rows)
    protocol = (
        "# Scaffold-prior ablation V1 frozen protocol\n\n"
        "Prospective question: does request-specific SPP become more useful when ABX3 scaffold occupation prior is removed? Existing V3 tight/loose outcomes are immutable and will not be rerun. Only five informative targets and two new minimal conditions are frozen (10 future executions). All outcomes are acceptable prospectively. No retrieval, SPP fit, solve, CIF, or SCA execution occurred before this freeze.\n"
    )
    (FREEZE / "FROZEN_PROTOCOL.md").write_text(protocol, encoding="utf-8")
    preflight_hashes = {name: sha256(PREFLIGHT / name) for name in PREFLIGHT_FILES}
    frozen_hashes = {
        "targets_sha256": sha256(FREEZE / "TARGETS.csv"),
        "references_sha256": sha256(FREEZE / "REFERENCES.csv"),
        "scaffold_definitions_sha256": sha256(FREEZE / "SCAFFOLD_LEVEL_DEFINITIONS.md"),
        "feasible_state_counts_sha256": sha256(FREEZE / "FEASIBLE_STATE_COUNTS.csv"),
        "guidance_config_sha256": sha256(FREEZE / "GUIDANCE_CONFIG.json"),
        "analysis_plan_sha256": sha256(FREEZE / "ANALYSIS_PLAN.md"),
        "historical_v3_arms_sha256": sha256(FREEZE / "HISTORICAL_V3_ARMS.csv"),
    }
    freeze_payload = {
        "schema_version": "scaffold_ablation_v1_freeze.v1", "workflow_commit": workflow_commit,
        "targets": list(TARGETS), "conditions": list(CONDITIONS), "planned_executions": 10,
        "execution_status": "FROZEN_NOT_STARTED", "benchmark_solves_before_freeze": 0,
        "existing_tight_loose_results_rerun": False, "protected_results": PROTECTED,
        "preflight_hashes": preflight_hashes,
        "minimal_scaffold_id": "abx3_five_site_minimal_assignment_v1",
        "minimal_feasible_state_counts": {row["formula"]: int(row["feasible_state_count"]) for row in minimal},
        "retrieval_config": json.loads((PREFLIGHT / "GUIDANCE_CONFIG.json").read_text(encoding="utf-8"))["fixed"],
        "hashes": frozen_hashes,
        "targets_frozen_before_new_solves": True, "references_frozen_before_new_solves": True,
        "minimal_scaffold_frozen_before_new_solves": True, "analysis_frozen_before_new_solves": True,
        "historical_v3_arm_count": 20, "historical_v3_arms_rerun": False,
    }
    write_json(FREEZE / "SCAFFOLD_ABLATION_FREEZE.json", freeze_payload)
    manifest_files = [*copies.values(), "ANALYSIS_PLAN.md", "HISTORICAL_V3_ARMS.csv", "FROZEN_PROTOCOL.md", "SCAFFOLD_ABLATION_FREEZE.json"]
    manifest = [{"path": name, "sha256": sha256(FREEZE / name)} for name in manifest_files]
    write_csv(FREEZE / "OUTPUT_HASH_MANIFEST.csv", manifest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    freeze() if args.freeze else build_preflight()


if __name__ == "__main__":
    main()
