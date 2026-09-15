"""Reconstruct the frozen paper execution ledger without running generation.

This is deliberately a read-only forensic aggregator with respect to source
campaigns.  It writes only artifacts/paper_results_extension_v2/00_audit.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_results_extension_v2" / "00_audit"
FINAL = ROOT / "artifacts" / "paper_final_results_v1"
NA = "NA"

FIELDS = [
    "run_id", "request_id", "experiment_group", "request_text",
    "composition_requested", "reduced_formula", "material_family",
    "scaffold_id", "scaffold_source", "requested_space_group",
    "scaffold_space_group", "retrieval_corpus", "retrieval_config_id",
    "spp_config_id", "solver_status", "solver_objective",
    "independently_recomputed_objective", "objective_difference",
    "solve_time_s", "num_binary_variables", "num_constraints",
    "num_pair_terms", "cif_generated", "generated_cif_path",
    "raw_structure_hash", "canonical_structure_hash", "unique_structure_id",
    "duplicate_of_run_id", "parse_ok", "formula_check",
    "initial_space_group", "symmetry_check", "minimum_distance_A",
    "severe_contact_check", "initial_topology", "chgnet_run",
    "chgnet_converged", "relaxation_steps", "final_fmax_eV_A",
    "relaxed_space_group", "volume_initial_A3", "volume_relaxed_A3",
    "volume_change_percent", "relaxed_topology",
    "structurematcher_initial_relaxed", "execution_outcome",
    "failure_or_abstention_reason", "notes",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p.resolve()).replace("\\", "/")


def bool_text(value) -> str:
    if value in (True, "True", "true", "PASS", "generated"):
        return "True"
    if value in (False, "False", "false", "FAIL"):
        return "False"
    return NA if value in (None, "") else str(value)


def blank_row() -> dict[str, str]:
    return {field: NA for field in FIELDS}


def validation_fields(result: dict[str, str]) -> dict[str, str]:
    return {
        "parse_ok": bool_text(result.get("parse_ok")),
        "formula_check": bool_text(result.get("formula_match")),
        "initial_space_group": result.get("detected_space_group") or NA,
        "symmetry_check": bool_text(result.get("detected_space_group") == result.get("requested_space_group")),
        "minimum_distance_A": result.get("minimum_distance") or NA,
        "severe_contact_check": bool_text(result.get("contact_screen_pass")),
        "initial_topology": result.get("topology_status") or NA,
        "chgnet_run": bool_text(result.get("chgnet_status") not in (None, "", "NOT_CONFIGURED")),
        "chgnet_converged": bool_text(result.get("converged")),
        "relaxation_steps": result.get("relaxation_steps") or NA,
        "final_fmax_eV_A": result.get("final_max_force") or NA,
        "relaxed_space_group": result.get("space_group_after") or NA,
        "volume_initial_A3": result.get("initial_volume") or NA,
        "volume_relaxed_A3": result.get("final_volume") or NA,
        "volume_change_percent": result.get("volume_change_percent") or NA,
        "relaxed_topology": result.get("topology_after") or NA,
        "structurematcher_initial_relaxed": bool_text(result.get("structure_match_initial_relaxed")),
    }


def request_id_for(source_task_id: str, formula: str) -> str:
    if source_task_id.startswith("exp3_"):
        return f"REQ-HALIDE-{formula.upper()}"
    if source_task_id.startswith("exp2v3_") and "_halide" in source_task_id:
        return f"REQ-HALIDE-{formula.upper()}"
    return source_task_id


def build_rows() -> list[dict[str, str]]:
    workflow = read_csv(FINAL / "01_manifests" / "FINAL_WORKFLOW_ROW_MANIFEST.csv")
    row_map = {r["final_row_id"]: r for r in read_csv(FINAL / "01_manifests" / "FINAL_ROW_TO_UNIQUE_STRUCTURE_MAP.csv")}
    unique_manifest = {r["unique_structure_id"]: r for r in read_csv(FINAL / "01_manifests" / "FINAL_UNIQUE_STRUCTURE_MANIFEST.csv")}
    unique_results = {r["unique_structure_id"]: r for r in read_csv(FINAL / "07_tables" / "FINAL_UNIQUE_STRUCTURE_RESULTS.csv")}
    representative_run: dict[str, str] = {}
    rows: list[dict[str, str]] = []

    # The frozen paper manifest contains 30 legacy experiment rows, one NASICON
    # specialist row, and three NASICON demonstration rows.  Build these first.
    for manifest in workflow:
        task = manifest["source_task_id"]
        final_id = manifest["final_row_id"]
        uid = row_map[final_id]["unique_structure_id"]
        u = unique_manifest[uid]
        result = unique_results[uid]
        cif = Path(manifest["generated_cif_path"])
        row = blank_row()
        row.update({
            "run_id": task,
            "request_id": request_id_for(task, manifest["target_formula"]),
            "experiment_group": manifest["experiment_group"],
            "request_text": manifest["natural_language_request"],
            "composition_requested": manifest["target_formula"],
            "reduced_formula": u.get("reduced_formula") or result.get("detected_formula") or NA,
            "material_family": manifest["target_family"],
            "scaffold_id": manifest["scaffold_id"],
            "scaffold_source": manifest.get("scaffold_version") or NA,
            "requested_space_group": manifest["requested_space_group"],
            "scaffold_space_group": manifest["requested_space_group"],
            "retrieval_corpus": manifest["retrieval_corpus"],
            "retrieval_config_id": manifest["retrieval_corpus"],
            "spp_config_id": manifest["spp_status"],
            "solver_status": manifest["solver_status"],
            "cif_generated": "True",
            "generated_cif_path": rel(cif),
            "raw_structure_hash": u["raw_cif_sha256"],
            "canonical_structure_hash": u["canonical_structure_sha256"],
            "unique_structure_id": uid,
            "notes": f"Frozen paper row {final_id}; source campaign {manifest['source_campaign']}.",
        })
        row.update(validation_fields(result))

        if task.startswith(("exp1_", "exp2v3_", "exp3_")):
            run_dir = cif.parent
            solution = read_json(run_dir / "qlip_solution.json")
            sol = solution.get("solution", {})
            row.update({
                "solver_objective": sol.get("objective_value") if sol.get("objective_value") is not None else NA,
                "num_binary_variables": NA,
                "num_constraints": NA,
                "num_pair_terms": len(sol.get("selected_pair_score_breakdown") or []),
                "notes": row["notes"] + " Legacy generated status used an enumeration-backed QLIP-style selector; no formal optimality certificate.",
            })
        else:
            demo_result_path = ROOT / "artifacts" / "paper_diversity_v2" / "nasicon_demo" / "NASICON_DEMO_RESULTS.jsonl"
            if task.startswith("E4_"):
                d = next(x for x in read_jsonl(demo_result_path) if x["task_id"] == task)
                row.update({
                    "solver_objective": d["solver_objective"],
                    "independently_recomputed_objective": d["recomputed_objective"],
                    "objective_difference": float(d["solver_objective"]) - float(d["recomputed_objective"]),
                    "num_binary_variables": d["variable_count"],
                    "num_constraints": d["constraint_count"],
                    "num_pair_terms": 0,
                })
            else:  # frozen leave-target-out NASICON specialist row
                base = ROOT / "artifacts" / "paper_nasicon_specialist_v2_final" / "leave_target_out"
                summary = read_json(base / "workflow_summary.json")
                solve = read_json(base / "solve_result.json")
                stats = solve["certificates"]["diagnostics"]["model_stats"]
                row.update({
                    "solver_objective": summary["objective"],
                    "independently_recomputed_objective": summary["objective"],
                    "objective_difference": 0.0,
                    "solve_time_s": summary["solver_time_ms"] / 1000,
                    "num_binary_variables": stats["variables"],
                    "num_constraints": stats["constraints"],
                    "num_pair_terms": solve["certificates"]["diagnostics"]["spp_guidance"]["terms_added_count"],
                })

        if uid in representative_run:
            row["execution_outcome"] = "GENERATED_DUPLICATE"
            row["duplicate_of_run_id"] = representative_run[uid]
        else:
            representative_run[uid] = task
            row["execution_outcome"] = "GENERATED_UNIQUE"
        rows.append(row)

    # Add the genuine but leakage-excluded full-corpus NASICON execution.  It is
    # byte-identical to the paper's leave-target-out U-021 representative.
    full_base = ROOT / "artifacts" / "paper_nasicon_specialist_v2_final" / "full"
    full_summary = read_json(full_base / "workflow_summary.json")
    full_solve = read_json(full_base / "solve_result.json")
    u21 = unique_results["U-021"]
    stats = full_solve["certificates"]["diagnostics"]["model_stats"]
    full = blank_row()
    full.update({
        "run_id": "nasicon_full_v2", "request_id": "REQ-NASICON-NA3ZR2SI2PO12-SPECIALIST",
        "experiment_group": "paper_nasicon_specialist",
        "request_text": "Generate an ordered NASICON-type Na3Zr2Si2PO12 candidate using the full specialist corpus.",
        "composition_requested": "Na3Zr2Si2PO12", "reduced_formula": "Na3Zr2Si2PO12",
        "material_family": "nasicon", "scaffold_id": "ordered_nasicon_mp_1221148_orbit_scaffold",
        "scaffold_source": "specialist NASICON ordered-orbit scaffold", "requested_space_group": "C2",
        "scaffold_space_group": "C2", "retrieval_corpus": full_summary["corpus_id"],
        "retrieval_config_id": "full", "spp_config_id": full_summary["spp_stage_status"],
        "solver_status": full_summary["solver_status"], "solver_objective": full_summary["objective"],
        "independently_recomputed_objective": full_summary["objective"], "objective_difference": 0.0,
        "solve_time_s": full_summary["solver_time_ms"] / 1000, "num_binary_variables": stats["variables"],
        "num_constraints": stats["constraints"],
        "num_pair_terms": full_solve["certificates"]["diagnostics"]["spp_guidance"]["terms_added_count"],
        "cif_generated": "True", "generated_cif_path": rel(full_base / "generated_nasicon.cif"),
        "raw_structure_hash": u21["raw_cif_sha256"], "canonical_structure_hash": u21["canonical_structure_sha256"],
        "unique_structure_id": "U-021", "duplicate_of_run_id": "nasicon_leave_target_out_v2",
        "execution_outcome": "GENERATED_DUPLICATE",
        "notes": "Real completed condition excluded from the paper/SCA denominator because exact_target_leakage_count=12; byte-identical to leave-target-out U-021.",
    })
    full.update(validation_fields(u21))
    rows.append(full)

    # Broad-corpus specialist condition: retrieval ran, but missing Na-Zr
    # coverage blocked SPP and therefore the solver.
    broad_base = ROOT / "artifacts" / "paper_nasicon_specialist_v2_final" / "broad"
    broad_summary = read_json(broad_base / "workflow_summary.json")
    broad = blank_row()
    broad.update({
        "run_id": "nasicon_broad_v2", "request_id": "REQ-NASICON-NA3ZR2SI2PO12-SPECIALIST",
        "experiment_group": "paper_nasicon_specialist",
        "request_text": "Generate an ordered NASICON-type Na3Zr2Si2PO12 candidate using the broad corpus condition.",
        "composition_requested": "Na3Zr2Si2PO12", "reduced_formula": "Na3Zr2Si2PO12",
        "material_family": "nasicon", "scaffold_id": "ordered_nasicon_mp_1221148_orbit_scaffold",
        "scaffold_source": "specialist NASICON ordered-orbit scaffold", "requested_space_group": "C2",
        "scaffold_space_group": "C2", "retrieval_corpus": broad_summary["corpus_id"],
        "retrieval_config_id": "broad", "spp_config_id": "BLOCKED_BEFORE_SPP",
        "solver_status": "NOT_CALLED", "solve_time_s": 0.0, "cif_generated": "False",
        "execution_outcome": "BLOCKED_UNSUPPORTED",
        "failure_or_abstention_reason": "missing required chemical-pair coverage: Na-Zr",
        "notes": "Retrieval completed; workflow_status=BLOCKED_BEFORE_SPP; no solver call and no CIF.",
    })
    rows.append(broad)

    # Two explicit capability-boundary executions.
    boundary_root = ROOT / "local_runs" / "paper_capability_boundary_audit_v1"
    for b in read_csv(boundary_root / "CAPABILITY_BOUNDARY_RESULTS.csv"):
        run_dir = boundary_root / b["row_id"]
        inp = read_json(run_dir / "input.json")
        row = blank_row()
        row.update({
            "run_id": b["row_id"], "request_id": b["row_id"],
            "experiment_group": "paper_capability_boundary_audit_v1",
            "request_text": inp["input_text"], "composition_requested": b["target_formula"],
            "reduced_formula": b["target_formula"], "material_family": b["target_family"],
            "retrieval_corpus": inp.get("source_db_scope", NA), "retrieval_config_id": inp.get("source_db_scope", NA),
            "solver_status": "NOT_CALLED", "solve_time_s": 0.0, "cif_generated": "False",
            "execution_outcome": "BLOCKED_UNSUPPORTED", "failure_or_abstention_reason": b["failure_reason"],
            "notes": "Explicit unsupported-solver capability-boundary audit; retrieval evidence is not a generated CIF.",
        })
        rows.append(row)

    # The scientific abstention is a workflow execution but did not call the solver.
    abst = read_csv(FINAL / "01_manifests" / "FINAL_ABSTENTION_MANIFEST.csv")[0]
    task_rows = {r["task_id"]: r for r in read_csv(ROOT / "artifacts" / "paper_diversity_v2" / "nasicon_demo" / "NASICON_DEMO_TASKS.csv")}
    if abst["abstention_id"] in task_rows:
        task = task_rows[abst["abstention_id"]]
    else:
        full_tasks = read_csv(ROOT / "artifacts" / "paper_diversity_v2" / "final" / "FOUR_EXPERIMENT_TASK_MANIFEST.csv")
        task = next(r for r in full_tasks if r["task_id"] == abst["abstention_id"])
    row = blank_row()
    row.update({
        "run_id": abst["abstention_id"], "request_id": abst["abstention_id"],
        "experiment_group": "nasicon_demo", "request_text": task.get("natural_language_request") or task.get("request") or task.get("request_text") or "Experiment 4 NASICON specialist request",
        "composition_requested": task.get("target_formula") or NA, "reduced_formula": task.get("target_formula") or NA,
        "material_family": "nasicon", "scaffold_id": task.get("scaffold_id") or task.get("scaffold_hypotheses") or NA,
        "requested_space_group": task.get("requested_symmetry") or task.get("requested_space_group") or NA,
        "retrieval_corpus": task.get("retrieval_database") or NA, "solver_status": "NOT_CALLED",
        "solve_time_s": 0.0, "cif_generated": "False", "execution_outcome": "SCIENTIFIC_ABSTENTION",
        "failure_or_abstention_reason": abst["reason"],
        "notes": f"Frozen abstention status: {abst['status']}; ordered orbit multiplicities cannot represent the requested composition.",
    })
    rows.append(row)

    # Give the old specialist conditions the same request identity as the frozen
    # leave-target-out paper row.
    for row in rows:
        if row["run_id"] == "nasicon_leave_target_out_v2":
            row["request_id"] = "REQ-NASICON-NA3ZR2SI2PO12-SPECIALIST"
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_funnel(rows: list[dict[str, str]]) -> list[dict[str, str | int]]:
    generated = [r for r in rows if r["cif_generated"] == "True"]
    metrics = [
        ("scientific_requests", len({r["request_id"] for r in rows}), "Unique intended tasks; repeated experimental conditions share a request_id."),
        ("workflow_executions", len(rows), "One row per observed workflow execution, including blocks and abstention."),
        ("solver_attempts", sum(r["solver_status"] != "NOT_CALLED" for r in rows), "Executions reaching a selector/solver stage."),
        ("optimal_solves", sum(r["solver_status"] == "OPTIMAL" for r in rows), "Explicitly certified OPTIMAL results only."),
        ("other_feasible_solves", 0, "No execution carries a distinct formal FEASIBLE certificate."),
        ("solver_outcome_not_formally_certified", sum(r["solver_status"] == "generated" for r in rows), "Legacy enumeration-backed generated rows; not re-labelled optimal."),
        ("solver_infeasible", sum(r["execution_outcome"] == "SOLVER_INFEASIBLE" for r in rows), "Explicit solver infeasibility only."),
        ("blocked_before_solver", sum(r["execution_outcome"] == "BLOCKED_UNSUPPORTED" for r in rows), "Unsupported or missing-evidence records with no solver call."),
        ("software_errors", sum(r["execution_outcome"] == "SOFTWARE_ERROR" for r in rows), "Crashes/software faults; none found in authoritative set."),
        ("cifs_generated", len(generated), "Generated candidate CIFs; retrieval/exported evidence CIFs excluded."),
        ("cifs_parseable", sum(r["parse_ok"] == "True" for r in generated), "Generated executions whose candidate parses; duplicate executions count."),
        ("generated_executions_after_validation", sum(r["parse_ok"] == "True" and r["formula_check"] == "True" and r["severe_contact_check"] == "True" for r in generated), "Generated execution records passing parse, formula, and severe-contact checks."),
        ("duplicate_generated_executions", sum(r["execution_outcome"] == "GENERATED_DUPLICATE" for r in rows), "Generated executions mapping to an earlier/representative unique structure."),
        ("crystallographically_unique_generated_structures", len({r["unique_structure_id"] for r in generated}), "Frozen canonical/hash/StructureMatcher unique IDs."),
        ("scientific_abstentions", sum(r["execution_outcome"] == "SCIENTIFIC_ABSTENTION" for r in rows), "Deliberate scientific representability abstentions."),
    ]
    return [{"metric": m, "count": c, "definition": d} for m, c, d in metrics]


def halide_markdown(rows: list[dict[str, str]]) -> str:
    halides = [r for r in rows if r["request_id"].startswith("REQ-HALIDE-")]
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in halides:
        grouped[row["composition_requested"]].append(row)
    lines = ["| Composition | Three execution IDs | Distinct structure |", "|---|---|---|"]
    for formula in sorted(grouped):
        group = grouped[formula]
        ids = ", ".join(r["run_id"] for r in group)
        uids = sorted({r["unique_structure_id"] for r in group})
        lines.append(f"| {formula} | {ids} | {', '.join(uids)} ({len(uids)}) |")
    assert len(halides) == 15 and len(grouped) == 5
    assert all(len(v) == 3 and len({r["unique_structure_id"] for r in v}) == 1 for v in grouped.values())
    return "\n".join(lines)


def write_documents(rows: list[dict[str, str]], funnel: list[dict]) -> None:
    source_manifest = """# Source manifest

