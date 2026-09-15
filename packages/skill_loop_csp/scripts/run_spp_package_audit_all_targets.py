from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.workflow.evidence import SPPEvidenceBundle, assemble_spp_evidence
from sok_llm_orchestrator.workflow.pair_aware_retrieval import (
    actual_pair_structure_counts,
    append_augmentation_to_retrieval,
    build_family_pair_inventory,
    select_pair_augmentation,
)
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages, WorkflowConfig, WorkflowStageError
from sok_llm_orchestrator.workflow.spp_only_benchmark import (
    SPPOnlyBenchmarkPolicy,
    _dataset_directory,
    _prompt,
    _retrieval_artifacts,
    _structure_ids_by_candidate_key,
    _task,
    benchmark_run_scope,
    leakage_safe_neighbourhood,
)
from sok_llm_orchestrator.workflow.spp_package_audit import (
    assert_family_database_provenance,
    audit_spp_package,
)


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = (
        "experiment_id", "family", "formula", "SPP_READY", "failure_stage", "failure_code",
        "failure_message", "required_pair_count", "local_usable_pair_count",
        "global_only_pair_count", "unsupported_pair_count", "semantic_core_count",
        "coverage_augmentation_count", "final_spp_corpus_count", "missing_after_core",
        "missing_after_augmentation", "PAIR_AWARE_RETRIEVAL_POLICY_APPLIED",
        "EXPECTED_FAMILY_DB_EQUALS_ACTUAL_FAMILY_DB", "CIF_HASH_CHAIN_VALID", "QLIP_RUN",
        "target_directory",
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})
    temporary.replace(path)


def _build_evidence(
    *, retrieval: dict[str, Any], required_pairs: list[str], excluded_ids: tuple[str, ...],
    inventory: list[dict[str, Any]], maximum_corpus_size: int,
) -> SPPEvidenceBundle:
    assembled = assemble_spp_evidence(
        retrieval=retrieval, required_pairs=required_pairs,
        excluded_structure_ids=excluded_ids, max_ranked_structures=maximum_corpus_size,
        allow_partial_pair_coverage=True,
    )
    actual_counts = actual_pair_structure_counts(
        (item.structure_id for item in assembled.selected), inventory, required_pairs,
    )
    statuses = {
        pair: {
            **assembled.pair_evidence_status.get(pair, {}),
            "local_evidence_present": actual_counts[pair] > 0,
            "structures_contributing": actual_counts[pair],
        }
        for pair in required_pairs
    }
    return replace(assembled, pair_structure_counts=actual_counts, pair_evidence_status=statuses)


