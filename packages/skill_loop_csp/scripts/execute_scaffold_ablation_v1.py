"""Execute the frozen prospective Scaffold-Prior Ablation V1.

This is execution/provenance/reporting code only. Every scientific run is
delegated to the canonical ``run_csp_workflow`` API at the frozen commit.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymatgen.core import Composition, Structure

from launch_final_paper_benchmark_v3 import exclusion_counts, latest_attempt, structure_metrics
from sok_llm_orchestrator.bench.prospective import FrozenReference, ProspectiveBenchmarkStages
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages, WorkflowConfig, run_csp_workflow


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "artifacts" / "scaffold_ablation_v1"
RESULTS = FREEZE / "results"
LEDGER = RESULTS / "EXECUTION_LEDGER.csv"
WORKFLOW_COMMIT = "22617f414eb41892c04c59aa6e933a7789a2818f"
EXPECTED_CORPUS = "mp_stable_10k_v1"
EXPECTED_REGULATOR = "icsd_broad_regulator_v1"
EXPECTED_REGULATOR_HASH = "be0a8f620fca62aa3bb755d76ac9edeeb8aa1ac507c4800001e4018b94c6cf0c"
CONDITIONS = (
    ("MINIMAL_REGULATOR_ONLY", "disabled", "minimal_regulator_only"),
    ("MINIMAL_REGULATOR_PLUS_REQUEST", "enabled", "minimal_regulator_plus_request"),
)
TERMINAL = {"PASS"}

LEDGER_FIELDS = [
    "sequence_number", "case_id", "target", "condition", "run_id", "attempt_id",
    "workflow_commit", "freeze_sha256", "request", "request_spp_mode", "corpus_id",
    "corpus_hash", "retrieval_backend", "retrieval_ids", "retrieval_ids_sha256",
    "reference_ID_exclusions", "raw_duplicate_exclusions", "canonical_duplicate_exclusions",
    "StructureMatcher_exclusions", "reference_equivalent_evidence_count", "required_pairs",
    "request_usable_pairs", "fallback_pairs", "unsupported_pairs", "required_pair_count",
    "request_usable_pair_count", "regulator_fallback_pair_count", "unsupported_pair_count",
    "request_usable_fraction", "fallback_fraction", "request_spp_run_id", "request_spp_hash",
    "regulator_id", "regulator_hash", "scaffold_mode", "scaffold_id", "candidate_sites",
    "feasible_state_count", "selected_assignment", "solver_status", "solver_objective",
    "independent_objective", "objective_difference", "objective_parity", "request_objective",
    "regulator_objective", "combined_objective", "cif_path", "cif_hash", "cif_parse",
    "exact_composition", "sca_status", "sca_topology", "sca_result_json", "reference_id",
    "reference_cif_hash", "reference_match", "generated_space_group", "reference_space_group",
    "exact_space_group_agreement", "generated_crystal_system", "reference_crystal_system",
    "crystal_system_agreement", "generated_volume_A3", "reference_volume_A3",
    "generated_volume_per_atom_A3", "reference_volume_per_atom_A3",
    "absolute_volume_error_percent", "minimum_distance_A", "workflow_status", "failure_stage",
    "failure_code", "failure_message", "started_at", "completed_at",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    columns = fields or list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify_freeze() -> dict[str, Any]:
    payload = json.loads((FREEZE / "SCAFFOLD_ABLATION_FREEZE.json").read_text(encoding="utf-8"))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if commit != WORKFLOW_COMMIT or commit != payload["workflow_commit"]:
        raise RuntimeError(f"workflow commit changed: {commit}")
    source_diff = subprocess.check_output(
        ["git", "diff", "--name-only", WORKFLOW_COMMIT, "--", "src"], cwd=ROOT, text=True,
    ).strip()
    source_untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src"], cwd=ROOT, text=True,
    ).strip()
    if source_diff or source_untracked:
        raise RuntimeError(f"scientific source diff detected: tracked={source_diff!r}, untracked={source_untracked!r}")
    manifest = read_csv(FREEZE / "OUTPUT_HASH_MANIFEST.csv")
    if len(manifest) != 12:
        raise RuntimeError(f"freeze manifest is not 12/12: {len(manifest)}")
    for row in manifest:
        actual = sha256(FREEZE / row["path"])
        if actual != row["sha256"]:
            raise RuntimeError(f"frozen hash mismatch: {row['path']}: {actual}")
    for relative, expected in payload["protected_results"].items():
        actual = sha256(ROOT / relative)
        if actual != expected:
            raise RuntimeError(f"protected historical result changed: {relative}: {actual}")
    if payload["benchmark_solves_before_freeze"] != 0 or payload["planned_executions"] != 10:
        raise RuntimeError("invalid frozen prospective execution counts")
    return payload


def frozen_references() -> dict[str, FrozenReference]:
    references: dict[str, FrozenReference] = {}
    for row in read_csv(FREEZE / "REFERENCES.csv"):
        reference = FrozenReference.from_cif(
            case_id=row["case_id"], formula=row["formula"], reference_id=row["reference_id"],
            source_structure_id=row["source_structure_id"], cif_path=ROOT / row["reference_cif_path"],
        )
        if reference.raw_sha256 != row["cif_sha256"] or reference.canonical_sha256 != row["canonical_sha256"]:
            raise RuntimeError(f"wrong frozen reference for {row['formula']}")
        references[row["formula"]] = reference
    return references


def pre_qlip_invariants(task: dict[str, Any], expected: dict[str, str]) -> dict[str, Any]:
    stages = ProductionWorkflowStages()
    config = WorkflowConfig(output_root=RESULTS, scaffold_mode="minimal", request_spp_mode="disabled")
    scaffold_id, structure, orbits = stages._scaffold(task, config)
    assignments = stages.enumerate_feasible_assignments(task, config)
    formula_species = sorted(Composition(task["formula"]).get_el_amt_dict(), key=str.lower)
    position_payload = {
        "lattice": [round(float(value), 12) for row in structure.lattice.matrix for value in row],
        "fractional_positions": [[round(float(value) % 1.0, 12) for value in row] for row in structure.frac_coords],
    }
    failures = []
    if len(structure) != 5:
        failures.append("candidate sites != 5")
    if len(orbits) != 5 or any(len(orbit["site_indices"]) != 1 for orbit in orbits):
        failures.append("domains are not five singleton sites")
    if any(orbit.get("required_occupancy") is not True or orbit.get("vacancy_allowed") for orbit in orbits):
        failures.append("not all sites are required occupied")
    if any("fixed_species" in orbit for orbit in orbits):
        failures.append("fixed/target occupation encoded")
    if any(sorted(map(str, orbit["allowed_species"]), key=str.lower) != formula_species for orbit in orbits):
        failures.append("role/site species constraint encoded")
    if len(assignments) != 20:
        failures.append(f"feasible assignments != 20 ({len(assignments)})")
    if scaffold_id != expected["scaffold_id"]:
        failures.append(f"scaffold id changed ({scaffold_id})")
    if json_hash(position_payload) != expected["candidate_cell_position_hash"]:
        failures.append("candidate cell/positions changed")
    if json_hash(assignments) != expected["assignment_set_sha256"]:
        failures.append("assignment set changed")
    target_counts = {str(k): int(round(float(v))) for k, v in Composition(expected["exact_formula"]).get_el_amt_dict().items()}
    if any({species: assignment.count(species) for species in target_counts} != target_counts for assignment in assignments):
        failures.append("enumerated assignment violates exact composition")
    if failures:
        raise RuntimeError(f"minimal pre-QLIP invariant failure for {task['formula']}: {failures}")
    return {"candidate_sites": 5, "feasible_state_count": 20, "scaffold_id": scaffold_id}


def selected_assignment(cif_path: Path, task: dict[str, Any]) -> str:
    stages = ProductionWorkflowStages()
    config = WorkflowConfig(output_root=RESULTS, scaffold_mode="minimal")
    _, scaffold, _ = stages._scaffold(task, config)
    generated = Structure.from_file(cif_path)
    if len(generated) != len(scaffold):
        raise RuntimeError("generated CIF site count changed from minimal scaffold")
    unused = set(range(len(generated)))
    selected: list[str] = []
    for index, site in enumerate(scaffold):
        ranked = sorted(
            ((float(scaffold.lattice.get_distance_and_image(site.frac_coords, generated[j].frac_coords)[0]), j) for j in unused),
            key=lambda item: (item[0], item[1]),
        )
        distance, match = ranked[0]
        if distance > 1e-5:
            raise RuntimeError(f"generated site geometry changed at site_{index:03d}: {distance}")
        unused.remove(match)
        selected.append(f"site_{index:03d}={generated[match].specie}")
    return ";".join(selected)


def crystal_systems(metrics: dict[str, Any], cif: Path, reference: FrozenReference) -> None:
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    metrics["generated_crystal_system"] = SpacegroupAnalyzer(Structure.from_file(cif), symprec=1e-2, angle_tolerance=5).get_crystal_system()
    metrics["reference_crystal_system"] = SpacegroupAnalyzer(Structure.from_file(reference.cif_path), symprec=1e-2, angle_tolerance=5).get_crystal_system()


def append_terminal(row: dict[str, Any]) -> None:
    rows = read_csv(LEDGER)
    key = (row["case_id"], row["condition"])
    if any((item["case_id"], item["condition"]) == key and item["workflow_status"] in TERMINAL for item in rows):
        raise RuntimeError(f"refusing to overwrite terminal execution: {key}")
    rows.append({field: row.get(field, "") for field in LEDGER_FIELDS})
    write_csv(LEDGER, rows, LEDGER_FIELDS)


def validate_frozen_objective_provenance(
    trace: dict[str, Any], *, request_mode: str, outer_scale: float = 10.0,
    regulator_coefficient: float = 2.0, tolerance: float = 1e-6,
) -> dict[str, float]:
    """Validate the objective from canonical wire/decomposition evidence.

    ``outer_objective_scale`` and ``regulator_coefficient`` are WorkflowConfig
    fields, not guaranteed adapter-diagnostic keys.  QLIP's actual wire
    representation is the adapter representation/guidance weight, and the
    retained pair decomposition independently proves the effective weights.
    """
    adapter = trace.get("qlip_adapter") or {}
    pairs = list(trace.get("pair_components") or [])
    if not pairs:
        raise RuntimeError("objective provenance lacks pair components")
    request_score = sum(float(row["request_pair_score"]) for row in pairs)
    regulator_score = sum(float(row["regulator_pair_score"]) for row in pairs)
    pair_total = sum(float(row["combined_pair_score"]) for row in pairs)
    expected_total = outer_scale * (request_score + regulator_coefficient * regulator_score)
    solver_objective = float(trace["solver_objective"])
    independent_objective = float(trace["independent_objective"])

    if request_mode == "disabled":
        expected_representation = "REGULATOR_AS_PRIMARY_WEIGHTED"
        expected_wire_weight = outer_scale * regulator_coefficient
        if abs(request_score) >= tolerance or abs(float(trace.get("request_component", 0.0))) >= tolerance:
            raise RuntimeError("request-disabled objective has a nonzero request contribution")
        if any(str(row.get("request_pair_status")) != "REQUEST_DISABLED" for row in pairs):
            raise RuntimeError("request-disabled objective contains an active request pair")
        regulator_root = str(trace.get("regulator_root") or trace.get("regulator_path") or "")
        primary_root = str(adapter.get("primary_pot_root") or "")
        if regulator_root and primary_root and Path(primary_root).resolve() != Path(regulator_root).resolve():
            raise RuntimeError("regulator-only QLIP input does not use the frozen regulator as primary POT root")
    elif request_mode == "enabled":
        expected_representation = "REQUEST_PLUS_REGULATOR_FALLBACK"
        expected_wire_weight = outer_scale
    else:
        raise ValueError(f"unsupported request mode: {request_mode}")

    if adapter.get("representation") != expected_representation:
        raise RuntimeError(f"wrong QLIP objective representation: {adapter.get('representation')}")
    if abs(float(adapter.get("guidance_weight", float("nan"))) - expected_wire_weight) >= tolerance:
        raise RuntimeError("wrong outer objective scale in QLIP wire representation")
    for row in pairs:
        expected_pair = outer_scale * (
            float(row["request_pair_score"]) + regulator_coefficient * float(row["regulator_pair_score"])
        )
        if abs(float(row["combined_pair_score"]) - expected_pair) >= tolerance:
            raise RuntimeError(f"wrong effective regulator/request coefficient for {row.get('species_pair')}")
    if abs(float(trace.get("request_component", request_score)) - request_score) >= tolerance:
        raise RuntimeError("request component disagrees with pair decomposition")
    if abs(float(trace.get("regulator_component", regulator_score)) - regulator_score) >= tolerance:
        raise RuntimeError("regulator component disagrees with pair decomposition")
    if abs(pair_total - expected_total) >= tolerance:
        raise RuntimeError("combined pair objective disagrees with frozen coefficients")
    if abs(independent_objective - expected_total) >= tolerance:
        raise RuntimeError("independent objective disagrees with frozen coefficients")
    if abs(solver_objective - expected_total) >= tolerance:
        raise RuntimeError("solver objective disagrees with frozen coefficients")
    if abs(solver_objective - independent_objective) >= tolerance:
        raise RuntimeError("objective parity failure")
    return {
        "request_score": request_score, "regulator_score": regulator_score,
        "expected_total": expected_total, "solver_objective": solver_objective,
        "absolute_difference": abs(solver_objective - expected_total),
    }


def run_one(sequence: int, target: dict[str, str], condition: str, request_mode: str, directory: str,
            reference: FrozenReference, minimal_row: dict[str, str], freeze_payload: dict[str, Any]) -> dict[str, Any]:
    verify_freeze()
    production = ProductionWorkflowStages()
    task = production.normalise(target["formula"])
    invariants = pre_qlip_invariants(task, minimal_row)
    request = f"Generate {task['formula']} as a {task['family']} crystal with requested {task['space_group']} symmetry."
    output_root = RESULTS / directory / target["case_id"] / condition
    stages = ProspectiveBenchmarkStages(tasks=ProductionWorkflowStages._TASKS, reference=reference)
    config = WorkflowConfig(
        output_root=output_root, retrieval_depth=40, retrieval_demo_export=True,
        excluded_structure_ids=(reference.reference_id, reference.source_structure_id),
        scaffold_mode="minimal", request_spp_mode=request_mode, stages=stages,
    )
    started = now()
    try:
        result = run_csp_workflow(request, config)
        freeze_payload = verify_freeze()
        manifest, trace = latest_attempt(output_root)
        exclusions = exclusion_counts(stages)
        if result.corpus_id != EXPECTED_CORPUS:
            raise RuntimeError(f"wrong corpus: {result.corpus_id}")
        if result.regulator_spp_hash != EXPECTED_REGULATOR_HASH:
            raise RuntimeError(f"wrong regulator hash: {result.regulator_spp_hash}")
        if exclusions["reference_equivalent_evidence_count"] != 0:
            raise RuntimeError("reference leakage reached request-SPP fitting")
        if result.unsupported_pair_count != 0:
            raise RuntimeError("unsupported guidance reached QLIP")
        if result.objective_difference >= 1e-6:
            raise RuntimeError(f"objective parity failure: {result.objective_difference}")
        if result.scaffold_mode != "minimal" or result.scaffold_id != invariants["scaffold_id"] or result.feasible_state_count != 20:
            raise RuntimeError("wrong minimal scaffold reached QLIP")
        pair_rows = list(result.request_spp_quality.get("request_pair_results", []))
        required_pairs = [str(row["species_pair"]) for row in pair_rows]
        usable = [str(row["species_pair"]) for row in pair_rows if row.get("request_pair_status") == "REQUEST_USABLE"]
        fallback = [str(row["species_pair"]) for row in pair_rows if str(row.get("guidance_mode", "")).startswith("REGULATOR_ONLY")]
        unsupported = [str(row["species_pair"]) for row in pair_rows if row.get("guidance_mode") == "UNSUPPORTED_REQUIRED_PAIR"]
        if len(required_pairs) != 6 or len(usable) != result.request_supported_pair_count or len(fallback) != result.regulator_fallback_pair_count or unsupported:
            raise RuntimeError("corrupt pair-coverage provenance")
        if request_mode == "disabled":
            if result.request_component != 0.0 or usable or len(fallback) != 6:
                raise RuntimeError("regulator-only objective/coverage contract violated")
        else:
            expected_counts = (int(target["frozen_request_usable_pairs"]), int(target["frozen_regulator_fallback_pairs"]))
            if (len(usable), len(fallback)) != expected_counts:
                raise RuntimeError(f"request-SPP coverage changed: {(len(usable), len(fallback))} != {expected_counts}")
            if result.request_spp_run_id != result.run_id:
                raise RuntimeError("request SPP is not fresh for this run")
        validate_frozen_objective_provenance(trace, request_mode=request_mode)
        metrics = structure_metrics(Path(result.generated_cif_path), reference, target["formula"])
        crystal_systems(metrics, Path(result.generated_cif_path), reference)
        request_hash = str(manifest.get("request_spp_hash", ""))
        if request_mode == "enabled" and not request_hash:
            raise RuntimeError("fresh request-SPP hash missing")
        row = {
            "sequence_number": sequence, "case_id": target["case_id"], "target": target["formula"],
            "condition": condition, "run_id": result.run_id, "attempt_id": result.attempt_id,
            "workflow_commit": WORKFLOW_COMMIT, "freeze_sha256": sha256(FREEZE / "SCAFFOLD_ABLATION_FREEZE.json"),
            "request": request, "request_spp_mode": request_mode, "corpus_id": result.corpus_id,
            "corpus_hash": result.corpus_hash, "retrieval_backend": result.provenance_manifest["retrieval_backend"],
            "retrieval_ids": ";".join(result.retrieved_ids), "retrieval_ids_sha256": json_hash(list(result.retrieved_ids)),
            **exclusions, "required_pairs": ";".join(required_pairs), "request_usable_pairs": ";".join(usable),
            "fallback_pairs": ";".join(fallback), "unsupported_pairs": ";".join(unsupported),
            "required_pair_count": len(required_pairs), "request_usable_pair_count": len(usable),
            "regulator_fallback_pair_count": len(fallback), "unsupported_pair_count": len(unsupported),
            "request_usable_fraction": len(usable) / len(required_pairs), "fallback_fraction": len(fallback) / len(required_pairs),
            "request_spp_run_id": result.request_spp_run_id, "request_spp_hash": request_hash,
            "regulator_id": EXPECTED_REGULATOR, "regulator_hash": result.regulator_spp_hash,
            "scaffold_mode": result.scaffold_mode, "scaffold_id": result.scaffold_id,
            "candidate_sites": 5, "feasible_state_count": result.feasible_state_count,
            "selected_assignment": selected_assignment(Path(result.generated_cif_path), task),
            "solver_status": result.solver_status, "solver_objective": result.solver_objective,
            "independent_objective": result.independent_objective, "objective_difference": result.objective_difference,
            "objective_parity": "PASS", "request_objective": result.request_component,
            "regulator_objective": result.regulator_component, "combined_objective": result.combined_objective,
            "cif_path": result.generated_cif_path, "cif_hash": result.generated_cif_hash,
            "sca_status": "PASS" if result.sca_result.get("parse_ok") else result.sca_result.get("status", "PARTIAL"),
            "sca_topology": result.sca_result.get("topology_status", "UNKNOWN"),
            "sca_result_json": json.dumps(result.sca_result, sort_keys=True), "reference_id": reference.reference_id,
            "reference_cif_hash": reference.raw_sha256, **metrics, "workflow_status": "PASS",
            "failure_stage": "", "failure_code": "", "failure_message": "", "started_at": started,
            "completed_at": manifest.get("completed_at", manifest.get("updated_at", now())),
        }
        append_terminal(row)
        return row
    except Exception as exc:
        manifest, trace = latest_attempt(output_root)
        failure = {
            "sequence_number": sequence, "case_id": target["case_id"], "target": target["formula"],
            "condition": condition, "run_id": manifest.get("run_id", trace.get("run_id", "")),
            "attempt_id": manifest.get("attempt_id", trace.get("attempt_id", "")), "workflow_commit": WORKFLOW_COMMIT,
            "freeze_sha256": sha256(FREEZE / "SCAFFOLD_ABLATION_FREEZE.json"), "request": request,
            "request_spp_mode": request_mode, "workflow_status": "FAILED_SOFTWARE_OR_PROVENANCE",
            "failure_stage": trace.get("failure_stage", "execution_validation"),
            "failure_code": trace.get("failure_code", type(exc).__name__), "failure_message": str(exc),
            "started_at": started, "completed_at": now(),
        }
        append_terminal(failure)
        raise


def classification(regulator: dict[str, str], request: dict[str, str]) -> tuple[str, str]:
    changed = regulator["selected_assignment"] != request["selected_assignment"]
    rmatch, qmatch = regulator["reference_match"] == "YES", request["reference_match"] == "YES"
    if not rmatch and qmatch:
        label = "IMPROVED"
    elif rmatch and not qmatch:
        label = "WORSENED"
    elif rmatch and qmatch:
        label = "UNCHANGED_REFERENCE"
    elif not changed:
        label = "UNCHANGED_NONREFERENCE"
    else:
        label = "CHANGED_BUT_NEITHER_REFERENCE"
    return label, "YES" if changed else "NO"


def finalize(rows: list[dict[str, str]]) -> None:
    if len(rows) != 10 or any(row["workflow_status"] != "PASS" for row in rows):
        raise RuntimeError("cannot finalize before ten successful terminal executions")
    by_key = {(row["target"], row["condition"]): row for row in rows}
    targets = [row["formula"] for row in read_csv(FREEZE / "TARGETS.csv")]
    comparisons = []
    for formula in targets:
        r = by_key[(formula, "MINIMAL_REGULATOR_ONLY")]
        q = by_key[(formula, "MINIMAL_REGULATOR_PLUS_REQUEST")]
        label, changed = classification(r, q)
        comparisons.append({
            "target": formula, "regulator_only_assignment": r["selected_assignment"],
            "regulator_plus_request_assignment": q["selected_assignment"], "selected_assignment_changed": changed,
            "regulator_only_reference_match": r["reference_match"],
            "regulator_plus_request_reference_match": q["reference_match"], "classification": label,
        })
    historical = read_csv(FREEZE / "HISTORICAL_V3_ARMS.csv")
    strength = []
    for row in historical:
        guidance = "REGULATOR_PLUS_REQUEST" if row["condition_id"].endswith("PLUS_REQUEST") else "REGULATOR_ONLY"
        strength.append({
            "target": row["formula"], "guidance_mode": guidance, "scaffold_level": row["scaffold_mode"].upper(),
            "feasible_state_count": row["feasible_state_count"], "reference_match": row["reference_match"],
            "exact_space_group_agreement": row["exact_space_group_agreement"],
            "crystal_system_agreement": row["crystal_system_agreement"],
            "absolute_volume_error_percent": row["absolute_volume_error_percent"], "sca_status": row["sca_status"],
            "source": "FROZEN_V3_HISTORICAL",
        })
    for row in rows:
        strength.append({
            "target": row["target"], "guidance_mode": "REGULATOR_PLUS_REQUEST" if row["request_spp_mode"] == "enabled" else "REGULATOR_ONLY",
            "scaffold_level": "MINIMAL", "feasible_state_count": row["feasible_state_count"],
            "reference_match": row["reference_match"], "exact_space_group_agreement": row["exact_space_group_agreement"],
            "crystal_system_agreement": row["crystal_system_agreement"],
            "absolute_volume_error_percent": row["absolute_volume_error_percent"], "sca_status": row["sca_status"],
            "source": "NEW_PROSPECTIVE_ABLATION",
        })
    write_csv(RESULTS / "MINIMAL_ABLATION_RESULTS.csv", rows, LEDGER_FIELDS)
    write_json(RESULTS / "MINIMAL_ABLATION_RESULTS.json", rows)
    write_csv(RESULTS / "MINIMAL_REQUEST_SPP_COMPARISON.csv", comparisons)
    write_csv(RESULTS / "SCAFFOLD_STRENGTH_COMPARISON.csv", strength)

    counts = {label: sum(row["classification"] == label for row in comparisons) for label in (
        "IMPROVED", "WORSENED", "UNCHANGED_REFERENCE", "UNCHANGED_NONREFERENCE", "CHANGED_BUT_NEITHER_REFERENCE")}
    recovery = {}
    for guidance in ("REGULATOR_ONLY", "REGULATOR_PLUS_REQUEST"):
        for level in ("TIGHT", "LOOSE", "MINIMAL"):
            selected = [row for row in strength if row["guidance_mode"] == guidance and row["scaffold_level"] == level]
            recovery[(guidance, level)] = sum(row["reference_match"] == "YES" for row in selected)
    condition_rows = {
        condition: [row for row in rows if row["condition"] == condition]
        for condition, _, _ in CONDITIONS
    }
    aggregates = {}
    for condition, selected in condition_rows.items():
        aggregates[condition] = {
            "reference_matches": sum(row["reference_match"] == "YES" for row in selected),
            "median_absolute_volume_error_percent": statistics.median(float(row["absolute_volume_error_percent"]) for row in selected),
            "median_request_usable_fraction": statistics.median(float(row["request_usable_fraction"]) for row in selected),
            "median_fallback_fraction": statistics.median(float(row["fallback_fraction"]) for row in selected),
        }
    changed = sum(row["selected_assignment_changed"] == "YES" for row in comparisons)
    per_target = ["# Scaffold Ablation Per Target", ""]
    for item in comparisons:
        per_target.extend([
            f"## {item['target']}", "",
            f"- Regulator only: `{item['regulator_only_assignment']}`; reference match {item['regulator_only_reference_match']}.",
            f"- Regulator + request: `{item['regulator_plus_request_assignment']}`; reference match {item['regulator_plus_request_reference_match']}.",
            f"- Assignment changed: {item['selected_assignment_changed']}; classification: {item['classification']}.", "",
        ])
    (RESULTS / "SCAFFOLD_ABLATION_PER_TARGET.md").write_text("\n".join(per_target), encoding="utf-8")

    rrec = aggregates["MINIMAL_REGULATOR_ONLY"]["reference_matches"]
    qrec = aggregates["MINIMAL_REGULATOR_PLUS_REQUEST"]["reference_matches"]
    if rrec == qrec and changed == 0:
        interpretation = "The request-specific SPP changed no selections and did not compensate for removing scaffold prior in this benchmark."
    elif qrec > rrec:
        interpretation = "Request-specific retrieval guidance improved recovery when the scaffold prior was weakened."
    elif qrec < rrec:
        interpretation = "Request-specific SPP mis-ranked at least one candidate under the weak scaffold constraint."
    else:
        interpretation = "Request-specific SPP changed selections without changing aggregate reference recovery."
    summary = f"""# Scaffold-Prior Ablation Summary

