"""Measure production request-SPP quality before Benchmark V3 is frozen.

This script intentionally stops after canonical pair-guidance classification.
It never invokes the QLIP solve, CIF generation, SCA, or reference recovery.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from pymatgen.core import Structure

from sok_llm_orchestrator.bench.prospective import FrozenReference, ProspectiveBenchmarkStages
from sok_llm_orchestrator.workflow.evidence import assemble_spp_evidence, canonical_pair
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
    _prepare_execution_attempt,
    _update_execution_attempt,
)


ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "artifacts" / "final_paper_benchmark"
V2 = ROOT / "artifacts" / "final_paper_benchmark_v2"
OUT = ROOT / "artifacts" / "final_paper_benchmark_v3_quality_preflight"
WORKFLOW_COMMIT = "698d82a37d94b1b64a6f2488a2e3b205dbf0f989"
GENERAL_CORPUS = "mp_stable_10k_v1"
SPECIALIST_CORPUS = "nasicon_specialist_v3"
QUALITY_THRESHOLD = 0.5


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
    ("RDX-E4-A2", "Na3Zr2Si2PO12", ROOT / "data/nasicon/reference/reference.cif", "nasicon-mp1221148"),
    ("RDX-E4-C2", "Na3Ti2(PO4)3", ROOT / "data/corpora/nasicon_specialist_v3/cifs/nasicon-mp761046.cif", "nasicon-mp761046"),
    ("RDX-E4-F1", "LiZr2(PO4)3", ROOT / "data/corpora/nasicon_specialist_v3/cifs/nasicon-mp10499.cif", "nasicon-mp10499"),
)

NASICON_NEGATIVE = (
    ("RDX-NEG-E4-A1", "Na3Zr2Si2PO12", "ORBIT_MULTIPLICITY_NOT_REPRESENTABLE"),
    ("RDX-NEG-E4-A3", "Na3Ti2Si2PO12", "TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH"),
    ("RDX-NEG-E4-A4", "Na3Hf2Si2PO12", "TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def pairs_in_path(path: Path) -> set[str]:
    elements = sorted({str(element) for element in Structure.from_file(path).composition.elements}, key=str.lower)
    return {canonical_pair(left, right) for left in elements for right in elements}


def retrieval_pair_count(retrieval: dict[str, Any], pair: str) -> int:
    count = 0
    for item in retrieval.get("selected", []):
        export = item.get("cif_export") if isinstance(item.get("cif_export"), dict) else {}
        value = export.get("path") or item.get("internal_spp_cif_path")
        path = Path(str(value)).resolve() if value else None
        if path is not None and path.is_file() and pair in pairs_in_path(path):
            count += 1
    return count


def request_for(task: dict[str, Any], *, case_id: str | None = None) -> str:
    prefix = f"{case_id}: " if case_id and case_id.startswith("RDX-NEG") else ""
    return (
        f"{prefix}Generate {task['formula']} as a {task['family']} crystal "
        f"with requested {task['space_group']} symmetry."
    )


def frozen_general_references() -> dict[str, FrozenReference]:
    v1_by_formula = {row["formula"]: row for row in read_csv(V1 / "BENCHMARK_TARGETS.csv")}
    v2_by_formula = {row["formula"]: row for row in read_csv(V2 / "BENCHMARK_V2_REFERENCES.csv")}
    result: dict[str, FrozenReference] = {}
    for case_id, formula in GENERAL_CASES:
        source = v1_by_formula[formula]
        frozen = v2_by_formula[formula]
        reference = FrozenReference.from_cif(
            case_id=case_id,
            formula=formula,
            reference_id=frozen["crystal_db_structure_id"],
            source_structure_id=frozen["source_mp_id"],
            cif_path=ROOT / source["reference_cif_path"],
        )
        if reference.raw_sha256 != frozen["cif_sha256"] or reference.canonical_sha256 != frozen["canonical_sha256"]:
            raise RuntimeError(f"protected frozen reference hash mismatch for {formula}")
        result[formula] = reference
    return result


def quality_config(config: WorkflowConfig) -> dict[str, Any]:
    return {
        "request_spp_convention": config.request_spp_convention,
        "cutoff_angstrom": config.cutoff,
        "max_cap_fraction_threshold": QUALITY_THRESHOLD,
        "request_spp_mode": config.request_spp_mode,
        "regulator_id": config.regulator_id,
    }


def run_guidance_case(
    *,
    case_id: str,
    formula: str,
    stages: ProspectiveBenchmarkStages,
    expected_corpus: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    task = dict(stages._benchmark_tasks[formula])
    request = request_for(task)
    base_config = WorkflowConfig(
        output_root=OUT / "runs" / case_id,
        retrieval_depth=40,
        retrieval_demo_export=True,
        scaffold_mode="loose",
        request_spp_mode="enabled",
    )
    attempt = _prepare_execution_attempt(base_config, request)
    config = replace(base_config, run_id=attempt.run_id, attempt_id=attempt.attempt_id)
    _update_execution_attempt(attempt, "RUNNING", terminal_boundary="PAIR_GUIDANCE_ONLY")
    try:
        normalized = stages.normalise(request)
        retrieval = stages.retrieve(request, normalized, config, attempt.workspace)
        if retrieval["corpus"]["corpus_id"] != expected_corpus:
            raise RuntimeError(
                f"wrong corpus for {formula}: {retrieval['corpus']['corpus_id']} != {expected_corpus}"
            )
        exclusion = stages.last_exclusion
        if exclusion is None or exclusion.reference_equivalent_evidence_count != 0:
            raise RuntimeError(f"reference exclusion failed for {formula}")
        required = stages.required_pairs(normalized, config)
        evidence = assemble_spp_evidence(
            retrieval=retrieval,
            required_pairs=required,
            excluded_structure_ids=(stages.reference.reference_id, stages.reference.source_structure_id),
            max_ranked_structures=config.retrieval_depth,
            allow_partial_pair_coverage=True,
        )
        request_spp = stages.fit_request_spp(evidence, normalized, config, attempt.workspace)
        pair_results = list(request_spp["quality"]["request_pair_results"])
        by_pair = {str(row["species_pair"]): row for row in pair_results}
        if set(by_pair) != set(required):
            raise RuntimeError(f"request-SPP pair domain mismatch for {formula}")
        pair_rows: list[dict[str, Any]] = []
        for pair in required:
            row = by_pair[pair]
            mode = str(row["guidance_mode"])
            if mode not in {
                "REQUEST_PLUS_REGULATOR",
                "REGULATOR_ONLY_LOCAL_INSUFFICIENT",
                "REGULATOR_ONLY_LOCAL_MISSING",
                "GUIDANCE_PAIR_UNSUPPORTED",
                "UNSUPPORTED_REQUIRED_PAIR",
            }:
                raise RuntimeError(f"unexpected guidance mode for {formula}/{pair}: {mode}")
            if mode == "UNSUPPORTED_REQUIRED_PAIR":
                mode = "GUIDANCE_PAIR_UNSUPPORTED"
            pair_rows.append({
                "case_id": case_id,
                "formula": formula,
                "species_pair": pair,
                "retrieved_evidence_count": retrieval_pair_count(retrieval, pair),
                "structures_contributing": int(row["structures_contributing"]),
                "distance_observations": int(row["observations"]),
                "request_pot_generated": "YES" if row.get("request_pot_hash") else "NO",
                "request_pot_cap_fraction": "" if row.get("cap_fraction") is None else row["cap_fraction"],
                "request_pot_quality": row["request_quality"],
                "request_pair_status": row["request_pair_status"],
                "regulator_available": "YES" if row["regulator_available"] else "NO",
                "final_guidance_mode": mode,
            })
        usable = sum(row["final_guidance_mode"] == "REQUEST_PLUS_REGULATOR" for row in pair_rows)
        fallback = sum(row["final_guidance_mode"].startswith("REGULATOR_ONLY_") for row in pair_rows)
        unsupported = sum(row["final_guidance_mode"] == "GUIDANCE_PAIR_UNSUPPORTED" for row in pair_rows)
        if unsupported:
            overall = "UNSUPPORTED"
        elif usable == len(required):
            overall = "FULL_LOCAL_SUPPORT"
        elif usable:
            overall = "PARTIAL_LOCAL_SUPPORT"
        else:
            overall = "NO_USABLE_LOCAL_SUPPORT"
        summary = {
            "case_id": case_id,
            "formula": formula,
            "required_pair_count": len(required),
            "request_usable_pair_count": usable,
            "regulator_fallback_pair_count": fallback,
            "unsupported_pair_count": unsupported,
            "request_usable_fraction": f"{usable / len(required):.6f}",
            "overall_local_support_status": overall,
            "corpus_id": retrieval["corpus"]["corpus_id"],
        }
        retrieval_ids = [str(item.get("structure_id", "")) for item in retrieval.get("selected", [])]
        evidence_ids = [item.structure_id for item in evidence.selected]
        exclusion_counts = {
            "candidates_checked": len(exclusion.audit),
            "exact_id_removed": sum(row.reference_id_match for row in exclusion.audit),
            "raw_hash_removed": sum(row.raw_hash_match for row in exclusion.audit),
            "canonical_hash_removed": sum(row.canonical_hash_match for row in exclusion.audit),
            "structurematcher_equivalent_removed": sum(row.structurematcher_equivalent for row in exclusion.audit),
            "reference_equivalent_evidence_count": exclusion.reference_equivalent_evidence_count,
        }
        provenance = {
            "case_id": case_id,
            "formula": formula,
            "run_id": attempt.run_id,
            "attempt_id": attempt.attempt_id,
            "attempt_workspace": str(attempt.workspace),
            "workflow_commit": WORKFLOW_COMMIT,
            "retrieval": {
                "corpus_id": retrieval["corpus"]["corpus_id"],
                "corpus_hash": retrieval["corpus"]["hash"],
                "ids": retrieval_ids,
                "ids_hash": canonical_hash(retrieval_ids),
                "config": retrieval["config"],
                "config_hash": canonical_hash(retrieval["config"]),
            },
            "reference_exclusion": exclusion_counts,
            "reference": {
                "reference_id": stages.reference.reference_id,
                "raw_sha256": stages.reference.raw_sha256,
                "canonical_sha256": stages.reference.canonical_sha256,
                "coordinates_used_only_for_exclusion": True,
            },
            "request_spp_evidence": {
                "ids": evidence_ids,
                "ids_hash": canonical_hash(evidence_ids),
                "bundle_hash": evidence.bundle_hash,
            },
            "request_pot_hashes": request_spp["request_spp_hashes"],
            "quality_config": quality_config(config),
            "quality_config_hash": canonical_hash(quality_config(config)),
            "regulator_id": request_spp["regulator_id"],
            "regulator_hash": request_spp["regulator_hash"],
            "solver_invoked": False,
            "solver_output_exists": False,
            "cif_generated": False,
            "sca_invoked": False,
            "reference_result_inspected": False,
        }
        _update_execution_attempt(
            attempt,
            "COMPLETED_GUIDANCE_PREFLIGHT",
            pair_guidance_summary=summary,
            evidence_bundle_hash=evidence.bundle_hash,
            request_pot_hashes=request_spp["request_spp_hashes"],
            solver_invoked=False,
            cif_generated=False,
            sca_invoked=False,
        )
        return pair_rows, summary, provenance
    except Exception as exc:
        _update_execution_attempt(attempt, "FAILED", error_type=type(exc).__name__, error=str(exc))
        raise


def run_negative_case(case_id: str, formula: str, expected_code: str) -> dict[str, Any]:
    stages = ProductionWorkflowStages()
    task = dict(stages._TASKS[formula]) if case_id != "RDX-NEG-E4-A1" else {
        "formula": formula,
        "family": "NASICON/NZP",
        "prototype": "nasicon_na3sc2po43_r3c",
        "space_group": "R-3c",
        "expected_abstention": expected_code,
    }
    request = request_for(task, case_id=case_id)
    config = WorkflowConfig(output_root=OUT / "negative_checks" / case_id)
    normalized = stages.normalise(request)
    try:
        stages.required_pairs(normalized, config)
    except WorkflowStageError as exc:
        if exc.stage != "representability" or exc.code != expected_code:
            raise RuntimeError(
                f"unexpected terminal for {case_id}: {exc.stage}/{exc.code}; expected representability/{expected_code}"
            ) from exc
        return {
            "case_id": case_id,
            "formula": formula,
            "case_type": "NEGATIVE_ABSTENTION",
            "corpus_id": "NOT_REACHED_REPRESENTABILITY",
            "request_usable_pair_count": "NOT_FITTED",
            "regulator_fallback_pair_count": "NOT_FITTED",
            "unsupported_pair_count": "NOT_APPLICABLE",
            "terminal_stage": exc.stage,
            "terminal_code": exc.code,
            "ready": "YES",
        }
    raise RuntimeError(f"negative case did not stop at representability: {case_id}")


def assert_no_deterministic_contradictions(provenance: Iterable[dict[str, Any]]) -> None:
    observed: dict[tuple[str, str], str] = {}
    for record in provenance:
        key = (record["request_spp_evidence"]["bundle_hash"], record["quality_config_hash"])
        result_hash = canonical_hash(record["request_pot_hashes"])
        if key in observed and observed[key] != result_hash:
            raise RuntimeError("same deterministic evidence/config produced contradictory request POT hashes")
        observed[key] = result_hash


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    references = frozen_general_references()
    tasks = ProductionWorkflowStages._TASKS
    pair_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []

    for case_id, formula in GENERAL_CASES:
        rows, summary, record = run_guidance_case(
            case_id=case_id,
            formula=formula,
            stages=ProspectiveBenchmarkStages(tasks=tasks, reference=references[formula]),
            expected_corpus=GENERAL_CORPUS,
        )
        pair_rows.extend(rows)
        summaries.append(summary)
        provenance.append(record)

    result3 = []
    for summary in summaries:
        usable = int(summary["request_usable_pair_count"])
        unsupported = int(summary["unsupported_pair_count"])
        classification = (
            "UNSUPPORTED" if unsupported
            else "HIGH" if usable >= 2
            else "MEDIUM" if usable == 1
            else "NOT_INFORMATIVE_FOR_REQUEST_SPP"
        )
        result3.append({
            "case_id": summary["case_id"],
            "formula": summary["formula"],
            "genuinely_variable_scaffold": "YES",
            "request_usable_pair_count": usable,
            "regulator_fallback_pair_count": summary["regulator_fallback_pair_count"],
            "unsupported_pair_count": unsupported,
            "actual_informativeness": classification,
            "included_in_four_mode_execution_design": "YES",
            "included_in_causal_request_spp_denominator": "YES" if usable >= 1 and not unsupported else "NO",
        })

    result4: list[dict[str, Any]] = []
    for case_id, formula, reference_path, reference_id in NASICON_POSITIVE:
        reference = FrozenReference.from_cif(
            case_id=case_id,
            formula=formula,
            reference_id=reference_id,
            source_structure_id=reference_id,
            cif_path=reference_path,
        )
        rows, summary, record = run_guidance_case(
            case_id=case_id,
            formula=formula,
            stages=ProspectiveBenchmarkStages(tasks=tasks, reference=reference),
            expected_corpus=SPECIALIST_CORPUS,
        )
        pair_rows.extend(rows)
        provenance.append(record)
        result4.append({
            "case_id": case_id,
            "formula": formula,
            "case_type": "POSITIVE",
            "corpus_id": summary["corpus_id"],
            "request_usable_pair_count": summary["request_usable_pair_count"],
            "regulator_fallback_pair_count": summary["regulator_fallback_pair_count"],
            "unsupported_pair_count": summary["unsupported_pair_count"],
            "terminal_stage": "PAIR_GUIDANCE_COMPLETE",
            "terminal_code": "",
            "ready": "YES" if int(summary["unsupported_pair_count"]) == 0 else "NO",
        })
    result4.extend(run_negative_case(*case) for case in NASICON_NEGATIVE)

    assert_no_deterministic_contradictions(provenance)
    write_csv(OUT / "ACTUAL_REQUEST_SPP_PAIR_QUALITY.csv", pair_rows)
    write_csv(OUT / "ACTUAL_REQUEST_SPP_TARGET_SUMMARY.csv", summaries)
    write_csv(OUT / "RESULT_3_ACTUAL_INFORMATIVENESS.csv", result3)
    write_csv(OUT / "RESULT_4_GUIDANCE_READINESS.csv", result4)
    write_json(OUT / "GUIDANCE_PREFLIGHT_PROVENANCE.json", {
        "schema_version": "benchmark_v3_guidance_quality_preflight.v1",
        "workflow_commit": WORKFLOW_COMMIT,
        "corrects_proxy": "structural pair presence is replaced by actual production POT fitting and quality gating",
        "quality_threshold_changed": False,
        "evidence_assembly_changed": False,
        "target_set_changed": False,
        "paper_benchmark_solves": 0,
        "runs": provenance,
    })
    write_json(OUT / "QUALITY_PREFLIGHT_STATUS.json", {
        "workflow_commit": WORKFLOW_COMMIT,
        "result_2_targets": len(summaries),
        "result_2_executable": sum(int(row["unsupported_pair_count"]) == 0 for row in summaries),
        "result_3_four_mode_api_executable": 7,
        "result_4_positive_ready": sum(row["case_type"] == "POSITIVE" and row["ready"] == "YES" for row in result4),
        "result_4_negative_ready": sum(row["case_type"] == "NEGATIVE_ABSTENTION" and row["ready"] == "YES" for row in result4),
        "ready_to_freeze": all(int(row["unsupported_pair_count"]) == 0 for row in summaries)
        and all(row["ready"] == "YES" for row in result4),
        "solver_invocations": 0,
        "generated_cifs": 0,
        "sca_invocations": 0,
    })
    print(json.dumps(json.loads((OUT / "QUALITY_PREFLIGHT_STATUS.json").read_text(encoding="utf-8")), indent=2))


if __name__ == "__main__":
    main()