def run_target(
    *, target: dict[str, Any], pool: dict[str, Any], crystal_root: Path, output_root: Path,
    policy: SPPOnlyBenchmarkPolicy, stages: ProductionWorkflowStages,
) -> dict[str, Any]:
    target_dir = output_root / "targets" / str(target["family"]) / str(target["benchmark_id"])
    target_dir.mkdir(parents=True, exist_ok=True)
    result_path = target_dir / "spp_package_audit.json"
    if result_path.is_file():
        return _read_json(result_path)["summary_row"]
    task = _task(target)
    request = _prompt(target)
    dataset_dir = _dataset_directory(crystal_root, str(target["family"]))
    structure_ids = _structure_ids_by_candidate_key(dataset_dir)
    excluded_ids = tuple(
        structure_ids[key] for key in pool["excluded_candidate_keys"] if key in structure_ids
    )
    config = WorkflowConfig(
        output_root=target_dir, retrieval_depth=policy.candidate_retrieval_depth,
        embedding_model=policy.embedding_model, embedding_version=policy.embedding_version,
        retrieval_demo_export=True, cutoff=policy.cutoff, excluded_structure_ids=excluded_ids,
        scaffold_mode="none", native_qlip=True, cell_mode=policy.cell_mode,
        native_grid_density=policy.native_grid_density,
        run_id=f"spp-correctness-audit-{benchmark_run_scope(output_root)}-{target['benchmark_id']}",
        attempt_id="no-qlip-spp-package-audit-v1",
    )
    row: dict[str, Any] = {
        "experiment_id": target["benchmark_id"], "family": target["family"],
        "formula": target["formula"], "SPP_READY": False, "failure_stage": "",
        "failure_code": "", "failure_message": "", "required_pair_count": 0,
        "local_usable_pair_count": 0, "global_only_pair_count": 0,
        "unsupported_pair_count": 0, "semantic_core_count": 0,
        "coverage_augmentation_count": 0, "final_spp_corpus_count": 0,
        "missing_after_core": "", "missing_after_augmentation": "",
        "PAIR_AWARE_RETRIEVAL_POLICY_APPLIED": True,
        "EXPECTED_FAMILY_DB_EQUALS_ACTUAL_FAMILY_DB": False,
        "CIF_HASH_CHAIN_VALID": False, "QLIP_RUN": False,
        "target_directory": str(target_dir.resolve()),
    }
    try:
        retrieval = stages.retrieve(request, task, config, target_dir / "retrieval")
        database = assert_family_database_provenance(
            target=target, retrieval=retrieval, crystal_root=crystal_root,
        )
        row["EXPECTED_FAMILY_DB_EQUALS_ACTUAL_FAMILY_DB"] = True
        _write_json(target_dir / "retrieval" / "database_provenance.json", database)
        core, exclusions = leakage_safe_neighbourhood(
            retrieval, excluded_structure_ids=excluded_ids, limit=policy.spp_corpus_size,
        )
        required_pairs = stages.required_pairs(task, config)
        row["required_pair_count"] = len(required_pairs)
        inventory = build_family_pair_inventory(
            crystal_root=crystal_root, dataset_dir=dataset_dir, formula=str(target["formula"]),
            cutoff=policy.cutoff, excluded_structure_ids=excluded_ids,
            semantic_retrieval=retrieval, work_dir=target_dir / "retrieval",
        )
        core_ids = [str(item["structure_id"]) for item in core["selected"]]
        core_counts = actual_pair_structure_counts(core_ids, inventory, required_pairs)
        missing_core = [pair for pair, count in core_counts.items() if count == 0]
        additions = select_pair_augmentation(
            candidates=inventory, selected_structure_ids=core_ids,
            priority_pairs=missing_core,
            maximum_additions=policy.maximum_corpus_size - len(core_ids),
            coverage_only=True,
        )
        selected = append_augmentation_to_retrieval(
            core, additions, export_dir=target_dir / "retrieval" / "augmentation_cifs",
        )
        _retrieval_artifacts(target_dir, request, retrieval, selected, exclusions)
        _write_json(target_dir / "retrieval" / "retrieval_core.json", core)
        _write_json(target_dir / "retrieval" / "retrieval_augmentation.json", additions)
        _write_json(target_dir / "spp" / "pair_support.json", inventory)
        evidence = _build_evidence(
            retrieval=selected, required_pairs=required_pairs, excluded_ids=excluded_ids,
            inventory=inventory, maximum_corpus_size=policy.maximum_corpus_size,
        )
        _write_json(target_dir / "spp" / "evidence_bundle.json", evidence.to_dict())
        missing_after = [pair for pair, count in evidence.pair_structure_counts.items() if count == 0]
        row.update({
            "semantic_core_count": len(core_ids),
            "coverage_augmentation_count": len(additions),
            "final_spp_corpus_count": len(evidence.selected),
            "missing_after_core": ";".join(missing_core),
            "missing_after_augmentation": ";".join(missing_after),
        })
        request_spp = stages.fit_request_spp(evidence, task, config, target_dir / "spp" / "fit")
        package = audit_spp_package(
            required_pairs=required_pairs, request_spp=request_spp,
            regulator_root=Path(request_spp["regulator_root"]),
            cif_chain=request_spp.get("quality", {}).get("spp_input_manifest"),
        )
        pair_rows = package["pair_diagnostics"]
        row.update({
            "SPP_READY": bool(package["SPP_READY"]),
            "local_usable_pair_count": sum(item["intended_final_source"] == "request_plus_global_regulator" for item in pair_rows),
            "global_only_pair_count": sum(item["intended_final_source"] == "global_regulator" for item in pair_rows),
            "unsupported_pair_count": len(package["unsupported_pairs"]),
            "CIF_HASH_CHAIN_VALID": bool(package["cif_provenance_valid"]),
        })
        payload = {
            "schema_version": "spp_package_audit.v1", "target": target,
            "policy": asdict(policy), "database_provenance": database,
            "pair_aware_retrieval": {
                "PAIR_AWARE_RETRIEVAL_POLICY_APPLIED": True,
                "semantic_core_k": len(core_ids), "missing_pairs_after_core": missing_core,
                "augmentation_candidates_considered": len(inventory) - len(core_ids),
                "augmentation_structures_added": len(additions),
                "missing_pairs_after_augmentation": missing_after,
                "augmentation_stop_reason": "coverage_complete" if not missing_after else "no_further_same_family_support_or_safety_maximum",
                "maximum_corpus_size": policy.maximum_corpus_size,
            },
            "request_spp_quality": request_spp["quality"],
            "package_audit": package, "summary_row": row,
        }
        _write_json(result_path, payload)
        return row
    except WorkflowStageError as exc:
        row.update(failure_stage=exc.stage, failure_code=exc.code, failure_message=str(exc))
        _write_json(result_path, {
            "schema_version": "spp_package_audit.v1", "target": target,
            "controlled_failure": {"stage": exc.stage, "code": exc.code, "message": str(exc), "details": exc.details},
            "summary_row": row,
        })
        return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--crystal-root", type=Path, default=Path("../Crystal-DB"))
    parser.add_argument("--max-new-targets", type=int)
    args = parser.parse_args()
    frozen = _read_json(args.frozen.resolve())
    targets = list(frozen["targets"])
    pools = {str(row["benchmark_id"]): row for row in frozen["evidence_pools"]}
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    existing = {
        path.parent.name
        for path in output_root.glob("targets/*/*/spp_package_audit.json")
    }
    rows: list[dict[str, Any]] = []
    new_count = 0
    stages = ProductionWorkflowStages()
    policy = SPPOnlyBenchmarkPolicy()
    for target in targets:
        experiment_id = str(target["benchmark_id"])
        if args.max_new_targets is not None and new_count >= args.max_new_targets and experiment_id not in existing:
            break
        was_existing = experiment_id in existing
        rows.append(run_target(
            target=target, pool=pools[experiment_id], crystal_root=args.crystal_root.resolve(),
            output_root=output_root, policy=policy, stages=stages,
        ))
        if not was_existing:
            new_count += 1
        _write_csv(output_root / "SPP_PACKAGE_AUDIT_ALL_TARGETS.csv", rows)
        _write_json(output_root / "SPP_PACKAGE_AUDIT_SUMMARY.json", {
            "processed_targets": len(rows), "spp_ready": sum(bool(row["SPP_READY"]) for row in rows),
            "not_ready": sum(not bool(row["SPP_READY"]) for row in rows),
            "qlip_runs": sum(bool(row["QLIP_RUN"]) for row in rows),
            "pair_aware_assertions": sum(bool(row["PAIR_AWARE_RETRIEVAL_POLICY_APPLIED"]) for row in rows),
            "family_database_assertions": sum(bool(row["EXPECTED_FAMILY_DB_EQUALS_ACTUAL_FAMILY_DB"]) for row in rows),
            "cif_hash_chain_assertions": sum(bool(row["CIF_HASH_CHAIN_VALID"]) for row in rows),
        })
    print((output_root / "SPP_PACKAGE_AUDIT_SUMMARY.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