This is a prospective comparison of five frozen targets. The new runs use 20-state minimal scaffolds; tight and loose values are immutable V3 results.

## New minimal comparison

- Regulator only reference recovery: {rrec}/5.
- Regulator + request reference recovery: {qrec}/5.
- Request SPP changed selection: {changed}/5.
- Improved: {counts['IMPROVED']}/5; worsened: {counts['WORSENED']}/5.
- Unchanged reference: {counts['UNCHANGED_REFERENCE']}/5; unchanged non-reference: {counts['UNCHANGED_NONREFERENCE']}/5; changed but neither reference: {counts['CHANGED_BUT_NEITHER_REFERENCE']}/5.
- Regulator-only median volume error: {aggregates['MINIMAL_REGULATOR_ONLY']['median_absolute_volume_error_percent']:.6g}%.
- Regulator + request median volume error: {aggregates['MINIMAL_REGULATOR_PLUS_REQUEST']['median_absolute_volume_error_percent']:.6g}%.
- Regulator-only median request-usable/fallback fractions: {aggregates['MINIMAL_REGULATOR_ONLY']['median_request_usable_fraction']:.6g}/{aggregates['MINIMAL_REGULATOR_ONLY']['median_fallback_fraction']:.6g}.
- Regulator + request median request-usable/fallback fractions: {aggregates['MINIMAL_REGULATOR_PLUS_REQUEST']['median_request_usable_fraction']:.6g}/{aggregates['MINIMAL_REGULATOR_PLUS_REQUEST']['median_fallback_fraction']:.6g}.