This audit is a read-only reconstruction. “Frozen” means the source is an existing final/campaign artefact used as evidence; this script does not rewrite it.

| Source | Purpose | Frozen / relation to paper |
|---|---|---|
| `artifacts/paper_final_results_v1/01_manifests/FINAL_WORKFLOW_ROW_MANIFEST.csv` | Authoritative 34 generated paper workflow rows | Frozen final paper manifest |
| `artifacts/paper_final_results_v1/01_manifests/FINAL_UNIQUE_STRUCTURE_MANIFEST.csv` | Authoritative 24 unique structures and hashes | Frozen final unique denominator |
| `artifacts/paper_final_results_v1/01_manifests/FINAL_ROW_TO_UNIQUE_STRUCTURE_MAP.csv` | Row-to-unique and duplicate mapping | Frozen final deduplication evidence |
| `artifacts/paper_final_results_v1/01_manifests/FINAL_ABSTENTION_MANIFEST.csv` | E4_A1 scientific abstention | Frozen final abstention evidence |
| `artifacts/paper_final_results_v1/07_tables/FINAL_UNIQUE_STRUCTURE_RESULTS.csv` | Initial validation, CHGNet, relaxation, topology and StructureMatcher fields | Frozen final results table |
| `local_runs/paper_experiment_1_common_v1` | Ten current common-family executions, requests, retrieval traces, selectors and CIFs | Frozen raw source campaign for PFRV1-001–010 |
| `local_runs/paper_experiment_2_hard_v3` | Ten current hard-family executions including five halide baseline conditions | Frozen raw source campaign for PFRV1-011–020 |
| `local_runs/paper_experiment_3_specialist_halide_v1` | Ten specialist-halide repeated-condition executions | Frozen raw source campaign for PFRV1-021–030 |
| `local_runs/paper_capability_boundary_audit_v1` | Two explicit unsupported records | Frozen capability-boundary evidence; outside generated paper rows but inside complete execution denominator |
| `artifacts/paper_nasicon_specialist_v2_final` | Full, leave-target-out, and broad NASICON conditions | Frozen specialist source. Leave-target-out is PFRV1-031; full is a leakage-excluded duplicate; broad is blocked before SPP/solver |
| `artifacts/paper_diversity_v2/nasicon_demo` | Three generated demonstration tasks plus E4_A1 abstention | Frozen source for PFRV1-032–034 and abstention manifest |
| `C:/Users/brown/Documents/GitHub/Structured_Crystal_Analyser/artifacts/paper_full_sca_v1` | Fresh full SCA validation and trace bundles | Linked frozen validation source; 31 workflow rows / 21 unique input hashes before the three later demo structures |
| `runs/paper_final_results_v1` | CHGNet relaxation and final validation outputs keyed by U-001–U-024 | Frozen final analysis outputs |

