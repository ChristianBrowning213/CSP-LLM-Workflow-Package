"""Launch the frozen 41-execution Benchmark V3 through the canonical API.

This file contains orchestration, provenance validation, and post-generation
measurement only. Scientific execution is exclusively delegated to
``sok_llm_orchestrator.workflow.runner.run_csp_workflow``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.bench.prospective import FrozenReference, ProspectiveBenchmarkStages
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
    run_csp_workflow,
)


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "artifacts" / "final_paper_benchmark_v3"
RESULTS = FREEZE / "results"
V1 = ROOT / "artifacts" / "final_paper_benchmark"
TRACE_SOURCE = ROOT / "artifacts" / "paper_results_final_redesign" / "01_traceability"
WORKFLOW_COMMIT = "698d82a37d94b1b64a6f2488a2e3b205dbf0f989"
EXPECTED_HASHES = {
    "BENCHMARK_V3_CONFIG.json": "f974489e16a6771b3ae270c8e4062de0f9309b7339e1ed07c6de0f5f7a176fd0",
    "BENCHMARK_V3_TARGETS.csv": "58ad9337e978b2db144b0bcd35bf048ef25113d90ccf4a1e7754c6078f9f31ac",
    "BENCHMARK_V3_REFERENCES.csv": "6af602b3d4d06d9fd92ced7f02e026560a52b4935324e6f6721d248f5e18aeb1",
    "RESULT_3_INFORMATIVENESS.csv": "fcba2bad71dbc5b03c9b7a9a8066c5d901496775f35fbc18480e2cb9015e5f95",
    "BENCHMARK_V3_FREEZE.json": "ae981fcac24b8f977fad3a70e9257a224e8570d93c58d0c13aab96aa7fb98c57",
}
EXPECTED_GENERAL_CORPUS = "mp_stable_10k_v1"
EXPECTED_NASICON_CORPUS = "nasicon_specialist_v3"
EXPECTED_REGULATOR = "icsd_broad_regulator_v1"

DIRS = {
    "result_1": RESULTS / "result_1_traceability",
    "result_2": RESULTS / "result_2_heldout",
    "result_3": RESULTS / "result_3_factorial",
    "result_4": RESULTS / "result_4_nasicon",
    "summary": RESULTS / "summary",
    "provenance": RESULTS / "provenance",
}
LEDGER = RESULTS / "EXECUTION_LEDGER.csv"

GENERAL_CASES = (
    ("RDX-BATIO3", "BaTiO3"),
    ("RDX-CATIO3", "CaTiO3"),
    ("RDX-CSPBBR3", "CsPbBr3"),
    ("RDX-CSPBCL3", "CsPbCl3"),
    ("RDX-CSPBI3", "CsPbI3"),
    ("RDX-CSSNBR3", "CsSnBr3"),
    ("RDX-CSSNI3", "CsSnI3"),
)
NASICON_POSITIVE = (
    ("RDX-E4-A2", "Na3Zr2Si2PO12", ROOT / "data/nasicon/reference/reference.cif", "nasicon-mp1221148", "TARGET_DERIVED_DEMONSTRATION"),
    ("RDX-E4-C2", "Na3Ti2(PO4)3", ROOT / "data/corpora/nasicon_specialist_v3/cifs/nasicon-mp761046.cif", "nasicon-mp761046", "TARGET_DERIVED_DEMONSTRATION"),
    ("RDX-E4-F1", "LiZr2(PO4)3", ROOT / "data/corpora/nasicon_specialist_v3/cifs/nasicon-mp10499.cif", "nasicon-mp10499", "INDEPENDENT_REFERENCE_RECOVERY"),
)
NASICON_NEGATIVE = (
    ("RDX-NEG-E4-A1", "Na3Zr2Si2PO12", "ORBIT_MULTIPLICITY_NOT_REPRESENTABLE"),
    ("RDX-NEG-E4-A3", "Na3Ti2Si2PO12", "TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH"),
    ("RDX-NEG-E4-A4", "Na3Hf2Si2PO12", "TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH"),
)
CONDITIONS = (
    ("TIGHT_REGULATOR_ONLY", "tight", "disabled"),
    ("TIGHT_REGULATOR_PLUS_REQUEST", "tight", "enabled"),
    ("LOOSE_REGULATOR_ONLY", "loose", "disabled"),
    ("LOOSE_REGULATOR_PLUS_REQUEST", "loose", "enabled"),
)

LEDGER_FIELDS = [
    "sequence_number", "result_block", "case_id", "condition_id", "run_id", "attempt_id",
    "formula", "request", "workflow_commit", "benchmark_config_hash", "target_hash",
    "reference_manifest_hash", "informativeness_hash", "freeze_hash", "corpus_id", "corpus_hash",
    "retrieval_backend", "embedding_model", "retrieved_count", "retrieved_ids",
    "reference_ID_exclusions", "raw_duplicate_exclusions", "canonical_duplicate_exclusions",
    "StructureMatcher_exclusions", "reference_equivalent_evidence_count", "request_spp_run_id",
    "request_spp_hash", "required_pair_count", "request_usable_pair_count",
    "regulator_fallback_pair_count", "unsupported_pair_count", "request_usable_fraction",
    "regulator_id", "regulator_hash", "scaffold_mode", "scaffold_id", "feasible_state_count",
    "selected_state", "solver_status", "solver_objective", "independent_objective",
    "objective_difference", "objective_parity", "request_objective", "regulator_objective",
    "combined_objective", "cif_generated", "cif_path", "cif_hash", "cif_parse",
    "exact_composition", "sca_status", "sca_topology", "minimum_distance_A", "reference_id",
    "reference_cif_hash", "reference_match", "generated_space_group", "reference_space_group",
    "exact_space_group_agreement", "crystal_system_agreement", "generated_volume_A3",
    "reference_volume_A3", "generated_volume_per_atom_A3", "reference_volume_per_atom_A3",
    "absolute_volume_error_percent", "reference_classification", "workflow_status", "failure_stage",
    "failure_code", "failure_message", "started_at", "completed_at",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    columns = fields or (list(rows[0]) if rows else [])
    if not columns:
        raise RuntimeError(f"CSV schema required for empty output: {path}")
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
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if commit != WORKFLOW_COMMIT:
        raise RuntimeError(f"workflow commit changed: {commit} != {WORKFLOW_COMMIT}")
    for name, expected in EXPECTED_HASHES.items():
        actual = sha256(FREEZE / name)
        if actual != expected:
            raise RuntimeError(f"frozen hash changed for {name}: {actual} != {expected}")
    tracked_diff = subprocess.check_output(
        ["git", "diff", "--name-only", WORKFLOW_COMMIT, "--", "src/sok_llm_orchestrator/workflow"],
        cwd=ROOT, text=True,
    ).strip()
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src/sok_llm_orchestrator/workflow"],
        cwd=ROOT, text=True,
    ).strip()
    if tracked_diff or untracked:
        raise RuntimeError(f"scientific workflow diff detected: tracked={tracked_diff!r}, untracked={untracked!r}")
    with (FREEZE / "OUTPUT_HASH_MANIFEST.csv").open("r", encoding="utf-8", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    if len(manifest) != 9:
        raise RuntimeError(f"freeze manifest row count changed: {len(manifest)}")
    for row in manifest:
        if sha256(FREEZE / row["path"]) != row["sha256"]:
            raise RuntimeError(f"freeze manifest mismatch: {row['path']}")
    payload = json.loads((FREEZE / "BENCHMARK_V3_FREEZE.json").read_text(encoding="utf-8"))
    if int(payload["CSP_benchmark_solves_executed_before_freeze"]) != 0:
        raise RuntimeError("freeze does not record zero pre-freeze benchmark solves")
    return payload


def prepare_results() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    for path in DIRS.values():
        path.mkdir(parents=True, exist_ok=True)
    for name in ("EXECUTION_FUNNEL.csv", "EXECUTION_FUNNEL.md"):
        destination = DIRS["result_1"] / name
        source = TRACE_SOURCE / name
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            raise RuntimeError(f"Result-1 carry-forward mutation detected: {destination}")
        if not destination.exists():
            shutil.copy2(source, destination)
    write_json(DIRS["provenance"] / "LAUNCH_FREEZE_VERIFICATION.json", {
        "verified_at": now(),
        "workflow_commit": WORKFLOW_COMMIT,
        "protected_hashes": EXPECTED_HASHES,
        "full_freeze_manifest_status": "PASS",
        "scientific_workflow_diff": [],
        "protocol_mutations": 0,
    })


def general_references() -> dict[str, FrozenReference]:
    v1 = {row["formula"]: row for row in read_csv(V1 / "BENCHMARK_TARGETS.csv")}
    refs = {row["formula"]: row for row in read_csv(FREEZE / "BENCHMARK_V3_REFERENCES.csv")}
    result = {}
    for case_id, formula in GENERAL_CASES:
        frozen = refs[formula]
        reference = FrozenReference.from_cif(
            case_id=case_id, formula=formula,
            reference_id=frozen["crystal_db_structure_id"], source_structure_id=frozen["source_mp_id"],
            cif_path=ROOT / v1[formula]["reference_cif_path"],
        )
        if reference.raw_sha256 != frozen["cif_sha256"] or reference.canonical_sha256 != frozen["canonical_sha256"]:
            raise RuntimeError(f"frozen reference mutation for {formula}")
        result[formula] = reference
    return result


def nasicon_references() -> dict[str, tuple[FrozenReference, str]]:
    result = {}
    for case_id, formula, path, reference_id, classification in NASICON_POSITIVE:
        result[case_id] = (
            FrozenReference.from_cif(
                case_id=case_id, formula=formula, reference_id=reference_id,
                source_structure_id=reference_id, cif_path=path,
            ),
            classification,
        )
    return result


def request_for(task: dict[str, Any], case_id: str | None = None) -> str:
    prefix = f"{case_id}: " if case_id and case_id.startswith("RDX-NEG") else ""
    return f"{prefix}Generate {task['formula']} as a {task['family']} crystal with requested {task['space_group']} symmetry."


def latest_attempt(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifests = sorted(root.glob("attempts/*/attempt_manifest.json"), key=lambda path: path.stat().st_mtime_ns)
    if not manifests:
        return {}, {}
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    trace_path = manifests[-1].parent / "workflow_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8")) if trace_path.is_file() else {}
    return manifest, trace


def exclusion_counts(stages: Any) -> dict[str, int]:
    exclusion = getattr(stages, "last_exclusion", None)
    if exclusion is None:
        return {key: 0 for key in (
            "reference_ID_exclusions", "raw_duplicate_exclusions", "canonical_duplicate_exclusions",
            "StructureMatcher_exclusions", "reference_equivalent_evidence_count",
        )}
    return {
        "reference_ID_exclusions": sum(row.reference_id_match for row in exclusion.audit),
        "raw_duplicate_exclusions": sum(row.raw_hash_match for row in exclusion.audit),
        "canonical_duplicate_exclusions": sum(row.canonical_hash_match for row in exclusion.audit),
        "StructureMatcher_exclusions": sum(row.structurematcher_equivalent for row in exclusion.audit),
        "reference_equivalent_evidence_count": exclusion.reference_equivalent_evidence_count,
    }


def minimum_distance(structure: Structure) -> float | None:
    if len(structure) < 2:
        return None
    matrix = np.asarray(structure.distance_matrix, dtype=float)
    matrix[matrix <= 1e-12] = np.inf
    value = float(matrix.min())
    return value if np.isfinite(value) else None


def structure_metrics(cif_path: Path, reference: FrozenReference, formula: str) -> dict[str, Any]:
    generated = Structure.from_file(cif_path)
    heldout = Structure.from_file(reference.cif_path)
    matcher = StructureMatcher()
    generated_sg = SpacegroupAnalyzer(generated, symprec=1e-2, angle_tolerance=5)
    reference_sg = SpacegroupAnalyzer(heldout, symprec=1e-2, angle_tolerance=5)
    generated_symbol = generated_sg.get_space_group_symbol()
    reference_symbol = reference_sg.get_space_group_symbol()
    generated_system = generated_sg.get_crystal_system()
    reference_system = reference_sg.get_crystal_system()
    generated_vpa = float(generated.volume / len(generated))
    reference_vpa = float(heldout.volume / len(heldout))
    return {
        "cif_parse": "YES",
        "exact_composition": "YES" if generated.composition.reduced_composition == Composition(formula).reduced_composition else "NO",
        "reference_match": "YES" if matcher.fit(generated, heldout) else "NO",
        "generated_space_group": generated_symbol,
        "reference_space_group": reference_symbol,
        "exact_space_group_agreement": "YES" if generated_symbol == reference_symbol else "NO",
        "crystal_system_agreement": "YES" if generated_system == reference_system else "NO",
        "generated_volume_A3": float(generated.volume),
        "reference_volume_A3": float(heldout.volume),
        "generated_volume_per_atom_A3": generated_vpa,
        "reference_volume_per_atom_A3": reference_vpa,
        "absolute_volume_error_percent": 100.0 * abs(generated_vpa - reference_vpa) / reference_vpa,
        "minimum_distance_A": minimum_distance(generated),
    }


def selected_state(cif_path: Path, task: dict[str, Any]) -> str:
    structure = Structure.from_file(cif_path)
    roles = task.get("roles") or {}
    if set(roles) == {"A", "B", "X"}:
        cations = [site for site in structure if str(site.specie) in {str(roles["A"]), str(roles["B"])}]
        ordered = sorted(cations, key=lambda site: tuple(round(float(value) % 1.0, 6) for value in site.frac_coords))
        return ";".join(f"{site.specie}@{','.join(f'{float(v)%1.0:.6f}' for v in site.frac_coords)}" for site in ordered)
    return sha256(cif_path)


def append_ledger(row: dict[str, Any]) -> None:
    rows = read_csv(LEDGER)
    rows.append({field: row.get(field, "") for field in LEDGER_FIELDS})
    write_csv(LEDGER, rows, LEDGER_FIELDS)


def update_block(path: Path, row: dict[str, Any]) -> None:
    rows = read_csv(path)
    rows.append(row)
    fields = list(dict.fromkeys(key for item in rows for key in item))
    write_csv(path, rows, fields)
    write_json(path.with_suffix(".json"), rows)


def completed_keys() -> set[tuple[str, str, str]]:
    return {
        (row["result_block"], row["case_id"], row["condition_id"])
        for row in read_csv(LEDGER)
        if row["workflow_status"] in {"PASS", "EXPECTED_CONTROLLED_ABSTENTION"}
    }


def base_ledger(sequence: int, block: str, case_id: str, condition: str, formula: str, request: str, reference: FrozenReference | None, classification: str) -> dict[str, Any]:
    return {
        "sequence_number": sequence, "result_block": block, "case_id": case_id,
        "condition_id": condition, "formula": formula, "request": request,
        "workflow_commit": WORKFLOW_COMMIT,
        "benchmark_config_hash": EXPECTED_HASHES["BENCHMARK_V3_CONFIG.json"],
        "target_hash": EXPECTED_HASHES["BENCHMARK_V3_TARGETS.csv"],
        "reference_manifest_hash": EXPECTED_HASHES["BENCHMARK_V3_REFERENCES.csv"],
        "informativeness_hash": EXPECTED_HASHES["RESULT_3_INFORMATIVENESS.csv"],
        "freeze_hash": EXPECTED_HASHES["BENCHMARK_V3_FREEZE.json"],
        "embedding_model": "text-embedding-bge-m3/lmstudio_v1",
        "reference_id": reference.reference_id if reference else "NOT_APPLICABLE",
        "reference_cif_hash": reference.raw_sha256 if reference else "NOT_APPLICABLE",
        "reference_classification": classification,
        "started_at": now(), "workflow_status": "STARTED",
    }


def validate_success(result: Any, stages: ProspectiveBenchmarkStages, expected_corpus: str, expected_counts: tuple[int, int], freeze_payload: dict[str, Any]) -> None:
    verify_freeze()
    if result.corpus_id != expected_corpus:
        raise RuntimeError(f"wrong corpus: {result.corpus_id} != {expected_corpus}")
    if result.regulator_spp_hash != freeze_payload["regulator"]["tree_sha256"]:
        raise RuntimeError("wrong frozen regulator hash")
    if result.unsupported_pair_count:
        raise RuntimeError("unsupported guidance reached QLIP")
    if result.objective_difference >= 1e-6:
        raise RuntimeError(f"objective parity failure: {result.objective_difference}")
    counts = (result.request_supported_pair_count, result.regulator_fallback_pair_count)
    if counts != expected_counts:
        raise RuntimeError(f"deterministic request-SPP support discrepancy: {counts} != {expected_counts}")
    excluded = exclusion_counts(stages)
    if excluded["reference_equivalent_evidence_count"] != 0:
        raise RuntimeError("reference-equivalent evidence reached request-SPP")


def run_positive(
    *, sequence: int, block: str, case_id: str, condition: str, formula: str,
    stages: ProspectiveBenchmarkStages, reference: FrozenReference, classification: str,
    expected_corpus: str, scaffold_mode: str, request_mode: str,
    expected_counts: tuple[int, int], freeze_payload: dict[str, Any], output_root: Path,
) -> dict[str, Any]:
    task = stages.normalise(formula)
    request = request_for(task)
    base = base_ledger(sequence, block, case_id, condition, formula, request, reference, classification)
    config = WorkflowConfig(
        output_root=output_root, retrieval_depth=40, retrieval_demo_export=True,
        excluded_structure_ids=(reference.reference_id, reference.source_structure_id),
        scaffold_mode=scaffold_mode, request_spp_mode=request_mode, stages=stages,
    )
    try:
        result = run_csp_workflow(request, config)
        validate_success(result, stages, expected_corpus, expected_counts, freeze_payload)
        manifest, trace = latest_attempt(output_root)
        metrics = structure_metrics(Path(result.generated_cif_path), reference, formula)
        exclusions = exclusion_counts(stages)
        pair_count = result.request_supported_pair_count + result.regulator_fallback_pair_count + result.unsupported_pair_count
        row = {
            **base, **exclusions, **metrics,
            "run_id": result.run_id, "attempt_id": result.attempt_id,
            "corpus_id": result.corpus_id, "corpus_hash": result.corpus_hash,
            "retrieval_backend": result.provenance_manifest["retrieval_backend"],
            "retrieved_count": len(result.retrieved_ids), "retrieved_ids": ";".join(result.retrieved_ids),
            "request_spp_run_id": result.request_spp_run_id,
            "request_spp_hash": manifest.get("request_spp_hash", ""),
            "required_pair_count": pair_count,
            "request_usable_pair_count": result.request_supported_pair_count,
            "regulator_fallback_pair_count": result.regulator_fallback_pair_count,
            "unsupported_pair_count": result.unsupported_pair_count,
            "request_usable_fraction": result.request_supported_pair_count / pair_count,
            "regulator_id": EXPECTED_REGULATOR, "regulator_hash": result.regulator_spp_hash,
            "scaffold_mode": result.scaffold_mode, "scaffold_id": result.scaffold_id,
            "feasible_state_count": result.feasible_state_count,
            "selected_state": selected_state(Path(result.generated_cif_path), result.normalised_task),
            "solver_status": result.solver_status, "solver_objective": result.solver_objective,
            "independent_objective": result.independent_objective,
            "objective_difference": result.objective_difference,
            "objective_parity": "PASS" if result.objective_difference < 1e-6 else "FAIL",
            "request_objective": result.request_component,
            "regulator_objective": result.regulator_component,
            "combined_objective": result.combined_objective,
            "cif_generated": "YES", "cif_path": result.generated_cif_path,
            "cif_hash": result.generated_cif_hash,
            "sca_status": result.sca_result.get("status", "UNKNOWN"),
            "sca_topology": result.sca_result.get("topology_status", "UNKNOWN"),
            "workflow_status": "PASS", "failure_stage": "", "failure_code": "", "failure_message": "",
            "started_at": manifest.get("started_at", base["started_at"]),
            "completed_at": manifest.get("completed_at", manifest.get("updated_at", now())),
        }
        append_ledger(row)
        return row
    except Exception as exc:
        manifest, trace = latest_attempt(output_root)
        row = {
            **base, **exclusion_counts(stages),
            "run_id": manifest.get("run_id", trace.get("run_id", "")),
            "attempt_id": manifest.get("attempt_id", trace.get("attempt_id", "")),
            "corpus_id": trace.get("corpus_id", ""), "corpus_hash": trace.get("corpus_hash", ""),
            "retrieval_backend": trace.get("retrieval_backend", ""),
            "retrieved_count": trace.get("retrieval_count", ""),
            "retrieved_ids": ";".join(trace.get("retrieved_ids", [])),
            "request_spp_run_id": trace.get("fresh_request_spp_run_id", ""),
            "request_spp_hash": manifest.get("request_spp_hash", ""),
            "required_pair_count": len(trace.get("required_pairs", [])),
            "request_usable_pair_count": trace.get("request_supported_pair_count", ""),
            "regulator_fallback_pair_count": trace.get("regulator_fallback_pair_count", ""),
            "unsupported_pair_count": trace.get("unsupported_pair_count", ""),
            "regulator_id": trace.get("regulator_id", ""), "regulator_hash": trace.get("regulator_hash", ""),
            "scaffold_mode": scaffold_mode, "cif_generated": "YES" if trace.get("CIF_generated") else "NO",
            "cif_path": trace.get("CIF_path", ""), "cif_hash": trace.get("CIF_hash", ""),
            "solver_status": trace.get("solver_status", ""), "objective_parity": trace.get("objective_parity", ""),
            "sca_status": trace.get("SCA_status", ""), "workflow_status": "FAILED_SOFTWARE_OR_PROVENANCE",
            "failure_stage": trace.get("failure_stage", getattr(exc, "stage", "orchestrator_validation")),
            "failure_code": trace.get("failure_code", getattr(exc, "code", type(exc).__name__)),
            "failure_message": str(exc), "started_at": manifest.get("started_at", base["started_at"]),
            "completed_at": manifest.get("updated_at", now()),
        }
        append_ledger(row)
        raise


def run_negative(sequence: int, case_id: str, formula: str, expected_code: str, freeze_payload: dict[str, Any]) -> dict[str, Any]:
    stages = ProductionWorkflowStages()
    if case_id == "RDX-NEG-E4-A1":
        task = {"formula": formula, "family": "NASICON/NZP", "prototype": "nasicon_na3sc2po43_r3c", "space_group": "R-3c", "expected_abstention": expected_code}
    else:
        task = dict(stages._TASKS[formula])
    request = request_for(task, case_id)
    base = base_ledger(sequence, "RESULT_4", case_id, "CONTROLLED_REPRESENTABILITY", formula, request, None, "CONTROLLED_NEGATIVE")
    output_root = DIRS["result_4"] / "runs" / case_id / "CONTROLLED_REPRESENTABILITY"
    config = WorkflowConfig(output_root=output_root, scaffold_mode="loose", request_spp_mode="enabled", stages=stages)
    try:
        run_csp_workflow(request, config)
    except WorkflowStageError as exc:
        manifest, trace = latest_attempt(output_root)
        verify_freeze()
        if exc.stage != "representability" or exc.code != expected_code:
            row = {**base, "run_id": manifest.get("run_id", ""), "attempt_id": manifest.get("attempt_id", ""), "workflow_status": "FAILED_SOFTWARE_OR_PROVENANCE", "failure_stage": exc.stage, "failure_code": exc.code, "failure_message": str(exc), "started_at": manifest.get("started_at", base["started_at"]), "completed_at": manifest.get("updated_at", now())}
            append_ledger(row)
            raise RuntimeError(f"wrong controlled terminal for {case_id}: {exc.stage}/{exc.code}") from exc
        if trace.get("corpus_id") != EXPECTED_NASICON_CORPUS:
            row = {**base, "run_id": manifest.get("run_id", ""), "attempt_id": manifest.get("attempt_id", ""), "corpus_id": trace.get("corpus_id", ""), "workflow_status": "FAILED_SOFTWARE_OR_PROVENANCE", "failure_stage": "retrieval", "failure_code": "WRONG_CORPUS", "failure_message": str(trace.get("corpus_id")), "started_at": manifest.get("started_at", base["started_at"]), "completed_at": manifest.get("updated_at", now())}
            append_ledger(row)
            raise RuntimeError(f"wrong corpus for {case_id}")
        row = {
            **base, "run_id": manifest.get("run_id", trace.get("run_id", "")),
            "attempt_id": manifest.get("attempt_id", trace.get("attempt_id", "")),
            "corpus_id": trace.get("corpus_id", ""), "corpus_hash": trace.get("corpus_hash", ""),
            "retrieval_backend": trace.get("retrieval_backend", ""), "retrieved_count": trace.get("retrieval_count", ""),
            "retrieved_ids": ";".join(trace.get("retrieved_ids", [])), "scaffold_mode": "loose",
            "solver_status": "NOT_REACHED", "cif_generated": "NO", "sca_status": "NOT_REACHED",
            "workflow_status": "EXPECTED_CONTROLLED_ABSTENTION", "failure_stage": exc.stage,
            "failure_code": exc.code, "failure_message": str(exc),
            "started_at": manifest.get("started_at", base["started_at"]), "completed_at": manifest.get("updated_at", now()),
        }
        append_ledger(row)
        return row
    except Exception as exc:
        manifest, trace = latest_attempt(output_root)
        row = {**base, "run_id": manifest.get("run_id", ""), "attempt_id": manifest.get("attempt_id", ""), "workflow_status": "FAILED_SOFTWARE_OR_PROVENANCE", "failure_stage": trace.get("failure_stage", "unknown"), "failure_code": trace.get("failure_code", type(exc).__name__), "failure_message": str(exc), "started_at": manifest.get("started_at", base["started_at"]), "completed_at": manifest.get("updated_at", now())}
        append_ledger(row)
        raise
    raise RuntimeError(f"negative case unexpectedly completed: {case_id}")


def write_leakage_audit(rows: list[dict[str, Any]]) -> None:
    path = DIRS["result_2"] / "RESULT_2_LEAKAGE_AUDIT.csv"
    write_csv(path, rows, [
        "case_id", "formula", "structure_id", "retrieval_rank", "retrieval_source",
        "reference_id_match", "raw_hash_match", "canonical_hash_match",
        "structurematcher_equivalent", "included_in_request_spp", "exclusion_reason",
    ])


def main() -> None:
    freeze_payload = verify_freeze()
    prepare_results()
    general_refs = general_references()
    nasicon_refs = nasicon_references()
    target_support = {row["formula"]: (int(row["request_usable_pair_count"]), int(row["regulator_fallback_pair_count"])) for row in read_csv(FREEZE / "BENCHMARK_V3_TARGETS.csv")}
    nasicon_support = {row["formula"]: (int(row["request_usable_pair_count"]), int(row["regulator_fallback_pair_count"])) for row in read_csv(ROOT / "artifacts/final_paper_benchmark_v3_quality_preflight/RESULT_4_GUIDANCE_READINESS.csv") if row["case_type"] == "POSITIVE"}
    done = completed_keys()
    sequence = max([int(row["sequence_number"]) for row in read_csv(LEDGER)] or [0])
    leakage_rows = read_csv(DIRS["result_2"] / "RESULT_2_LEAKAGE_AUDIT.csv")

    for case_id, formula in GENERAL_CASES:
        key = ("RESULT_2", case_id, "CANONICAL_HELDOUT")
        if key in done:
            continue
        sequence += 1
        stages = ProspectiveBenchmarkStages(tasks=ProductionWorkflowStages._TASKS, reference=general_refs[formula])
        row = run_positive(
            sequence=sequence, block="RESULT_2", case_id=case_id, condition="CANONICAL_HELDOUT",
            formula=formula, stages=stages, reference=general_refs[formula], classification="STRICT_INDEPENDENT",
            expected_corpus=EXPECTED_GENERAL_CORPUS, scaffold_mode="loose", request_mode="enabled",
            expected_counts=target_support[formula], freeze_payload=freeze_payload,
            output_root=DIRS["result_2"] / "runs" / case_id / "CANONICAL_HELDOUT",
        )
        update_block(DIRS["result_2"] / "RESULT_2_HELDOUT_RECOVERY.csv", row)
        for audit in stages.last_exclusion.audit if stages.last_exclusion else ():
            leakage_rows.append({"case_id": case_id, "formula": formula, **asdict(audit)})
        write_leakage_audit(leakage_rows)
        print(f"[{sequence}/41] RESULT_2 {formula} PASS", flush=True)

    for case_id, formula in GENERAL_CASES:
        for condition, scaffold_mode, request_mode in CONDITIONS:
            key = ("RESULT_3", case_id, condition)
            if key in done:
                continue
            sequence += 1
            expected = target_support[formula] if request_mode == "enabled" else (0, 6)
            stages = ProspectiveBenchmarkStages(tasks=ProductionWorkflowStages._TASKS, reference=general_refs[formula])
            row = run_positive(
                sequence=sequence, block="RESULT_3", case_id=case_id, condition=condition,
                formula=formula, stages=stages, reference=general_refs[formula], classification="FACTORIAL",
                expected_corpus=EXPECTED_GENERAL_CORPUS, scaffold_mode=scaffold_mode, request_mode=request_mode,
                expected_counts=expected, freeze_payload=freeze_payload,
                output_root=DIRS["result_3"] / "runs" / case_id / condition,
            )
            row["request_spp_mode"] = request_mode
            row["tight_arm_interpretation"] = "HARD_CONSTRAINT_DETERMINED" if scaffold_mode == "tight" else "SELECTION_INFORMATIVE_IF_REQUEST_SUPPORTED"
            update_block(DIRS["result_3"] / "RESULT_3_FACTORIAL.csv", row)
            print(f"[{sequence}/41] RESULT_3 {formula} {condition} PASS", flush=True)

    for case_id, formula, _, _, _ in NASICON_POSITIVE:
        key = ("RESULT_4", case_id, "POSITIVE_CANONICAL")
        if key in done:
            continue
        sequence += 1
        reference, classification = nasicon_refs[case_id]
        stages = ProspectiveBenchmarkStages(tasks=ProductionWorkflowStages._TASKS, reference=reference)
        row = run_positive(
            sequence=sequence, block="RESULT_4", case_id=case_id, condition="POSITIVE_CANONICAL",
            formula=formula, stages=stages, reference=reference, classification=classification,
            expected_corpus=EXPECTED_NASICON_CORPUS, scaffold_mode="loose", request_mode="enabled",
            expected_counts=nasicon_support[formula], freeze_payload=freeze_payload,
            output_root=DIRS["result_4"] / "runs" / case_id / "POSITIVE_CANONICAL",
        )
        update_block(DIRS["result_4"] / "RESULT_4_NASICON_POSITIVE.csv", row)
        print(f"[{sequence}/41] RESULT_4 {formula} PASS", flush=True)

    for case_id, formula, expected_code in NASICON_NEGATIVE:
        key = ("RESULT_4", case_id, "CONTROLLED_REPRESENTABILITY")
        if key in done:
            continue
        sequence += 1
        row = run_negative(sequence, case_id, formula, expected_code, freeze_payload)
        update_block(DIRS["result_4"] / "RESULT_4_NASICON_NEGATIVE.csv", row)
        print(f"[{sequence}/41] RESULT_4 {case_id} EXPECTED_CONTROLLED_ABSTENTION", flush=True)

    rows = read_csv(LEDGER)
    if len(rows) != 41:
        raise RuntimeError(f"prospective execution accounting mismatch: {len(rows)} != 41")
    if any(row["workflow_status"] == "FAILED_SOFTWARE_OR_PROVENANCE" for row in rows):
        raise RuntimeError("software/provenance failure exists in execution ledger")
    verify_freeze()
    write_json(DIRS["provenance"] / "CAMPAIGN_EXECUTION_STATUS.json", {
        "status": "EXECUTION_COMPLETE_PENDING_FINAL_ANALYSIS",
        "planned": 41, "accounted": len(rows),
        "completed": sum(row["workflow_status"] == "PASS" for row in rows),
        "controlled_abstentions": sum(row["workflow_status"] == "EXPECTED_CONTROLLED_ABSTENTION" for row in rows),
        "unexpected_failures": 0, "objective_parity_failures": 0, "leakage_violations": 0,
        "wrong_corpus_violations": 0, "completed_at": now(),
    })
    print("PASS 41/41 prospective executions accounted for; final analysis may proceed", flush=True)


if __name__ == "__main__":
    main()