## Scaffold strength

| Guidance | Tight (1) | Loose (2) | Minimal (20) |
|---|---:|---:|---:|
| Regulator only | {recovery[('REGULATOR_ONLY','TIGHT')]}/5 | {recovery[('REGULATOR_ONLY','LOOSE')]}/5 | {recovery[('REGULATOR_ONLY','MINIMAL')]}/5 |
| Regulator + request | {recovery[('REGULATOR_PLUS_REQUEST','TIGHT')]}/5 | {recovery[('REGULATOR_PLUS_REQUEST','LOOSE')]}/5 | {recovery[('REGULATOR_PLUS_REQUEST','MINIMAL')]}/5 |

## Paper-ready result

1. Recovery across 1 → 2 → 20 states is shown in the table; it is the measured scaffold-prior effect.
2. In the 20-state space, request-specific SPP changed {changed}/5 selections and improved {counts['IMPROVED']}/5.
3. {interpretation}
4. Dominance is assigned only from the measured recovery pattern above; objective values are not compared across search spaces.
"""
    (RESULTS / "SCAFFOLD_ABLATION_SUMMARY.md").write_text(summary, encoding="utf-8")
    audit = {
        "completed_at": now(), "workflow_commit": WORKFLOW_COMMIT, "freeze_status": "PASS",
        "manifest_status": "12/12 PASS", "scientific_source_diff": 0, "executions_planned": 10,
        "executions_completed": 10, "software_failures": 0, "objective_parity_failures": 0,
        "leakage_violations": 0, "unsupported_pairs": 0,
        "protected_results": verify_freeze()["protected_results"],
        "output_hashes": {path.name: sha256(path) for path in sorted(RESULTS.glob("*")) if path.is_file()},
    }
    write_json(RESULTS / "provenance" / "FINAL_PROVENANCE.json", audit)
    (RESULTS / "SCAFFOLD_ABLATION_AUDIT.md").write_text(
        "# Scaffold Ablation Audit\n\n"
        "- Freeze verification: PASS (12/12).\n- Scientific source diff: 0.\n"
        "- New executions: 10/10 canonical runs.\n- Objective parity failures: 0.\n"
        "- Reference leakage violations: 0.\n- Unsupported pairs reaching QLIP: 0.\n"
        "- Frozen V3 tight/loose arms were not rerun.\n",
        encoding="utf-8",
    )


def main() -> None:
    freeze_payload = verify_freeze()
    targets = read_csv(FREEZE / "TARGETS.csv")
    references = frozen_references()
    minimal = {
        row["formula"]: row for row in read_csv(FREEZE / "FEASIBLE_STATE_COUNTS.csv")
        if row["scaffold_level"] == "MINIMAL"
    }
    if [row["formula"] for row in targets] != ["BaTiO3", "CaTiO3", "CsPbBr3", "CsPbCl3", "CsSnBr3"]:
        raise RuntimeError("frozen target list changed")
    for target in targets:
        pre_qlip_invariants(ProductionWorkflowStages().normalise(target["formula"]), minimal[target["formula"]])

    for directory in ("minimal_regulator_only", "minimal_regulator_plus_request", "summary", "provenance"):
        (RESULTS / directory).mkdir(parents=True, exist_ok=True)
    write_json(RESULTS / "provenance" / "LAUNCH_FREEZE_VERIFICATION.json", {
        "verified_at": now(), "workflow_commit": WORKFLOW_COMMIT,
        "targets_sha256": sha256(FREEZE / "TARGETS.csv"),
        "references_sha256": sha256(FREEZE / "REFERENCES.csv"),
        "scaffold_definitions_sha256": sha256(FREEZE / "SCAFFOLD_LEVEL_DEFINITIONS.md"),
        "state_counts_sha256": sha256(FREEZE / "FEASIBLE_STATE_COUNTS.csv"),
        "guidance_sha256": sha256(FREEZE / "GUIDANCE_CONFIG.json"),
        "analysis_sha256": sha256(FREEZE / "ANALYSIS_PLAN.md"),
        "freeze_sha256": sha256(FREEZE / "SCAFFOLD_ABLATION_FREEZE.json"),
        "manifest_status": "12/12 PASS", "scientific_source_diff": 0,
        "minimal_feasible_states": {formula: 20 for formula in minimal},
        "candidate_cells_and_positions": "MATCH_FROZEN_HASHES",
        "protected_historical_artifacts": freeze_payload["protected_results"],
    })
    existing = read_csv(LEDGER)
    done = {(row["case_id"], row["condition"]) for row in existing if row["workflow_status"] in TERMINAL}
    sequence = max([int(row["sequence_number"]) for row in existing] or [0])
    for target in targets:
        for condition, request_mode, directory in CONDITIONS:
            key = (target["case_id"], condition)
            if key in done:
                print(f"SKIP terminal {target['formula']} {condition}", flush=True)
                continue
            sequence += 1
            row = run_one(sequence, target, condition, request_mode, directory, references[target["formula"]], minimal[target["formula"]], freeze_payload)
            print(f"[{sequence}/10] {target['formula']} {condition} {row['solver_status']} reference={row['reference_match']}", flush=True)
    rows = read_csv(LEDGER)
    finalize(rows)
    print("SCAFFOLD_ABLATION_V1_COMPLETE 10/10", flush=True)


if __name__ == "__main__":
    main()
