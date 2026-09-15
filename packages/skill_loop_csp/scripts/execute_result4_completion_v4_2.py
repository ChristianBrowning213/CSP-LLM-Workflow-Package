"""Execute the frozen four-case Result-4 completion V4.2 benchmark."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.bench.prospective import FrozenReference, ProspectiveBenchmarkStages
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
    _qlip_ordered_orbits_adapter,
    _qlip_target_formula,
    run_csp_workflow,
)


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "artifacts/final_paper_benchmark_result4_completion_v4_2"
RESULTS = FREEZE / "results"
POSITIVE_ROOT = RESULTS / "positive"
NEGATIVE_ROOT = RESULTS / "negative"
SUMMARY_ROOT = RESULTS / "summary"
PROVENANCE_ROOT = RESULTS / "provenance"
LEDGER = RESULTS / "EXECUTION_LEDGER.csv"
V4_1 = ROOT / "artifacts/final_paper_benchmark_result4_v4_1"
V3 = ROOT / "artifacts/final_paper_benchmark_v3"
COMBINED = ROOT / "artifacts/final_paper_combined_results"

WORKFLOW_COMMIT = "ac79cf0db324adf4c676ea2b8c288d42613dcd28"
FREEZE_SHA256 = "8a9d6d72080e4783c3d1e1d263cb746738b0482f239bd4797ddd3b3209e5bb12"
V4_1_COMMIT = "31feff023515b2ac32165fe95fb803412e21a5bc"
V4_1_FREEZE = "03d8c09bcb0986aad4628211d2e9b1c17a929ac86f58fd832c366fd865f9b3a0"
CORPUS_ID = "nasicon_specialist_v3"
CORPUS_SHA256 = "4392933d241c4f6397af9328fd2d43bd187f053da824887e0e34a43bd09d1ea4"
REGULATOR_ID = "icsd_broad_regulator_v1"
REGULATOR_SHA256 = "be0a8f620fca62aa3bb755d76ac9edeeb8aa1ac507c4800001e4018b94c6cf0c"

EXPECTED_FREEZE = {
    "RESULT4_COMPLETION_V4_2_PROTOCOL.md": "80b37924ac03847af0923c0d5c51e2e5534b406ecd6bbd7ec4ce867abe142779",
    "RESULT4_COMPLETION_V4_2_CASES.csv": "f64e808f1aef53e38aff07f72331cba28af780cb69164b5058a407a6c1963c3e",
    "RESULT4_COMPLETION_V4_2_REFERENCE.csv": "f4c70dee69480876fc332c8e6490a4202adca222f4c6a95dc65e19c3635cedb2",
    "RESULT4_COMPLETION_V4_2_CONFIG.json": "68e1f4c45cfe8db26904b34e95af21a9e7d4cd11caf053ba17508db55ef27b86",
    "RESULT4_COMPLETION_V4_2_FREEZE.json": FREEZE_SHA256,
}
PROTECTED_PRIOR = {
    V4_1 / "results/EXECUTION_LEDGER.csv": "3f7dac9d0481ef8083a4ce8a95fc4e926eacafc81882d4358ef0557a7aff4c08",
    V3 / "results/result_2_heldout/RESULT_2_HELDOUT_RECOVERY.csv": "ee539ad8de148afc029b5494455d15a79b33cb362df3473e129d2c4557cfe0a0",
    V3 / "results/result_3_factorial/RESULT_3_FACTORIAL.csv": "5688029447547363fe7fd62fcee6da5f0e4d378afab8f54499be5a5251925c3e",
    V3 / "results/EXECUTION_LEDGER.csv": "20919d60edbd3a15131448259c39e1141a50d6d7437eb510aba70a1d9277ac01",
}
PROTECTED_V4_1_CASES = {
    ("RDX-E4-A2", "workflow_trace.json"): "009034c60967d8f9eef47001f0660a4b498bc61bfef25fb5a7caec20655146e5",
    ("RDX-E4-A2", "generated.cif"): "90f8fc952510051ed6b9415d8100528f4490ebf2941d10573a4e736084a57b85",
    ("RDX-E4-C2", "workflow_trace.json"): "8929e2d332ece9557bbd1b4f7576860612bad1002c874cc4a29346af70595ef9",
    ("RDX-E4-C2", "generated.cif"): "f895e71a6951d1de4c521682d4b66b0a24b59982bd4c155a9d790c47b4e0b399",
}

FIELDS = [
    "sequence_number", "case_id", "formula", "case_type", "claim_class", "request",
    "run_id", "attempt_id", "workflow_commit", "freeze_hash",
    "canonical_target_formula", "qlip_formula", "formula_species", "fixed_species",
    "occupied_allowed_species", "required_guidance_species", "active_guidance_species",
    "formula_species_contract", "corpus_id", "corpus_hash", "retrieved_count", "retrieved_ids",
    "retrieved_ids_hash", "evidence_ids_hash", "reference_ID_exclusions", "raw_duplicate_exclusions",
    "canonical_duplicate_exclusions", "StructureMatcher_exclusions",
    "reference_equivalent_evidence_count", "required_pairs", "required_pair_count",
    "request_usable_pairs", "fallback_pairs", "unsupported_pairs", "request_spp_run_id",
    "request_spp_hash", "regulator_id", "regulator_hash", "scaffold_id",
    "ordered_orbit_count", "orbit_membership_hash", "solver_invoked", "solver_status",
    "solver_objective", "independent_objective", "objective_difference", "objective_parity",
    "cif_emitted", "cif_path", "cif_hash", "cif_parse", "exact_composition", "sca_status",
    "reference_id", "reference_cif_hash", "reference_match", "generated_space_group",
    "reference_space_group", "exact_space_group_agreement", "generated_crystal_system",
    "reference_crystal_system", "crystal_system_agreement", "generated_volume_A3",
    "reference_volume_A3", "absolute_volume_error_A3", "generated_volume_per_atom_A3",
    "reference_volume_per_atom_A3", "absolute_volume_error_percent", "representability_status",
    "workflow_status", "failure_stage", "failure_code", "failure_message", "started_at", "completed_at",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def latest_artifacts(output_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifests = sorted(output_root.glob("attempts/*/attempt_manifest.json"), key=lambda p: p.stat().st_mtime_ns)
    if not manifests:
        return {}, {}
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    trace_path = manifests[-1].parent / "workflow_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8")) if trace_path.is_file() else {}
    return manifest, trace


def verify_freeze() -> None:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != WORKFLOW_COMMIT:
        raise RuntimeError(f"workflow commit mismatch: {head}")
    for name, expected in EXPECTED_FREEZE.items():
        if sha256(FREEZE / name) != expected:
            raise RuntimeError(f"freeze hash mismatch: {name}")
    manifest = read_csv(FREEZE / "OUTPUT_HASH_MANIFEST.csv")
    if len(manifest) != 5 or any(sha256(FREEZE / row["path"]) != row["sha256"] for row in manifest):
        raise RuntimeError("V4.2 hash manifest mismatch")
    tracked = subprocess.check_output(
        ["git", "diff", "--name-only", WORKFLOW_COMMIT, "--", "src"], cwd=ROOT, text=True
    ).strip()
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src"], cwd=ROOT, text=True
    ).strip()
    if tracked or untracked:
        raise RuntimeError(f"scientific source diff: tracked={tracked!r}, untracked={untracked!r}")
    for path, expected in PROTECTED_PRIOR.items():
        if sha256(path) != expected:
            raise RuntimeError(f"protected prior hash mismatch: {path}")
    for (case_id, name), expected in PROTECTED_V4_1_CASES.items():
        root = V4_1 / f"results/positive/{case_id}/POSITIVE_CANONICAL/attempts"
        matches = list(root.glob(f"*/{name}"))
        if len(matches) != 1 or sha256(matches[0]) != expected:
            raise RuntimeError(f"protected V4.1 artifact mismatch: {case_id}/{name}")


def prepare_results() -> None:
    for path in (RESULTS, POSITIVE_ROOT, NEGATIVE_ROOT, SUMMARY_ROOT, PROVENANCE_ROOT):
        path.mkdir(parents=True, exist_ok=True)
    if not LEDGER.exists():
        write_csv(LEDGER, [], FIELDS)
    write_json(PROVENANCE_ROOT / "LAUNCH_FREEZE_VERIFICATION.json", {
        "verified_at": now(), "workflow_commit": WORKFLOW_COMMIT, "freeze_sha256": FREEZE_SHA256,
        "manifest": "5/5 PASS", "scientific_source_diff": [], "A2_C2_rerun": False,
        "V3_Result_2_rerun": False, "V3_Result_3_rerun": False,
        "protected_prior_hashes": {str(path.relative_to(ROOT)): value for path, value in PROTECTED_PRIOR.items()},
    })


def append_row(row: dict[str, Any]) -> None:
    rows = read_csv(LEDGER)
    if any(item["case_id"] == row["case_id"] for item in rows):
        raise RuntimeError(f"refusing to overwrite attempted case: {row['case_id']}")
    rows.append({field: row.get(field, "") for field in FIELDS})
    write_csv(LEDGER, rows, FIELDS)


def request_for(task: dict[str, Any], case_id: str) -> str:
    prefix = f"{case_id}: " if case_id.startswith("RDX-NEG") else ""
    return f"{prefix}Generate {task['formula']} as a {task['family']} crystal with requested {task['space_group']} symmetry."


def base_row(sequence: int, case: dict[str, str], request: str) -> dict[str, Any]:
    return {
        "sequence_number": sequence, "case_id": case["case_id"], "formula": case["formula"],
        "case_type": case["case_type"], "claim_class": case["classification"], "request": request,
        "workflow_commit": WORKFLOW_COMMIT, "freeze_hash": FREEZE_SHA256,
        "started_at": now(), "workflow_status": "STARTED",
    }


def reference() -> FrozenReference:
    rows = read_csv(FREEZE / "RESULT4_COMPLETION_V4_2_REFERENCE.csv")
    if len(rows) != 1 or rows[0]["case_id"] != "RDX-E4-F1":
        raise RuntimeError("wrong frozen reference table")
    row = rows[0]
    frozen = FrozenReference.from_cif(
        case_id=row["case_id"], formula=row["formula"], reference_id=row["reference_id"],
        source_structure_id=row["reference_id"], cif_path=ROOT / row["reference_cif_path"],
    )
    if frozen.raw_sha256 != row["reference_cif_sha256"] or frozen.canonical_sha256 != row["reference_canonical_sha256"]:
        raise RuntimeError("wrong F1 frozen reference")
    return frozen


def exclusion_metrics(stages: ProspectiveBenchmarkStages, evidence_ids: tuple[str, ...]) -> dict[str, Any]:
    exclusion = stages.last_exclusion
    if exclusion is None:
        raise RuntimeError("corrupt provenance: prospective exclusion audit missing")
    excluded = {
        row.structure_id for row in exclusion.audit
        if row.reference_id_match or row.raw_hash_match or row.canonical_hash_match or row.structurematcher_equivalent
    }
    leaked = sorted(excluded & set(evidence_ids))
    if leaked or exclusion.reference_equivalent_evidence_count != 0:
        raise RuntimeError(f"reference leakage: {leaked}")
    return {
        "reference_ID_exclusions": sum(row.reference_id_match for row in exclusion.audit),
        "raw_duplicate_exclusions": sum(row.raw_hash_match for row in exclusion.audit),
        "canonical_duplicate_exclusions": sum(row.canonical_hash_match for row in exclusion.audit),
        "StructureMatcher_exclusions": sum(row.structurematcher_equivalent for row in exclusion.audit),
        "reference_equivalent_evidence_count": exclusion.reference_equivalent_evidence_count,
    }


def contract_metrics(stages: ProspectiveBenchmarkStages, task: dict[str, Any], config: WorkflowConfig,
                     required_pairs: list[str], expected_scaffold: str) -> dict[str, Any]:
    scaffold_id, structure, orbits = stages._scaffold(task, config)
    if scaffold_id != expected_scaffold:
        raise RuntimeError(f"wrong scaffold: {scaffold_id} != {expected_scaffold}")
    wire = _qlip_ordered_orbits_adapter(orbits)
    qlip_formula = _qlip_target_formula(task, len(structure))
    formula_species = set(Composition(qlip_formula).get_el_amt_dict())
    fixed_species = {
        str(orbit["fixed_species"]) for orbit in wire
        if orbit.get("fixed_species") and orbit.get("fixed_species") != "VACANCY"
    }
    allowed = {
        str(species) for orbit in wire if str(orbit.get("required_state", "AUTO")).upper() != "EMPTY"
        for species in orbit.get("allowed_species", []) if str(species) != "VACANCY"
    }
    required_species = {species for pair in required_pairs for species in pair.split("-", 1)}
    active_species = set(required_species)
    missing = (fixed_species | allowed | required_species | active_species) - formula_species
    if missing:
        raise RuntimeError(f"formula/species invariant violation: {sorted(missing)}")
    membership = [{"orbit_id": row["orbit_id"], "site_indices": row["site_indices"]} for row in wire]
    return {
        "canonical_target_formula": task["formula"], "qlip_formula": qlip_formula,
        "formula_species": ";".join(sorted(formula_species)), "fixed_species": ";".join(sorted(fixed_species)),
        "occupied_allowed_species": ";".join(sorted(allowed)),
        "required_guidance_species": ";".join(sorted(required_species)),
        "active_guidance_species": ";".join(sorted(active_species)), "formula_species_contract": "PASS",
        "scaffold_id": scaffold_id, "ordered_orbit_count": len(wire),
        "orbit_membership_hash": json_hash(membership),
    }


def reference_metrics(cif_path: Path, frozen: FrozenReference, formula: str) -> dict[str, Any]:
    generated = Structure.from_file(cif_path)
    heldout = Structure.from_file(frozen.cif_path)
    gsga = SpacegroupAnalyzer(generated, symprec=1e-2, angle_tolerance=5)
    rsga = SpacegroupAnalyzer(heldout, symprec=1e-2, angle_tolerance=5)
    generated_sg, reference_sg = gsga.get_space_group_symbol(), rsga.get_space_group_symbol()
    generated_system, reference_system = gsga.get_crystal_system(), rsga.get_crystal_system()
    gvpa, rvpa = generated.volume / len(generated), heldout.volume / len(heldout)
    return {
        "cif_parse": "YES",
        "exact_composition": "YES" if generated.composition.reduced_composition == Composition(formula).reduced_composition else "NO",
        "reference_match": "YES" if StructureMatcher().fit(generated, heldout) else "NO",
        "generated_space_group": generated_sg, "reference_space_group": reference_sg,
        "exact_space_group_agreement": "YES" if generated_sg == reference_sg else "NO",
        "generated_crystal_system": generated_system, "reference_crystal_system": reference_system,
        "crystal_system_agreement": "YES" if generated_system == reference_system else "NO",
        "generated_volume_A3": generated.volume, "reference_volume_A3": heldout.volume,
        "absolute_volume_error_A3": abs(generated.volume - heldout.volume),
        "generated_volume_per_atom_A3": gvpa, "reference_volume_per_atom_A3": rvpa,
        "absolute_volume_error_percent": 100.0 * abs(gvpa - rvpa) / rvpa,
    }


def run_f1(sequence: int, case: dict[str, str], frozen: FrozenReference) -> dict[str, Any]:
    stages = ProspectiveBenchmarkStages(tasks=ProductionWorkflowStages._TASKS, reference=frozen)
    task = stages.normalise(case["formula"])
    if task["prototype"] != case["prototype"] or task["space_group"] != case["space_group"]:
        raise RuntimeError("F1 frozen task mapping mismatch")
    request = request_for(task, case["case_id"])
    base = base_row(sequence, case, request)
    output_root = POSITIVE_ROOT / case["case_id"] / "POSITIVE_CANONICAL"
    config = WorkflowConfig(
        output_root=output_root, retrieval_depth=40, retrieval_demo_export=True,
        excluded_structure_ids=(frozen.reference_id, frozen.source_structure_id),
        scaffold_mode="loose", request_spp_mode="enabled", stages=stages,
    )
    try:
        result = run_csp_workflow(request, config)
        verify_freeze()
        manifest, trace = latest_artifacts(output_root)
        if manifest.get("status") != "COMPLETED" or trace.get("workflow_status") != "PASS":
            raise RuntimeError("corrupt run provenance: completed manifest/trace missing")
        if result.corpus_id != CORPUS_ID or result.corpus_hash != CORPUS_SHA256:
            raise RuntimeError(f"wrong corpus: {result.corpus_id}/{result.corpus_hash}")
        if result.regulator_spp_hash != REGULATOR_SHA256:
            raise RuntimeError("wrong regulator")
        if result.unsupported_pair_count != 0:
            raise RuntimeError("unsupported guidance entered QLIP")
        if result.objective_difference >= 1e-6:
            raise RuntimeError(f"objective parity failure: {result.objective_difference}")
        if result.request_spp_run_id != result.run_id or not manifest.get("request_spp_hash"):
            raise RuntimeError("fresh request-SPP provenance mismatch")
        if result.run_id != manifest.get("run_id") or result.attempt_id != manifest.get("attempt_id"):
            raise RuntimeError("corrupt run/attempt provenance")
        required_pairs = list(trace.get("required_pairs", []))
        contract = contract_metrics(stages, result.normalised_task, config, required_pairs, case["prototype"])
        exclusions = exclusion_metrics(stages, result.spp_evidence_ids)
        cif_path = Path(result.generated_cif_path)
        metrics = reference_metrics(cif_path, frozen, case["formula"])
        if metrics["exact_composition"] != "YES":
            raise RuntimeError("formula/species invariant violation in generated CIF")
        row = {
            **base, **contract, **exclusions, **metrics,
            "run_id": result.run_id, "attempt_id": result.attempt_id,
            "corpus_id": result.corpus_id, "corpus_hash": result.corpus_hash,
            "retrieved_count": len(result.retrieved_ids), "retrieved_ids": ";".join(result.retrieved_ids),
            "retrieved_ids_hash": json_hash(list(result.retrieved_ids)),
            "evidence_ids_hash": json_hash(list(result.spp_evidence_ids)),
            "required_pairs": ";".join(required_pairs), "required_pair_count": len(required_pairs),
            "request_usable_pairs": result.request_supported_pair_count,
            "fallback_pairs": result.regulator_fallback_pair_count,
            "unsupported_pairs": result.unsupported_pair_count,
            "request_spp_run_id": result.request_spp_run_id, "request_spp_hash": manifest["request_spp_hash"],
            "regulator_id": REGULATOR_ID, "regulator_hash": result.regulator_spp_hash,
            "solver_invoked": "YES", "solver_status": result.solver_status,
            "solver_objective": result.solver_objective, "independent_objective": result.independent_objective,
            "objective_difference": result.objective_difference, "objective_parity": "PASS",
            "cif_emitted": "YES", "cif_path": str(cif_path), "cif_hash": result.generated_cif_hash,
            "sca_status": "PASS" if result.sca_result.get("parse_ok") else str(result.sca_result.get("status", "PARTIAL")),
            "reference_id": frozen.reference_id, "reference_cif_hash": frozen.raw_sha256,
            "representability_status": "PASS", "workflow_status": "PASS",
            "failure_stage": "", "failure_code": "", "failure_message": "",
            "started_at": manifest.get("started_at", base["started_at"]),
            "completed_at": manifest.get("completed_at", manifest.get("updated_at", now())),
        }
        append_row(row)
        return row
    except Exception as exc:
        manifest, trace = latest_artifacts(output_root)
        row = {
            **base, "run_id": manifest.get("run_id", trace.get("run_id", "")),
            "attempt_id": manifest.get("attempt_id", trace.get("attempt_id", "")),
            "corpus_id": trace.get("corpus_id", ""), "corpus_hash": trace.get("corpus_hash", ""),
            "solver_invoked": "YES" if trace.get("solver_status") not in {None, "", "NOT_REACHED"} else "NO",
            "solver_status": trace.get("solver_status", ""),
            "cif_emitted": "YES" if trace.get("CIF_generated") else "NO",
            "cif_path": trace.get("CIF_path", ""), "cif_hash": trace.get("CIF_hash", ""),
            "workflow_status": "FAILED_SOFTWARE_OR_PROVENANCE",
            "failure_stage": trace.get("failure_stage", getattr(exc, "stage", "orchestrator_validation")),
            "failure_code": trace.get("failure_code", getattr(exc, "code", type(exc).__name__)),
            "failure_message": str(exc), "completed_at": manifest.get("updated_at", now()),
        }
        append_row(row)
        raise


def run_negative(sequence: int, case: dict[str, str]) -> dict[str, Any]:
    stages = ProductionWorkflowStages()
    task = stages.normalise(f"{case['case_id']}: {case['formula']} requested {case['space_group']}")
    if task["prototype"] != case["prototype"] or task["space_group"] != case["space_group"]:
        raise RuntimeError(f"frozen negative task mapping mismatch: {case['case_id']}")
    request = request_for(task, case["case_id"])
    base = base_row(sequence, case, request)
    output_root = NEGATIVE_ROOT / case["case_id"] / "CONTROLLED_REPRESENTABILITY"
    config = WorkflowConfig(output_root=output_root, retrieval_depth=40, retrieval_demo_export=True,
                            scaffold_mode="loose", request_spp_mode="enabled", stages=stages)
    expected_stage, expected_code = case["expected_terminal"].split("/", 1)
    try:
        run_csp_workflow(request, config)
    except WorkflowStageError as exc:
        manifest, trace = latest_artifacts(output_root)
        try:
            verify_freeze()
            if exc.stage != expected_stage or exc.code != expected_code:
                raise RuntimeError(f"wrong controlled terminal: {exc.stage}/{exc.code}")
            if trace.get("corpus_id") != CORPUS_ID or trace.get("corpus_hash") != CORPUS_SHA256:
                raise RuntimeError("wrong corpus in negative terminal")
            if trace.get("solver_status") != "NOT_REACHED" or trace.get("CIF_generated"):
                raise RuntimeError("negative unexpectedly invoked solver or emitted CIF")
            if manifest.get("status") != "FAILED_CONTROLLED" or trace.get("execution_attempt_status") != "FAILED_CONTROLLED":
                raise RuntimeError("corrupt controlled-terminal provenance")
            row = {
                **base, "run_id": manifest.get("run_id"), "attempt_id": manifest.get("attempt_id"),
                "corpus_id": trace["corpus_id"], "corpus_hash": trace["corpus_hash"],
                "retrieved_count": trace.get("retrieval_count", 0),
                "retrieved_ids": ";".join(trace.get("retrieved_ids", [])),
                "retrieved_ids_hash": json_hash(trace.get("retrieved_ids", [])),
                "solver_invoked": "NO", "solver_status": "NOT_REACHED", "cif_emitted": "NO",
                "sca_status": "NOT_REACHED", "representability_status": "EXPECTED_ABSTENTION",
                "workflow_status": "EXPECTED_CONTROLLED_ABSTENTION", "failure_stage": exc.stage,
                "failure_code": exc.code, "failure_message": str(exc),
                "started_at": manifest.get("started_at", base["started_at"]),
                "completed_at": manifest.get("updated_at", now()),
            }
            append_row(row)
            return row
        except Exception as validation_exc:
            failure = {
                **base, "run_id": manifest.get("run_id", ""), "attempt_id": manifest.get("attempt_id", ""),
                "corpus_id": trace.get("corpus_id", ""), "corpus_hash": trace.get("corpus_hash", ""),
                "solver_invoked": "YES" if trace.get("solver_status") not in {None, "", "NOT_REACHED"} else "NO",
                "cif_emitted": "YES" if trace.get("CIF_generated") else "NO",
                "workflow_status": "FAILED_SOFTWARE_OR_PROVENANCE",
                "failure_stage": getattr(validation_exc, "stage", "orchestrator_validation"),
                "failure_code": getattr(validation_exc, "code", type(validation_exc).__name__),
                "failure_message": str(validation_exc), "completed_at": manifest.get("updated_at", now()),
            }
            append_row(failure)
            raise validation_exc from exc
    except Exception as exc:
        manifest, trace = latest_artifacts(output_root)
        failure = {
            **base, "run_id": manifest.get("run_id", ""), "attempt_id": manifest.get("attempt_id", ""),
            "corpus_id": trace.get("corpus_id", ""), "corpus_hash": trace.get("corpus_hash", ""),
            "solver_invoked": "YES" if trace.get("solver_status") not in {None, "", "NOT_REACHED"} else "NO",
            "cif_emitted": "YES" if trace.get("CIF_generated") else "NO",
            "workflow_status": "FAILED_SOFTWARE_OR_PROVENANCE",
            "failure_stage": trace.get("failure_stage", getattr(exc, "stage", "orchestrator_validation")),
            "failure_code": trace.get("failure_code", getattr(exc, "code", type(exc).__name__)),
            "failure_message": str(exc), "completed_at": manifest.get("updated_at", now()),
        }
        append_row(failure)
        raise
    raise RuntimeError(f"negative case unexpectedly solved: {case['case_id']}")


def write_completion_outputs(rows: list[dict[str, str]]) -> None:
    positive = [row for row in rows if row["case_type"] == "POSITIVE"]
    negatives = [row for row in rows if row["case_type"] == "NEGATIVE_ABSTENTION"]
    positive_path = RESULTS / "RESULT_4_COMPLETION_V4_2_POSITIVE.csv"
    negative_path = RESULTS / "RESULT_4_COMPLETION_V4_2_NEGATIVE.csv"
    write_csv(positive_path, positive, FIELDS)
    write_csv(negative_path, negatives, FIELDS)
    f1 = positive[0]
    summary = (
        "# Result-4 completion V4.2 summary\n\n"
        f"- F1 legitimate scientific terminal: {f1['workflow_status']}\n"
        f"- F1 independent reference recovery: {f1['reference_match']}\n"
        f"- F1 formula contract: {f1['canonical_target_formula']} -> {f1['qlip_formula']} ({f1['formula_species_contract']})\n"
        f"- F1 solver/objective parity/CIF/SCA: {f1['solver_status']}/{f1['objective_parity']}/{f1['cif_parse']}/{f1['sca_status']}\n"
        f"- Controlled negative abstentions: {sum(row['workflow_status'] == 'EXPECTED_CONTROLLED_ABSTENTION' for row in negatives)}/3\n"
        f"- Negative solver invocations/CIFs: {sum(row['solver_invoked'] == 'YES' for row in negatives)}/{sum(row['cif_emitted'] == 'YES' for row in negatives)}\n"
        "- Software/provenance failures: 0\n"
        "- A2/C2 rerun: NO\n- V3 Result-2/Result-3 rerun: NO\n"
    )
    (RESULTS / "RESULT_4_COMPLETION_V4_2_SUMMARY.md").write_text(summary, encoding="utf-8")
    audit = (
        "# Result-4 completion V4.2 audit\n\n"
        f"- Workflow commit: `{WORKFLOW_COMMIT}`\n- Freeze SHA-256: `{FREEZE_SHA256}`\n"
        f"- Positive SHA-256: `{sha256(positive_path)}`\n- Negative SHA-256: `{sha256(negative_path)}`\n"
        "- Accounted intended terminals: 4/4\n- Wrong-corpus violations: 0\n"
        "- Reference leakage violations: 0\n- Objective parity failures: 0\n"
        "- Formula/species invariant violations: 0\n- Unsupported guidance entering QLIP: 0\n"
        "- F1 is the sole independent-reference Result-4 case (N=1). A scientific mismatch is retained as a valid non-recovery.\n"
    )
    (RESULTS / "RESULT_4_COMPLETION_V4_2_AUDIT.md").write_text(audit, encoding="utf-8")
    write_json(PROVENANCE_ROOT / "EXECUTION_STATUS.json", {
        "status": "VALID_COMPLETE", "planned": 4, "attempted": 4, "valid_intended_terminals": 4,
        "software_failures": 0, "objective_parity_failures": 0, "wrong_corpus_violations": 0,
        "leakage_violations": 0, "completed_at": now(),
        "result_hashes": {"positive": sha256(positive_path), "negative": sha256(negative_path)},
    })


def write_complete_result4(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    v4_1_rows = read_csv(V4_1 / "results/EXECUTION_LEDGER.csv")
    preserved = [row for row in v4_1_rows if row["case_id"] in {"RDX-E4-A2", "RDX-E4-C2"}]
    if len(preserved) != 2 or any(row["workflow_status"] != "PASS" for row in preserved):
        raise RuntimeError("preserved A2/C2 terminals unavailable")
    combined_rows: list[dict[str, Any]] = []
    for row in preserved:
        combined_rows.append({
            "case_id": row["case_id"], "formula": row["formula"], "claim_class": row["claim_class"],
            "source_benchmark": "RESULT4_V4_1", "workflow_commit": V4_1_COMMIT,
            "freeze_hash": V4_1_FREEZE, "result_status": row["workflow_status"],
            "solver_status": row["solver_status"], "objective_parity": row["objective_parity"],
            "CIF": row["cif_emitted"], "SCA": row["sca_status"], "reference_match": row["reference_match"],
            "controlled_abstention": "NO", "software_failure": "NO",
        })
    for row in rows:
        combined_rows.append({
            "case_id": row["case_id"], "formula": row["formula"], "claim_class": row["claim_class"],
            "source_benchmark": "RESULT4_COMPLETION_V4_2", "workflow_commit": WORKFLOW_COMMIT,
            "freeze_hash": FREEZE_SHA256, "result_status": row["workflow_status"],
            "solver_status": row["solver_status"], "objective_parity": row["objective_parity"],
            "CIF": row["cif_emitted"], "SCA": row["sca_status"], "reference_match": row["reference_match"],
            "controlled_abstention": "YES" if row["workflow_status"] == "EXPECTED_CONTROLLED_ABSTENTION" else "NO",
            "software_failure": "NO",
        })
    fields = list(combined_rows[0])
    COMBINED.mkdir(parents=True, exist_ok=True)
    write_csv(COMBINED / "RESULT_4_COMBINED.csv", combined_rows, fields)
    f1 = next(row for row in combined_rows if row["case_id"] == "RDX-E4-F1")
    text = (
        "# Complete Result 4\n\n"
        "A2 and C2 are prospective V4.1 target-derived demonstrations. F1 and the three negatives are the prospective V4.2 completion after the isolated formula-adapter repair. No completed case was rerun after observing its outcome.\n\n"
        f"- Six cases accounted: YES\n- Independent-reference cases/recoveries: 1/{int(f1['reference_match'] == 'YES')}\n"
        "- Target-derived demonstrations/completed: 2/2\n- Controlled negative cases/successful abstentions: 3/3\n"
        "- Unexpected software failures: 0\n"
    )
    (COMBINED / "RESULT_4_COMBINED_SUMMARY.md").write_text(text, encoding="utf-8")
    return combined_rows


def write_paper_outputs(combined_rows: list[dict[str, Any]], completion_rows: list[dict[str, str]]) -> None:
    result1_csv = V3 / "results/result_1_traceability/EXECUTION_FUNNEL.csv"
    result1_md = V3 / "results/result_1_traceability/EXECUTION_FUNNEL.md"
    result2 = V3 / "results/result_2_heldout/RESULT_2_HELDOUT_RECOVERY.csv"
    result3 = V3 / "results/result_3_factorial/RESULT_3_FACTORIAL.csv"
    informative = {
        row["formula"] for row in read_csv(V3 / "RESULT_3_INFORMATIVENESS.csv")
        if row["included_in_causal_request_spp_denominator"] == "YES"
    }
    r3_rows = read_csv(result3)
    by_key = {(row["formula"], row["condition_id"]): row for row in r3_rows}
    changed = sum(
        by_key[(formula, "LOOSE_REGULATOR_ONLY")]["selected_state"]
        != by_key[(formula, "LOOSE_REGULATOR_PLUS_REQUEST")]["selected_state"]
        for formula in informative
    )
    if len(informative) != 5 or changed != 0:
        raise RuntimeError("preserved Result-3 0/5 finding changed")
    f1 = next(row for row in combined_rows if row["case_id"] == "RDX-E4-F1")
    recoveries = int(f1["reference_match"] == "YES")
    v3_freeze_hash = sha256(V3 / "BENCHMARK_V3_FREEZE.json")
    index = (
        "# Combined paper evidence provenance index\n\n"
        "The evidence blocks retain distinct workflow and freeze provenance.\n\n"
        "## Result 1 — historical frozen audit\n\n"
        f"- Funnel CSV SHA-256: `{sha256(result1_csv)}`\n- Funnel MD SHA-256: `{sha256(result1_md)}`\n\n"
        "## Result 2 — preserved prospective V3\n\n"
        f"- Workflow commit: `698d82a37d94b1b64a6f2488a2e3b205dbf0f989`\n- V3 freeze: `{v3_freeze_hash}`\n- Result: `{sha256(result2)}`\n\n"
        "## Result 3 — preserved prospective V3\n\n"
        f"- Workflow commit: `698d82a37d94b1b64a6f2488a2e3b205dbf0f989`\n- V3 freeze: `{v3_freeze_hash}`\n- Result: `{sha256(result3)}`\n"
        "- Finding: five informative targets; loose selected state changed 0/5 (improved 0, worsened 0, unchanged 5).\n\n"
        "## Result 4 — combined prospective evidence\n\n"
        f"- A2/C2: V4.1 commit `{V4_1_COMMIT}`, freeze `{V4_1_FREEZE}`.\n"
        f"- F1/negatives: V4.2 commit `{WORKFLOW_COMMIT}`, freeze `{FREEZE_SHA256}`.\n"
        f"- Independent-reference recovery: {recoveries}/1.\n"
        "- No completed outcome was rerun after observation.\n"
    )
    (COMBINED / "PROVENANCE_INDEX.md").write_text(index, encoding="utf-8")
    table = [
        {"result": "Result 1", "provenance": "historical frozen audit", "planned": "NOT_APPLICABLE", "valid_terminals": "NOT_APPLICABLE", "finding": "Traceability funnel available", "claim_boundary": "Historical audit"},
        {"result": "Result 2", "provenance": "preserved prospective V3", "planned": 7, "valid_terminals": 7, "finding": "Frozen held-out result preserved", "claim_boundary": "Seven V3 held-out cases"},
        {"result": "Result 3", "provenance": "preserved prospective V3", "planned": 28, "valid_terminals": 28, "finding": "5 informative; changed 0/5, improved 0, worsened 0, unchanged 5", "claim_boundary": "Factorial selected-state comparison"},
        {"result": "Result 4", "provenance": "combined prospective V4.1 + V4.2", "planned": 6, "valid_terminals": 6, "finding": f"2 target-derived demonstrations, 1 independent case ({recoveries} recovery), 3 controlled abstentions", "claim_boundary": "Independent recovery N=1"},
    ]
    write_csv(COMBINED / "PAPER_RESULTS_TABLE.csv", table, list(table[0]))
    lines = ["# Paper results table", "", "| Result | Provenance | Planned | Valid terminals | Finding | Claim boundary |", "|---|---|---:|---:|---|---|"]
    lines.extend(f"| {r['result']} | {r['provenance']} | {r['planned']} | {r['valid_terminals']} | {r['finding']} | {r['claim_boundary']} |" for r in table)
    (COMBINED / "PAPER_RESULTS_TABLE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (COMBINED / "PAPER_RESULTS_SUMMARY_TEXT.md").write_text(
        "# Paper results summary text\n\n"
        "Result 1 is a historical frozen traceability audit. Results 2 and 3 are preserved prospective V3 evidence and were not rerun. Result 3 found that request-specific SPP changed loose selected state in 0/5 informative cases (improved 0, worsened 0, unchanged 5).\n\n"
        f"Result 4 combines two prospective V4.1 target-derived demonstrations with the V4.2 completion. The sole independent-reference case recovered the held-out structure in {recoveries}/1 case; all three negatives reached their frozen controlled abstention. No completed outcome was rerun.\n",
        encoding="utf-8",
    )
    (COMBINED / "PAPER_CLAIM_AUDIT.md").write_text(
        "# Paper claim audit\n\n"
        "- Result 1 is historical audit evidence.\n- Results 2 and 3 are preserved prospective V3 evidence.\n"
        "- Result 3 supports no request-SPP improvement claim: changed 0/5, improved 0, worsened 0, unchanged 5.\n"
        "- A2/C2 are target-derived demonstrations, not independent predictions.\n"
        "- F1 is the only independent-reference Result-4 case, so the recovery claim is N=1.\n"
        "- Controlled abstentions are intended negative terminals, not crystal predictions.\n",
        encoding="utf-8",
    )
    (COMBINED / "FINAL_BENCHMARK_PROVENANCE_AUDIT.md").write_text(
        "# Final benchmark provenance audit\n\n"
        f"- Result-2 preserved SHA-256: `{sha256(result2)}`\n- Result-3 preserved SHA-256: `{sha256(result3)}`\n"
        f"- Result-4 combined SHA-256: `{sha256(COMBINED / 'RESULT_4_COMBINED.csv')}`\n"
        f"- V4.2 ledger SHA-256: `{sha256(LEDGER)}`\n"
        "- Completed outcomes rerun: NO\n- Objective parity failures: 0\n"
        "- Wrong-corpus violations: 0\n- Leakage violations: 0\n- Unexpected software failures: 0\n"
        "- Result-4 provenance remains split explicitly between V4.1 and V4.2.\n",
        encoding="utf-8",
    )


def main() -> None:
    verify_freeze()
    prepare_results()
    cases = read_csv(FREEZE / "RESULT4_COMPLETION_V4_2_CASES.csv")
    if [case["case_id"] for case in cases] != ["RDX-E4-F1", "RDX-NEG-E4-A1", "RDX-NEG-E4-A3", "RDX-NEG-E4-A4"]:
        raise RuntimeError("frozen case order changed")
    completed = {
        row["case_id"] for row in read_csv(LEDGER)
        if row["workflow_status"] in {"PASS", "EXPECTED_CONTROLLED_ABSTENTION"}
    }
    sequence = len(read_csv(LEDGER))
    f1_case = cases[0]
    if f1_case["case_id"] not in completed:
        sequence += 1
        f1 = run_f1(sequence, f1_case, reference())
        print(f"[{sequence}/4] RDX-E4-F1 scientific terminal: reference_match={f1['reference_match']}", flush=True)
    for case in cases[1:]:
        if case["case_id"] in completed:
            continue
        sequence += 1
        run_negative(sequence, case)
        print(f"[{sequence}/4] {case['case_id']} EXPECTED_CONTROLLED_ABSTENTION", flush=True)
    rows = read_csv(LEDGER)
    valid = sum(row["workflow_status"] in {"PASS", "EXPECTED_CONTROLLED_ABSTENTION"} for row in rows)
    if len(rows) != 4 or valid != 4:
        raise RuntimeError(f"V4.2 accounting mismatch: rows={len(rows)}, valid={valid}")
    verify_freeze()
    write_completion_outputs(rows)
    combined = write_complete_result4(rows)
    write_paper_outputs(combined, rows)
    print("PASS: Result-4 V4.2 completion has 4/4 legitimate intended terminals", flush=True)


if __name__ == "__main__":
    main()