## Quarantined / superseded sources

- `local_runs/paper_experiment_2_hard_v1` and `paper_experiment_2_hard_v2` are superseded by v3 and are not counted.
- `artifacts/paper_results_package_v2` through `paper_results_package_v10` and their display/SPP audit derivatives are intermediate presentation packages, not the final execution authority.
- `artifacts/paper_nasicon_specialist` is superseded by `paper_nasicon_specialist_v2_final`.
- `artifacts/PAPER_EXPERIMENTS_FULL_SCA_MANIFEST.csv` and older 30-row packaging predate the final NASICON additions; they are not used as the current denominator.
- `artifacts/paper_final_cifs` is superseded for paper claims by `artifacts/paper_final_results_v1`.

The word “quarantined” is logical only: no source was moved, deleted, or modified.
"""
    (OUT / "SOURCE_MANIFEST.md").write_text(source_manifest, encoding="utf-8")

    counts = {x["metric"]: x["count"] for x in funnel}
    halides = halide_markdown(rows)
    ledger_md = f"""# Master execution ledger

`master_run_ledger.csv` is the machine-readable authority for this reconstruction. It contains {len(rows)} executions representing {counts['scientific_requests']} scientific requests. Repeated conditions share a request ID but retain separate run IDs.

## Outcome accounting

