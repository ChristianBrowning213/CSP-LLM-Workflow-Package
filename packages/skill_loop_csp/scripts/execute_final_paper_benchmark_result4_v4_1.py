"""Execute the frozen six-case Result-4-only V4.1 benchmark."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.bench.prospective import (
    FrozenReference,
    ProspectiveBenchmarkStages,
    canonical_structure_sha256,
)
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
    _qlip_ordered_orbits_adapter,
    run_csp_workflow,
)


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "artifacts/final_paper_benchmark_result4_v4_1"
RESULTS = FREEZE / "results"
POSITIVE_ROOT = RESULTS / "positive"
NEGATIVE_ROOT = RESULTS / "negative"
SUMMARY_ROOT = RESULTS / "summary"
PROVENANCE_ROOT = RESULTS / "provenance"
COMBINED = ROOT / "artifacts/final_paper_combined_results"
V3 = ROOT / "artifacts/final_paper_benchmark_v3"
LEDGER = RESULTS / "EXECUTION_LEDGER.csv"
WORKFLOW_COMMIT = "31feff023515b2ac32165fe95fb803412e21a5bc"
FREEZE_SHA256 = "03d8c09bcb0986aad4628211d2e9b1c17a929ac86f58fd832c366fd865f9b3a0"
CORPUS_ID = "nasicon_specialist_v3"
CORPUS_SHA256 = "4392933d241c4f6397af9328fd2d43bd187f053da824887e0e34a43bd09d1ea4"
REGULATOR_ID = "icsd_broad_regulator_v1"
REGULATOR_SHA256 = "be0a8f620fca62aa3bb755d76ac9edeeb8aa1ac507c4800001e4018b94c6cf0c"
EXPECTED_HASHES = {
    "RESULT4_V4_1_CASES.csv": "54cd5265822784cc67f61bce02f9be749dc538c7a833d46a6eaffc1b0db2be3d",
    "RESULT4_V4_1_REFERENCES.csv": "f1c40a613c44f4fbf03c78cac8ed344340af4ed7108678f42505070daf4116c0",
    "RESULT4_V4_1_CONFIG.json": "4ea2e91fc9520928471deac034a52973a55aa95f1738872ad39198cf480320d8",
    "RESULT4_V4_1_FREEZE.json": FREEZE_SHA256,
}
PROTECTED_V3 = {
    "results/result_2_heldout/RESULT_2_HELDOUT_RECOVERY.csv": "ee539ad8de148afc029b5494455d15a79b33cb362df3473e129d2c4557cfe0a0",
    "results/result_3_factorial/RESULT_3_FACTORIAL.csv": "5688029447547363fe7fd62fcee6da5f0e4d378afab8f54499be5a5251925c3e",
    "results/EXECUTION_LEDGER.csv": "20919d60edbd3a15131448259c39e1141a50d6d7437eb510aba70a1d9277ac01",
}
FIELDS = [
    "sequence_number", "case_id", "formula", "case_type", "claim_class", "request",
    "run_id", "attempt_id", "workflow_commit", "freeze_hash", "corpus_id", "corpus_hash",
    "retrieved_count", "retrieved_ids", "retrieved_ids_hash", "evidence_ids_hash",
    "reference_ID_exclusions", "raw_duplicate_exclusions", "canonical_duplicate_exclusions",
    "StructureMatcher_exclusions", "reference_equivalent_evidence_count",
    "required_pairs", "required_pair_count", "request_usable_pairs", "fallback_pairs",
    "unsupported_pairs", "request_spp_run_id", "request_spp_hash", "regulator_id",
    "regulator_hash", "scaffold_id", "ordered_orbit_count", "orbit_membership_hash",
    "solver_invoked", "solver_status", "solver_objective", "independent_objective",
    "objective_difference", "objective_parity", "cif_emitted", "cif_path", "cif_hash",
    "cif_parse", "exact_composition", "sca_status", "reference_id", "reference_cif_hash",
    "reference_match", "generated_space_group", "reference_space_group",
    "exact_space_group_agreement", "generated_crystal_system", "reference_crystal_system",
    "crystal_system_agreement", "generated_volume_per_atom_A3", "reference_volume_per_atom_A3",
    "absolute_volume_error_percent", "representability_status", "workflow_status",
    "failure_stage", "failure_code", "failure_message", "started_at", "completed_at",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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


def verify_freeze() -> None:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != WORKFLOW_COMMIT:
        raise RuntimeError(f"workflow commit mismatch: {head}")
    for name, expected in EXPECTED_HASHES.items():
        actual = sha256(FREEZE / name)
        if actual != expected:
            raise RuntimeError(f"freeze hash mismatch: {name}: {actual}")
    with (FREEZE / "OUTPUT_HASH_MANIFEST.csv").open("r", encoding="utf-8", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    if len(manifest) != 5 or any(sha256(FREEZE / row["path"]) != row["sha256"] for row in manifest):
        raise RuntimeError("V4.1 hash manifest mismatch")
    adapter = ROOT / "src/sok_llm_orchestrator/bench/prospective.py"
    committed = subprocess.check_output(
        ["git", "show", f"{WORKFLOW_COMMIT}:src/sok_llm_orchestrator/bench/prospective.py"], cwd=ROOT
    )
    if sha256(adapter) != hashlib.sha256(committed).hexdigest():
        raise RuntimeError("prospective adapter differs from committed file")
    tracked_diff = subprocess.check_output(
        ["git", "diff", "--name-only", WORKFLOW_COMMIT, "--", "src"], cwd=ROOT, text=True
    ).strip()
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src"], cwd=ROOT, text=True
    ).strip()
    if tracked_diff or untracked:
        raise RuntimeError(f"scientific source diff: tracked={tracked_diff!r}, untracked={untracked!r}")
    for relative, expected in PROTECTED_V3.items():
        if sha256(V3 / relative) != expected:
            raise RuntimeError(f"protected V3 hash mismatch: {relative}")


def prepare_results() -> None:
    for path in (RESULTS, POSITIVE_ROOT, NEGATIVE_ROOT, SUMMARY_ROOT, PROVENANCE_ROOT):
        path.mkdir(parents=True, exist_ok=True)
    if not LEDGER.exists():
        write_csv(LEDGER, [], FIELDS)
    write_json(PROVENANCE_ROOT / "LAUNCH_FREEZE_VERIFICATION.json", {
        "verified_at": now(), "workflow_commit": WORKFLOW_COMMIT,
        "freeze_sha256": FREEZE_SHA256, "manifest": "5/5 PASS",
        "prospective_adapter_tracked": True, "scientific_source_diff": [],
        "protected_v3_hashes": PROTECTED_V3, "benchmark_solves_before_freeze": 0,
    })


def latest_artifacts(output_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifests = sorted(output_root.glob("attempts/*/attempt_manifest.json"), key=lambda p: p.stat().st_mtime_ns)
    if not manifests:
        return {}, {}
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    trace_path = manifests[-1].parent / "workflow_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8")) if trace_path.is_file() else {}
    return manifest, trace


def append_row(row: dict[str, Any]) -> None:
    rows = read_csv(LEDGER)
    if any(item["case_id"] == row["case_id"] and item["workflow_status"] in {"PASS", "EXPECTED_CONTROLLED_ABSTENTION"} for item in rows):
        raise RuntimeError(f"refusing to overwrite completed terminal: {row['case_id']}")
    rows.append({field: row.get(field, "") for field in FIELDS})
    write_csv(LEDGER, rows, FIELDS)


def reference_map() -> dict[str, tuple[FrozenReference, str]]:
    result: dict[str, tuple[FrozenReference, str]] = {}
    for row in read_csv(FREEZE / "RESULT4_V4_1_REFERENCES.csv"):
        path = ROOT / row["reference_cif_path"]
        reference = FrozenReference.from_cif(
            case_id=row["case_id"], formula=row["formula"], reference_id=row["reference_id"],
            source_structure_id=row["reference_id"], cif_path=path,
        )
        if reference.raw_sha256 != row["reference_cif_sha256"] or reference.canonical_sha256 != row["reference_canonical_sha256"]:
            raise RuntimeError(f"wrong frozen reference: {row['case_id']}")
        result[row["case_id"]] = (reference, row["classification"])
    return result


def request_for(task: dict[str, Any], case_id: str) -> str:
    prefix = f"{case_id}: " if case_id.startswith("RDX-NEG") else ""
    return f"{prefix}Generate {task['formula']} as a {task['family']} crystal with requested {task['space_group']} symmetry."


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


def orbit_metrics(stages: ProspectiveBenchmarkStages, task: dict[str, Any], config: WorkflowConfig, expected_scaffold: str) -> dict[str, Any]:
    scaffold_id, _, internal = stages._scaffold(task, config)
    if scaffold_id != expected_scaffold:
        raise RuntimeError(f"wrong scaffold: {scaffold_id} != {expected_scaffold}")
    wire = _qlip_ordered_orbits_adapter(internal)
    membership = [{"orbit_id": row["orbit_id"], "site_indices": row["site_indices"]} for row in wire]
    return {"ordered_orbit_count": len(wire), "orbit_membership_hash": json_hash(membership)}


def reference_metrics(cif_path: Path, reference: FrozenReference, formula: str) -> dict[str, Any]:
    generated = Structure.from_file(cif_path)
    heldout = Structure.from_file(reference.cif_path)
    generated_sga = SpacegroupAnalyzer(generated, symprec=1e-2, angle_tolerance=5)
    reference_sga = SpacegroupAnalyzer(heldout, symprec=1e-2, angle_tolerance=5)
    generated_sg, reference_sg = generated_sga.get_space_group_symbol(), reference_sga.get_space_group_symbol()
    generated_system, reference_system = generated_sga.get_crystal_system(), reference_sga.get_crystal_system()
    generated_vpa, reference_vpa = generated.volume / len(generated), heldout.volume / len(heldout)
    return {
        "cif_parse": "YES", "exact_composition": "YES" if generated.composition.reduced_composition == Composition(formula).reduced_composition else "NO",
        "reference_match": "YES" if StructureMatcher().fit(generated, heldout) else "NO",
        "generated_space_group": generated_sg, "reference_space_group": reference_sg,
        "exact_space_group_agreement": "YES" if generated_sg == reference_sg else "NO",
        "generated_crystal_system": generated_system, "reference_crystal_system": reference_system,
        "crystal_system_agreement": "YES" if generated_system == reference_system else "NO",
        "generated_volume_per_atom_A3": generated_vpa, "reference_volume_per_atom_A3": reference_vpa,
        "absolute_volume_error_percent": 100.0 * abs(generated_vpa - reference_vpa) / reference_vpa,
    }


def base_row(sequence: int, case: dict[str, str], request: str) -> dict[str, Any]:
    return {
        "sequence_number": sequence, "case_id": case["case_id"], "formula": case["formula"],
        "case_type": case["case_type"], "claim_class": case["classification"], "request": request,
        "workflow_commit": WORKFLOW_COMMIT, "freeze_hash": FREEZE_SHA256, "started_at": now(),
        "workflow_status": "STARTED",
    }


def run_positive(sequence: int, case: dict[str, str], reference: FrozenReference, classification: str) -> dict[str, Any]:
    stages = ProspectiveBenchmarkStages(tasks=ProductionWorkflowStages._TASKS, reference=reference)
    task = stages.normalise(case["formula"])
    if task["prototype"] != case["prototype"] or task["space_group"] != case["space_group"]:
        raise RuntimeError(f"frozen task mapping mismatch: {case['case_id']}")
    request = request_for(task, case["case_id"])
    base = base_row(sequence, case, request)
    output_root = POSITIVE_ROOT / case["case_id"] / "POSITIVE_CANONICAL"
    config = WorkflowConfig(
        output_root=output_root, retrieval_depth=40, retrieval_demo_export=True,
        excluded_structure_ids=(reference.reference_id, reference.source_structure_id),
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
            raise RuntimeError("unsupported guidance silently entered solver")
        if result.request_supported_pair_count != int(case["guidance_usable_pairs"]) or result.regulator_fallback_pair_count != int(case["guidance_fallback_pairs"]):
            raise RuntimeError("request-SPP support counts differ from freeze")
        if result.objective_difference >= 1e-6:
            raise RuntimeError(f"objective parity failure: {result.objective_difference}")
        if result.request_spp_run_id != result.run_id or not manifest.get("request_spp_hash"):
            raise RuntimeError("fresh request-SPP provenance mismatch")
        if result.run_id != manifest.get("run_id") or result.attempt_id != manifest.get("attempt_id"):
            raise RuntimeError("corrupt run/attempt provenance")
        exclusions = exclusion_metrics(stages, result.spp_evidence_ids)
        orbits = orbit_metrics(stages, result.normalised_task, config, case["prototype"])
        cif_path = Path(result.generated_cif_path)
        metrics = reference_metrics(cif_path, reference, case["formula"])
        required_pairs = list(trace.get("required_pairs", []))
        row = {
            **base, **exclusions, **orbits, **metrics,
            "run_id": result.run_id, "attempt_id": result.attempt_id,
            "corpus_id": result.corpus_id, "corpus_hash": result.corpus_hash,
            "retrieved_count": len(result.retrieved_ids), "retrieved_ids": ";".join(result.retrieved_ids),
            "retrieved_ids_hash": json_hash(list(result.retrieved_ids)), "evidence_ids_hash": json_hash(list(result.spp_evidence_ids)),
            "required_pairs": ";".join(required_pairs), "required_pair_count": len(required_pairs),
            "request_usable_pairs": result.request_supported_pair_count,
            "fallback_pairs": result.regulator_fallback_pair_count, "unsupported_pairs": result.unsupported_pair_count,
            "request_spp_run_id": result.request_spp_run_id, "request_spp_hash": manifest["request_spp_hash"],
            "regulator_id": REGULATOR_ID, "regulator_hash": result.regulator_spp_hash,
            "scaffold_id": result.scaffold_id, "solver_invoked": "YES", "solver_status": result.solver_status,
            "solver_objective": result.solver_objective, "independent_objective": result.independent_objective,
            "objective_difference": result.objective_difference, "objective_parity": "PASS",
            "cif_emitted": "YES", "cif_path": str(cif_path), "cif_hash": result.generated_cif_hash,
            "sca_status": "PASS" if result.sca_result.get("parse_ok") else str(result.sca_result.get("status", "PARTIAL")),
            "reference_id": reference.reference_id, "reference_cif_hash": reference.raw_sha256,
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
            "solver_status": trace.get("solver_status", ""), "cif_emitted": "YES" if trace.get("CIF_generated") else "NO",
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
    config = WorkflowConfig(output_root=output_root, scaffold_mode="loose", request_spp_mode="enabled", stages=stages)
    expected_stage, expected_code = case["expected_terminal"].split("/", 1)
    try:
        run_csp_workflow(request, config)
    except WorkflowStageError as exc:
        verify_freeze()
        manifest, trace = latest_artifacts(output_root)
        if exc.stage != expected_stage or exc.code != expected_code:
            raise RuntimeError(f"wrong controlled terminal: {exc.stage}/{exc.code}") from exc
        if trace.get("corpus_id") != CORPUS_ID or trace.get("corpus_hash") != CORPUS_SHA256:
            raise RuntimeError("wrong corpus in negative terminal")
        if trace.get("solver_status") != "NOT_REACHED" or trace.get("CIF_generated"):
            raise RuntimeError("negative unexpectedly invoked solver or emitted CIF")
        if manifest.get("status") != "FAILED_CONTROLLED" or trace.get("execution_attempt_status") != "FAILED_CONTROLLED":
            raise RuntimeError("corrupt controlled-terminal provenance")
        row = {
            **base, "run_id": manifest.get("run_id"), "attempt_id": manifest.get("attempt_id"),
            "corpus_id": trace["corpus_id"], "corpus_hash": trace["corpus_hash"],
            "retrieved_count": trace.get("retrieval_count", 0), "retrieved_ids": ";".join(trace.get("retrieved_ids", [])),
            "retrieved_ids_hash": json_hash(trace.get("retrieved_ids", [])),
            "solver_invoked": "NO", "solver_status": "NOT_REACHED", "cif_emitted": "NO",
            "sca_status": "NOT_REACHED", "representability_status": "EXPECTED_ABSTENTION",
            "workflow_status": "EXPECTED_CONTROLLED_ABSTENTION", "failure_stage": exc.stage,
            "failure_code": exc.code, "failure_message": str(exc),
            "started_at": manifest.get("started_at", base["started_at"]), "completed_at": manifest.get("updated_at", now()),
        }
        append_row(row)
        return row
    except Exception as exc:
        manifest, trace = latest_artifacts(output_root)
        row = {
            **base, "run_id": manifest.get("run_id", ""), "attempt_id": manifest.get("attempt_id", ""),
            "corpus_id": trace.get("corpus_id", ""), "corpus_hash": trace.get("corpus_hash", ""),
            "solver_invoked": "YES" if trace.get("solver_status") not in {None, "", "NOT_REACHED"} else "NO",
            "cif_emitted": "YES" if trace.get("CIF_generated") else "NO",
            "workflow_status": "FAILED_SOFTWARE_OR_PROVENANCE",
            "failure_stage": trace.get("failure_stage", getattr(exc, "stage", "orchestrator_validation")),
            "failure_code": trace.get("failure_code", getattr(exc, "code", type(exc).__name__)),
            "failure_message": str(exc), "completed_at": manifest.get("updated_at", now()),
        }
        append_row(row)
        raise
    raise RuntimeError(f"negative case unexpectedly solved: {case['case_id']}")


def write_result_outputs(rows: list[dict[str, str]]) -> None:
    positive = [row for row in rows if row["case_type"] == "POSITIVE"]
    negative = [row for row in rows if row["case_type"] == "NEGATIVE_ABSTENTION"]
    write_csv(RESULTS / "RESULT_4_V4_1_POSITIVE.csv", positive, FIELDS)
    write_csv(RESULTS / "RESULT_4_V4_1_NEGATIVE.csv", negative, FIELDS)
    independent = [row for row in positive if row["claim_class"] == "INDEPENDENT_REFERENCE_RECOVERY"]
    target = [row for row in positive if row["claim_class"] == "TARGET_DERIVED_DEMONSTRATION"]
    recoveries = sum(row["reference_match"] == "YES" for row in independent)
    summary = (
        "# Result-4 V4.1 summary\n\n"
        f"- Positive planned/attempted/completed: 3/3/{sum(row['workflow_status'] == 'PASS' for row in positive)}\n"
        f"- Specialist routing correct: {sum(row['corpus_id'] == CORPUS_ID for row in positive)}/3\n"
        f"- OPTIMAL: {sum(row['solver_status'] == 'OPTIMAL' for row in positive)}/3\n"
        f"- Objective parity PASS: {sum(row['objective_parity'] == 'PASS' for row in positive)}/3\n"
        f"- Valid CIF: {sum(row['cif_parse'] == 'YES' for row in positive)}/3\n"
        f"- SCA completed: {sum(bool(row['sca_status']) and row['sca_status'] != 'NOT_REACHED' for row in positive)}/3\n"
        f"- Independent-reference cases/recoveries: 1/{recoveries}\n"
        f"- Target-derived demonstrations/completed: 2/{sum(row['workflow_status'] == 'PASS' for row in target)}\n"
        f"- Negative planned/attempted/controlled abstentions: 3/3/{sum(row['workflow_status'] == 'EXPECTED_CONTROLLED_ABSTENTION' for row in negative)}\n"
        f"- Unexpected negative solver invocations: {sum(row['solver_invoked'] == 'YES' for row in negative)}\n"
        f"- Negative CIFs emitted: {sum(row['cif_emitted'] == 'YES' for row in negative)}\n"
        "- Software/provenance failures: 0\n"
    )
    (RESULTS / "RESULT_4_V4_1_SUMMARY.md").write_text(summary, encoding="utf-8")
    hashes = {
        "positive_sha256": sha256(RESULTS / "RESULT_4_V4_1_POSITIVE.csv"),
        "negative_sha256": sha256(RESULTS / "RESULT_4_V4_1_NEGATIVE.csv"),
    }
    audit = (
        "# Result-4 V4.1 audit\n\n"
        f"- Workflow commit: `{WORKFLOW_COMMIT}`\n- Freeze SHA-256: `{FREEZE_SHA256}`\n"
        f"- Positive result SHA-256: `{hashes['positive_sha256']}`\n"
        f"- Negative result SHA-256: `{hashes['negative_sha256']}`\n"
        "- Accounted intended terminals: 6/6\n- Objective parity failures: 0\n"
        "- Wrong-corpus violations: 0\n- Reference leakage violations: 0\n"
        "- Result-2/3 rerun: NO\n\n"
        "Only RDX-E4-F1 is classified as independent-reference recovery. RDX-E4-A2 and RDX-E4-C2 are target-derived demonstrations and are not counted as independent predictions.\n"
    )
    (RESULTS / "RESULT_4_V4_1_AUDIT.md").write_text(audit, encoding="utf-8")
    write_json(PROVENANCE_ROOT / "EXECUTION_STATUS.json", {
        "status": "VALID_COMPLETE", "planned": 6, "attempted": 6, "valid_intended_terminals": 6,
        "software_failures": 0, "objective_parity_failures": 0, "wrong_corpus_violations": 0,
        "leakage_violations": 0, "result_hashes": hashes, "completed_at": now(),
    })


def write_combined_outputs(rows: list[dict[str, str]]) -> None:
    COMBINED.mkdir(parents=True, exist_ok=True)
    result1_csv = V3 / "results/result_1_traceability/EXECUTION_FUNNEL.csv"
    result1_md = V3 / "results/result_1_traceability/EXECUTION_FUNNEL.md"
    result2 = V3 / "results/result_2_heldout/RESULT_2_HELDOUT_RECOVERY.csv"
    result3 = V3 / "results/result_3_factorial/RESULT_3_FACTORIAL.csv"
    result4p = RESULTS / "RESULT_4_V4_1_POSITIVE.csv"
    result4n = RESULTS / "RESULT_4_V4_1_NEGATIVE.csv"
    r3_rows = read_csv(result3)
    informative = {
        row["formula"] for row in read_csv(V3 / "RESULT_3_INFORMATIVENESS.csv")
        if row["included_in_causal_request_spp_denominator"] == "YES"
    }
    if len(informative) != 5:
        raise RuntimeError("preserved Result-3 informative denominator changed")
    by_key = {(row["formula"], row["condition_id"]): row for row in r3_rows}
    changed = sum(
        by_key[(formula, "LOOSE_REGULATOR_ONLY")]["selected_state"] != by_key[(formula, "LOOSE_REGULATOR_PLUS_REQUEST")]["selected_state"]
        for formula in informative
    )
    if changed != 0:
        raise RuntimeError("preserved Result-3 selected-state finding changed")
    v3_freeze_hash = sha256(V3 / "BENCHMARK_V3_FREEZE.json")
    execution_date = max(row["completed_at"] for row in rows)
    index = (
        "# Combined paper evidence provenance index\n\n"
        "The four evidence blocks are intentionally distinct and were not produced under one workflow commit.\n\n"
        "## Result 1 — historical frozen audit\n\n"
        f"- Execution funnel CSV SHA-256: `{sha256(result1_csv)}`\n- Execution funnel MD SHA-256: `{sha256(result1_md)}`\n"
        "- Claim boundary: historical traceability/audit only.\n\n"
        "## Result 2 — prospective V3\n\n"
        f"- Workflow commit: `698d82a37d94b1b64a6f2488a2e3b205dbf0f989`\n- V3 freeze SHA-256: `{v3_freeze_hash}`\n"
        f"- Result SHA-256: `{sha256(result2)}`\n- Status: completed before the first V3 software failure.\n"
        "- Claim boundary: seven frozen prospective held-out cases.\n\n"
        "## Result 3 — prospective V3\n\n"
        f"- Workflow commit: `698d82a37d94b1b64a6f2488a2e3b205dbf0f989`\n- V3 freeze SHA-256: `{v3_freeze_hash}`\n"
        f"- Result SHA-256: `{sha256(result3)}`\n- Status: completed before the first V3 software failure.\n"
        "- Claim boundary: frozen factorial comparison; five informative targets, with selected state changed in 0/5 loose-arm comparisons.\n\n"
        "Results 2 and 3 were not rerun because their prospective outcomes had already been observed before the V3 halt.\n\n"
        "## Result 4 — prospective Result-4-only V4.1\n\n"
        f"- Workflow commit: `{WORKFLOW_COMMIT}`\n- Freeze SHA-256: `{FREEZE_SHA256}`\n"
        f"- Positive result SHA-256: `{sha256(result4p)}`\n- Negative result SHA-256: `{sha256(result4n)}`\n"
        f"- Execution completion: `{execution_date}`\n"
        "- Reason for new commit: isolated ordered-orbit strict-serialization repair plus provenance capture of the already-used prospective exclusion adapter.\n"
        "- Claim boundary: only RDX-E4-F1 is an independent-reference case; A2/C2 are target-derived demonstrations; negatives are controlled representability outcomes.\n"
    )
    (COMBINED / "PROVENANCE_INDEX.md").write_text(index, encoding="utf-8")
    positive = [row for row in rows if row["case_type"] == "POSITIVE"]
    negative = [row for row in rows if row["case_type"] == "NEGATIVE_ABSTENTION"]
    recoveries = sum(row["claim_class"] == "INDEPENDENT_REFERENCE_RECOVERY" and row["reference_match"] == "YES" for row in positive)
    table = [
        {"result": "Result 1", "provenance": "historical frozen audit", "workflow_commit": "historical", "planned": "NOT_APPLICABLE", "valid_terminals": "NOT_APPLICABLE", "finding": "Traceability funnel available", "claim_boundary": "Historical audit"},
        {"result": "Result 2", "provenance": "prospective V3 before halt", "workflow_commit": "698d82a37d94b1b64a6f2488a2e3b205dbf0f989", "planned": 7, "valid_terminals": 7, "finding": "Frozen held-out recovery result preserved", "claim_boundary": "Seven V3 held-out cases"},
        {"result": "Result 3", "provenance": "prospective V3 before halt", "workflow_commit": "698d82a37d94b1b64a6f2488a2e3b205dbf0f989", "planned": 28, "valid_terminals": 28, "finding": "5 informative targets; request SPP changed selected state 0/5; improved 0; worsened 0; unchanged 5", "claim_boundary": "Factorial selected-state comparison"},
        {"result": "Result 4", "provenance": "prospective Result-4-only V4.1", "workflow_commit": WORKFLOW_COMMIT, "planned": 6, "valid_terminals": 6, "finding": f"3 positive completions, 3 controlled abstentions, independent recoveries {recoveries}/1", "claim_boundary": "One independent case; two target-derived demonstrations; three controlled negatives"},
    ]
    fields = list(table[0])
    write_csv(COMBINED / "PAPER_RESULTS_TABLE.csv", table, fields)
    lines = ["# Paper results table", "", "| Result | Provenance | Planned | Valid terminals | Finding | Claim boundary |", "|---|---|---:|---:|---|---|"]
    lines.extend(f"| {r['result']} | {r['provenance']} | {r['planned']} | {r['valid_terminals']} | {r['finding']} | {r['claim_boundary']} |" for r in table)
    (COMBINED / "PAPER_RESULTS_TABLE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (COMBINED / "PAPER_RESULTS_SUMMARY_TEXT.md").write_text(
        "# Paper results summary text\n\n"
        "Result 1 is a historical frozen traceability audit. Results 2 and 3 completed prospectively under V3 before its first software failure and were preserved without rerun. Result 4 completed prospectively under the Result-4-only V4.1 freeze after the isolated NASICON ordered-orbit serialization compatibility repair.\n\n"
        "For Result 3, five targets were informative for the LOOSE_REGULATOR_ONLY versus LOOSE_REGULATOR_PLUS_REQUEST comparison. Request-specific SPP changed the selected state in 0/5 cases: improved 0, worsened 0, unchanged 5. This does not show that request-specific SPP improved CSP selection.\n\n"
        f"For Result 4, the independent-reference recovery count was {recoveries}/1. The two target-derived positives demonstrate workflow execution only and are not independent predictions. All three negative cases are evaluated as controlled representability outcomes.\n",
        encoding="utf-8",
    )
    (COMBINED / "PAPER_CLAIM_AUDIT.md").write_text(
        "# Paper claim audit\n\n"
        "- Result 1 is historical audit evidence, not prospective generation.\n"
        "- Results 2 and 3 are prospective V3 evidence preserved without rerun.\n"
        "- Result 3 supports no claim that request-specific SPP improved selection: changed 0/5, improved 0, worsened 0, unchanged 5.\n"
        "- Result 4 uses a distinct V4.1 workflow commit. Only RDX-E4-F1 may support independent NASICON recovery.\n"
        "- RDX-E4-A2 and RDX-E4-C2 are target-derived demonstrations and cannot be counted as independent prediction successes.\n"
        "- Controlled negative abstentions are valid intended terminals, not successful crystal predictions.\n",
        encoding="utf-8",
    )
    (COMBINED / "FINAL_BENCHMARK_PROVENANCE_AUDIT.md").write_text(
        "# Final benchmark provenance audit\n\n"
        f"- Result-4 V4.1 workflow commit: `{WORKFLOW_COMMIT}`\n- Result-4 V4.1 freeze: `{FREEZE_SHA256}`\n"
        f"- Result-2 preserved SHA-256: `{sha256(result2)}`\n- Result-3 preserved SHA-256: `{sha256(result3)}`\n"
        f"- Result-4 positive SHA-256: `{sha256(result4p)}`\n- Result-4 negative SHA-256: `{sha256(result4n)}`\n"
        "- Result-2/3 rerun: NO\n- Wrong-corpus violations: 0\n- Leakage violations: 0\n- Objective parity failures: 0\n"
        "- The evidence blocks retain distinct workflow/freeze provenance and are not represented as one homogeneous campaign.\n",
        encoding="utf-8",
    )


def main() -> None:
    verify_freeze()
    prepare_results()
    cases = read_csv(FREEZE / "RESULT4_V4_1_CASES.csv")
    references = reference_map()
    completed = {
        row["case_id"] for row in read_csv(LEDGER)
        if row["workflow_status"] in {"PASS", "EXPECTED_CONTROLLED_ABSTENTION"}
    }
    sequence = len(read_csv(LEDGER))
    for case in (row for row in cases if row["case_type"] == "POSITIVE"):
        if case["case_id"] in completed:
            continue
        sequence += 1
        reference, classification = references[case["case_id"]]
        run_positive(sequence, case, reference, classification)
        print(f"[{sequence}/6] {case['case_id']} POSITIVE PASS", flush=True)
    for case in (row for row in cases if row["case_type"] == "NEGATIVE_ABSTENTION"):
        if case["case_id"] in completed:
            continue
        sequence += 1
        run_negative(sequence, case)
        print(f"[{sequence}/6] {case['case_id']} EXPECTED_CONTROLLED_ABSTENTION", flush=True)
    rows = read_csv(LEDGER)
    valid = sum(row["workflow_status"] in {"PASS", "EXPECTED_CONTROLLED_ABSTENTION"} for row in rows)
    if len(rows) != 6 or valid != 6:
        raise RuntimeError(f"V4.1 accounting mismatch: rows={len(rows)}, valid={valid}")
    verify_freeze()
    write_result_outputs(rows)
    write_combined_outputs(rows)
    print("PASS: Result-4 V4.1 has 6/6 valid intended terminals", flush=True)


if __name__ == "__main__":
    main()
