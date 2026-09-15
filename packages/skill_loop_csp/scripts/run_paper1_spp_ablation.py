"""Run the frozen global-regulator-only Paper 1 SPP ablation condition."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from sok_llm_orchestrator.workflow.component_paths import ComponentRoots
from sok_llm_orchestrator.workflow.csv_workflow import (
    REPO_ROOT,
    _workflow_config,
    load_workflow_config,
    validate_csv,
)
from sok_llm_orchestrator.workflow.evidence import EvidenceItem, SPPEvidenceBundle


CONDITION = "B_GLOBAL_REGULATOR_ONLY"


def is_scientific_failure(error_code: str) -> bool:
    return (
        error_code.startswith("QLIP_INFEASIBLE")
        or error_code == "GUIDANCE_PAIR_UNSUPPORTED"
        or error_code == "PRIMARY_PREFLIGHT_NO_DYNAMIC_CELL"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def evidence_from_dict(payload: Mapping[str, Any]) -> SPPEvidenceBundle:
    items = tuple(
        EvidenceItem(
            structure_id=str(item["structure_id"]),
            retrieval_rank=int(item["retrieval_rank"]),
            retrieval_score=float(item["retrieval_score"]),
            cif_path=str(item["cif_path"]), cif_sha256=str(item["cif_sha256"]),
            inclusion_reason=str(item["inclusion_reason"]),
            species_pairs_contributed=tuple(item.get("species_pairs_contributed", ())),
            source_id=item.get("source_id"), family=item.get("family"),
        )
        for item in payload["selected"]
    )
    return SPPEvidenceBundle(
        corpus_id=str(payload["corpus_id"]), corpus_hash=str(payload["corpus_hash"]),
        selection_policy=str(payload["selection_policy"]),
        required_pairs=tuple(payload["required_pairs"]),
        pair_structure_counts={str(key): int(value) for key, value in payload["pair_structure_counts"].items()},
        pair_evidence_status=dict(payload["pair_evidence_status"]), selected=items,
        exclusion_audit=tuple(payload["exclusion_audit"]), bundle_hash=str(payload["bundle_hash"]),
    )


def _controlled_input_manifest(
    *, row: Any, primary_row_root: Path, dynamic_cell: Mapping[str, Any],
    evidence: SPPEvidenceBundle, freeze: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "paper1_spp_ablation_controlled_input.v1",
        "condition": CONDITION, "row_id": row.row_id,
        "request_spp_mode": "disabled",
        "primary_row_root": str(primary_row_root.resolve()),
        "primary_candidate_sha256": (
            sha256_file(primary_row_root / "generated" / "candidate.cif")
            if (primary_row_root / "generated" / "candidate.cif").is_file() else None
        ),
        "dynamic_cell": dict(dynamic_cell),
        "dynamic_cell_sha256": sha256_file(primary_row_root / "cell" / "dynamic_cell.json"),
        "evidence_bundle_hash": evidence.bundle_hash,
        "target_reference_id": row.effective_config["target_reference_id"],
        "excluded_structure_ids": [row.effective_config["target_reference_id"]],
        "grid_density": row.effective_config["grid_density"],
        "solver_time_limit_s": row.effective_config["solver_time_limit_s"],
        "solver_threads": row.effective_config["solver_threads"],
        "solver_mip_gap": row.effective_config["solver_mip_gap"],
        "random_seed": row.effective_config["random_seed"],
        "proximity_scale": row.effective_config["proximity_scale"],
        "freeze_payload_sha256": freeze["freeze_payload_sha256"],
    }


def execute(
    *, benchmark_csv: Path, freeze_manifest: Path, primary_root: Path,
    output_root: Path, resume: bool,
) -> dict[str, Any]:
    freeze = read_json(freeze_manifest)
    if freeze["conditions"][CONDITION]["request_spp_mode"] != "disabled":
        raise ValueError("frozen condition B is not request_spp_mode=disabled")
    roots = ComponentRoots.load(REPO_ROOT)
    roots.activate_imports(include_sca=False)
    from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages

    stages = ProductionWorkflowStages()
    rows = validate_csv(benchmark_csv, load_workflow_config(), stages=stages)
    by_id = {row.row_id: row for row in rows}
    selected_ids = [str(item["row_id"]) for item in freeze["targets"]]
    missing = sorted(set(selected_ids) - set(by_id))
    if missing:
        raise ValueError(f"ablation targets absent from benchmark CSV: {missing}")
    if output_root.exists() and not resume:
        raise FileExistsError(f"ablation output exists; use --resume: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    write_json(output_root / "run_config.json", {
        "schema_version": "paper1_spp_ablation_run.v1", "condition": CONDITION,
        "freeze_manifest": str(freeze_manifest.resolve()),
        "freeze_manifest_sha256": sha256_file(freeze_manifest),
        "benchmark_csv": str(benchmark_csv.resolve()),
        "benchmark_csv_sha256": sha256_file(benchmark_csv),
        "selected_rows": selected_ids,
    })
    results: list[dict[str, Any]] = []
    for row_id in selected_ids:
        row = by_id[row_id]
        row_root = output_root / row_id
        status_path = row_root / "status.json"
        if status_path.is_file():
            existing = read_json(status_path)
            if existing.get("state") in {"GENERATED", "SCIENTIFIC_FAILURE", "TECHNICAL_FAILURE"}:
                results.append(existing)
                continue
        primary_row = primary_root / row_id
        dynamic_cell_path = primary_row / "cell" / "dynamic_cell.json"
        if not dynamic_cell_path.is_file():
            state = {
                "row_id": row_id, "condition": CONDITION, "state": "SCIENTIFIC_FAILURE",
                "scientific_attempt_count": 0, "technical_attempt_count": 0,
                "error_type": "ControlledInputUnavailable",
                "error_code": "PRIMARY_PREFLIGHT_NO_DYNAMIC_CELL",
                "error": "Primary frozen row did not pass preflight and has no dynamic-cell control artifact.",
            }
            write_json(status_path, state)
            results.append(state)
            continue
        retrieval = read_json(primary_row / "retrieval" / "retrieval_manifest.json")
        evidence = evidence_from_dict(retrieval["spp_evidence"])
        dynamic_cell = read_json(dynamic_cell_path)
        config = replace(
            _workflow_config(row, row_root, roots),
            request_spp_mode="disabled", run_id=f"paper1-ablation-global-{row_id}",
            attempt_id="global_regulator_only", qlip_runtime_root=row_root,
        )
        input_manifest = _controlled_input_manifest(
            row=row, primary_row_root=primary_row, dynamic_cell=dynamic_cell,
            evidence=evidence, freeze=freeze,
        )
        write_json(row_root / "input_manifest.json", input_manifest)
        state: dict[str, Any] = {
            "row_id": row_id, "condition": CONDITION, "state": "RUNNING",
            "scientific_attempt_count": 1, "technical_attempt_count": 0,
        }
        write_json(status_path, state)
        started = time.perf_counter()
        try:
            request_spp = stages.fit_request_spp(
                evidence, row.structured_task, config, row_root / "spp" / "build",
            )
            request_spp["dynamic_cell"] = dynamic_cell
            write_json(row_root / "spp" / "request_spp.json", request_spp)
            solved = stages.solve(row.structured_task, request_spp, config, row_root / "qlip")
            generated = row_root / "generated"
            generated.mkdir(parents=True, exist_ok=True)
            candidate = generated / "candidate.cif"
            if candidate.exists():
                raise FileExistsError(f"refusing to overwrite ablation candidate: {candidate}")
            shutil.copy2(Path(solved["cif_path"]), candidate)
            state.update({
                "state": "GENERATED", "solver_status": str(solved["status"]),
                "solver_objective": float(solved["solver_objective"]),
                "runtime_s": time.perf_counter() - started,
                "candidate_path": str(candidate.resolve()), "candidate_sha256": sha256_file(candidate),
                "qlip_adapter": solved.get("qlip_adapter", {}),
                "search_space": solved.get("search_space", {}),
                "solver_summary": solved.get("solver_summary", {}),
            })
        except Exception as exc:
            code = str(getattr(exc, "code", ""))
            scientific = is_scientific_failure(code)
            state.update({
                "state": "SCIENTIFIC_FAILURE" if scientific else "TECHNICAL_FAILURE",
                "technical_attempt_count": 0 if scientific else 1,
                "error_type": type(exc).__name__, "error": str(exc), "error_code": code,
                "runtime_s": time.perf_counter() - started,
            })
        write_json(status_path, state)
        results.append(state)
    counts: dict[str, int] = {}
    for result in results:
        key = str(result["state"])
        counts[key] = counts.get(key, 0) + 1
    summary = {"condition": CONDITION, "selected_count": len(selected_ids), "counts": counts, "rows": results}
    write_json(output_root / "last_command_result.json", summary)
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--benchmark-csv", type=Path, default=root / "benchmark_paper1_simple_ordered_v1.csv")
    parser.add_argument(
        "--freeze-manifest", type=Path,
        default=root / "artifacts" / "paper1_spp_positive_domain" / "ablation_freeze_v1" / "FROZEN_SPP_ABLATION_MANIFEST.json",
    )
    parser.add_argument("--primary-root", type=Path, default=root / "outputs" / "paper1_simple_ordered_v1")
    parser.add_argument("--output-root", type=Path, default=root / "outputs" / "paper1_spp_ablation_v1" / "global_regulator_only")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = execute(
        benchmark_csv=args.benchmark_csv.resolve(), freeze_manifest=args.freeze_manifest.resolve(),
        primary_root=args.primary_root.resolve(), output_root=args.output_root.resolve(), resume=args.resume,
    )
    print(json.dumps(result["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