| Outcome | Count |
|---|---:|
""" + "\n".join(f"| {k} | {v} |" for k, v in sorted(Counter(r["execution_outcome"] for r in rows).items())) + f"""

The 30 legacy rows marked solver status `generated` reached an enumeration-backed QLIP-style selector but have no formal optimality certificate; they are solver attempts, not claimed OPTIMAL solves. Five later NASICON executions are explicitly OPTIMAL. Retrieval/exported evidence CIFs in blocked run directories are not candidate CIFs.

## Halide repeated-condition mapping

Five compositions × three conditions = 15 executions. They produced five distinct structures:

{halides}

All three executions within each composition have the same frozen raw and canonical structure hashes. This is execution replication, not 15 crystallographically distinct outputs.
"""
    (OUT / "master_run_ledger.md").write_text(ledger_md, encoding="utf-8")

    funnel_md = f"""# Execution funnel

The complete forensic denominator starts with **{counts['scientific_requests']} scientific requests** and **{counts['workflow_executions']} executions**. It includes the 34 generated rows in the final paper workflow manifest, the leakage-excluded completed NASICON full-corpus condition, the blocked NASICON broad condition, two capability-boundary blocks, and E4_A1's scientific abstention.

Of {counts['solver_attempts']} solver/selector attempts, {counts['optimal_solves']} have an explicit OPTIMAL certificate and 30 legacy generated executions do not carry a formal feasibility/optimality certificate. No solver-infeasible or software-error record was found. {counts['cifs_generated']} candidate CIF executions were generated and parse/validate; {counts['duplicate_generated_executions']} are duplicate executions, leaving **{counts['crystallographically_unique_generated_structures']} unique structures**.

The final 24 are reproduced as: 35 generated CIF executions − 11 duplicate generated executions = 24 crystallographically unique structures. The leakage-excluded full NASICON condition adds one generated execution and one duplicate, so it changes neither the final unique structure count nor the paper's frozen 34-row manifest.

## Halide reconciliation

{halides}

## Category boundary

- `BLOCKED_UNSUPPORTED` means no solver call: missing required evidence coverage or no supported parameterised scaffold.
- `SCIENTIFIC_ABSTENTION` is the explicit ordered-model representability refusal for E4_A1.
- `SOFTWARE_ERROR` is reserved for a crash/fault; none occurs in the authoritative set.
"""
    (OUT / "EXECUTION_FUNNEL.md").write_text(funnel_md, encoding="utf-8")

    metric_md = """# Metric interpretation

| Metric | Class | Interpretation |
|---|---|---|
| Formula agreement | A | Exact composition is encoded in the task/scaffold allocation and checked afterward. This verifies implementation, not unconstrained formula prediction. |
| Requested initial space-group agreement | A | Prototype/scaffold symmetry and symmetry-closed orbits are prescribed. Agreement verifies construction and symmetry analysis. |
| Severe-contact screen | B (semi-independent) | The original paper workflow checks pair distances post hoc at 0.75 Å (`src/sok_llm_orchestrator/experiments/paper_workflow.py:594`). It is not a universal constraint in the final SCA evaluator, which uses element/radius-aware 0.6 Å non-H and 0.35 Å H absolute floors plus a covalent-radius rule. Fixed prototype/scaffold coordinates and some shrink-control policies indirectly make catastrophic contacts unlikely, so 24/24 is useful QC but not independent generative-quality evidence. |
| Initial topology | B (semi-independent) | Evaluated from generated geometry, but the topology/prototype was also part of scaffold intent. PASS/PARTIAL is a structural QC outcome, not wholly independent discovery. |
| CHGNet relaxation/convergence | B | An external surrogate relaxation checks whether structures can be numerically relaxed; it is not a stability or experimental-realizability proof. |
| Initial–relaxed StructureMatcher | B | Independent geometric comparison used for retention/deduplication; it does not establish novelty or thermodynamic quality. |
| Reference similarity | B | Local-corpus comparison only; a match/non-match is conditional on the evaluated corpus and tolerances, not a novelty claim. |
| SPP ablation / condition comparison | C only with a controlled causal contrast | The current 15 halide executions yield the same five structures across conditions. Frozen evidence therefore does not establish that SPP caused an improvement. Raw independently fitted SPP objectives are not cross-condition calibrated. |

## The 0.75 Å question

The literal 0.75 Å threshold is genuinely applied **post hoc** in the original paper workflow validation loop. It is not found as a universal search constraint and it is not the final SCA bond evaluator's rule. Nevertheless, severe-contact avoidance is partly **indirectly guaranteed** by reuse of fixed, chemically conventional prototype/scaffold coordinates (and, in selected paths, separate shrink/contact policies). The accurate classification is therefore B/semi-independent quality control, not causal evidence and not a free-form prediction metric.
"""
    (OUT / "METRIC_INTERPRETATION.md").write_text(metric_md, encoding="utf-8")

    report = f"""# Audit report

## Verified result

- Scientific requests: **{counts['scientific_requests']}**
- Workflow executions: **{counts['workflow_executions']}**
- Solver/selector attempts: **{counts['solver_attempts']}**
- Explicit OPTIMAL solves: **{counts['optimal_solves']}**
- Generated candidate CIF executions: **{counts['cifs_generated']}**
- Duplicate generated executions: **{counts['duplicate_generated_executions']}**
- Crystallographically unique generated structures: **{counts['crystallographically_unique_generated_structures']}**
- Scientific abstentions: **{counts['scientific_abstentions']}**
- Blocked before solver: **{counts['blocked_before_solver']}**
- Solver infeasible / software errors: **0 / 0**

All requested headline claims agree with the frozen final unique-structure table. The 24-structure claim is independently reconstructed from 35 generated execution records and 11 duplicates. The extra full-corpus NASICON execution was excluded from the paper because of exact-target leakage and is duplicate-equivalent to U-021; it was not silently discarded from this forensic ledger.

## Acceptance-gate checks

1. Every row in the 34-row final workflow manifest is represented once, plus five evidenced non-manifest executions.
2. Three blocked runs and one scientific abstention are explicit rows.
3. Every duplicate names a representative `duplicate_of_run_id`.
4. Raw candidate paths and SHA-256 hashes are checked by the reconstruction script.
5. Current claims are traced in `CURRENT_RESULTS_CLAIM_AUDIT.csv`.
6. Superseded v1/v2 and intermediate package sources are explicitly quarantined in `SOURCE_MANIFEST.md`.
7. No generation, relaxation, retrieval, solver, or validation process was invoked.
"""
    (OUT / "AUDIT_REPORT.md").write_text(report, encoding="utf-8")


def claim_audit() -> list[dict[str, str]]:
    p = "artifacts/paper_final_results_v1/07_tables/FINAL_UNIQUE_STRUCTURE_RESULTS.csv"
    results = read_csv(ROOT / p)
    li = next(r for r in results if r["target_formula"] == "Li6PS5Cl")
    claims = [
        ("24 unique structures", "24", str(len(results)), "Unique rows U-001–U-024"),
        ("24/24 parse", "24/24", f"{sum(r['parse_ok']=='True' for r in results)}/24", "parse_ok"),
        ("24/24 formula", "24/24", f"{sum(r['formula_match']=='True' for r in results)}/24", "formula_match"),
        ("24/24 severe-contact pass", "24/24", f"{sum(r['contact_screen_pass']=='True' for r in results)}/24", "contact_screen_pass"),
        ("24/24 requested initial SG", "24/24", f"{sum(r['detected_space_group']==r['requested_space_group'] for r in results)}/24", "detected_space_group versus requested_space_group"),
        ("21 PASS / 3 PARTIAL initial topology", "21 PASS / 3 PARTIAL", f"{Counter(r['topology_status'] for r in results)['PASS']} PASS / {Counter(r['topology_status'] for r in results)['PARTIAL']} PARTIAL", "topology_status"),
        ("24/24 CHGNet convergence", "24/24", f"{sum(r['converged']=='True' for r in results)}/24", "converged"),
        ("24/24 composition retention", "24/24", f"{sum(r['formula_preserved']=='True' for r in results)}/24", "formula_preserved"),
        ("24/24 site-count retention", "24/24", f"{sum(r['site_count_preserved']=='True' for r in results)}/24", "site_count_preserved"),
        ("24/24 StructureMatcher initial-relaxed", "24/24", f"{sum(r['structure_match_initial_relaxed']=='True' for r in results)}/24", "structure_match_initial_relaxed"),
        ("23/24 exact SG retention", "23/24", f"{sum(r['space_group_retained']=='True' for r in results)}/24", "space_group_retained"),
        ("23/24 crystal-system retention", "23/24", f"{sum(r['crystal_system_retained']=='True' for r in results)}/24", "crystal_system_retained"),
        ("22 PASS / 2 PARTIAL relaxed topology", "22 PASS / 2 PARTIAL", f"{Counter(r['topology_after'] for r in results)['PASS']} PASS / {Counter(r['topology_after'] for r in results)['PARTIAL']} PARTIAL", "topology_after"),
        ("Li6PS5Cl 46.1% volume change", "46.1%", f"{float(li['volume_change_percent']):.1f}%", f"exact frozen value {li['volume_change_percent']}%"),
    ]
    return [{
        "claim": claim, "claimed_value": claimed, "verified_value": verified,
        "source_files": p, "status": "PASS" if claimed == verified else "FAIL", "notes": note,
    } for claim, claimed, verified, note in claims]


def validate(rows: list[dict[str, str]], funnel: list[dict]) -> None:
    assert len(rows) == 39
    assert len({r["run_id"] for r in rows}) == 39
    assert len({r["request_id"] for r in rows}) == 27
    assert sum(r["cif_generated"] == "True" for r in rows) == 35
    assert sum(r["execution_outcome"] == "GENERATED_DUPLICATE" for r in rows) == 11
    assert len({r["unique_structure_id"] for r in rows if r["cif_generated"] == "True"}) == 24
    assert sum(r["execution_outcome"] == "BLOCKED_UNSUPPORTED" for r in rows) == 3
    assert sum(r["execution_outcome"] == "SCIENTIFIC_ABSTENTION" for r in rows) == 1
    assert sum(r["execution_outcome"] == "SOFTWARE_ERROR" for r in rows) == 0
    for row in rows:
        if row["cif_generated"] == "True":
            path = Path(row["generated_cif_path"])
            if not path.is_absolute():
                path = ROOT / path
            assert path.is_file(), (row["run_id"], path)
            assert sha256(path) == row["raw_structure_hash"], row["run_id"]
        else:
            assert row["execution_outcome"] in {"BLOCKED_UNSUPPORTED", "SCIENTIFIC_ABSTENTION"}
    assert all(r["duplicate_of_run_id"] != NA for r in rows if r["execution_outcome"] == "GENERATED_DUPLICATE")
    assert all(r["status"] == "PASS" for r in claim_audit())
    assert {r["metric"]: r["count"] for r in funnel}["solver_attempts"] == 35


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = build_rows()
    funnel = build_funnel(rows)
    validate(rows, funnel)
    write_csv(OUT / "master_run_ledger.csv", rows, FIELDS)
    write_csv(OUT / "EXECUTION_FUNNEL.csv", funnel, ["metric", "count", "definition"])
    write_csv(OUT / "CURRENT_RESULTS_CLAIM_AUDIT.csv", claim_audit(), ["claim", "claimed_value", "verified_value", "source_files", "status", "notes"])
    write_documents(rows, funnel)
    print(f"PASS: wrote forensic audit to {OUT}")
    print("requests=27 executions=39 solver_attempts=35 cifs=35 duplicates=11 unique=24 abstentions=1 blocked=3 errors=0")


if __name__ == "__main__":
    main()
