"""Run the existing SCA evaluator separately over condition-B ablation candidates.

This mirrors ``sok_llm_orchestrator.workflow.csv_workflow._sca_one`` so that the
global-regulator-only (condition B) candidates are scored with exactly the same
raw-field mapping and ``sca_status`` rule as the primary condition-C benchmark.
No QLIP generation is performed; this is a read-only structural evaluation of
already-persisted ``generated/candidate.cif`` files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from sok_llm_orchestrator.workflow.component_paths import ComponentRoots
from sok_llm_orchestrator.workflow.csv_workflow import REPO_ROOT

SUMMARY_FIELDS = (
    "row_id",
    "sca_status",
    "source_candidate_sha256",
    "parse_ok",
    "composition_match",
    "detected_space_group",
    "requested_space_group",
    "space_group_match",
    "topology_result",
    "topology_policy",
    "geometry_valid",
    "bad_contacts",
    "minimum_distance_angstrom",
    "structure_match_result",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def summarize_sca(row_id: str, candidate_hash: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Map a raw SCA result to the canonical primary-benchmark summary.

    Field mapping and the ``sca_status`` rule are copied verbatim from
    ``csv_workflow._sca_one`` so condition B and condition C are scored identically.
    """
    parse = bool(raw.get("parse_ok"))
    composition = bool(raw.get("target_formula_match"))
    geometry = raw.get("geometry_ok") is True
    contacts = int(raw.get("num_bad_contacts") or 0)
    topology = str(raw.get("topology_status") or "NOT_EVALUATED")
    outcome = (
        "PASS"
        if parse and composition and geometry and contacts == 0 and topology in {"PASS", "NOT_EVALUATED"}
        else "PARTIAL"
        if parse and composition
        else "FAIL"
    )
    return {
        "row_id": row_id,
        "sca_status": outcome,
        "source_candidate_sha256": candidate_hash,
        "candidate_sha256_after": candidate_hash,
        "parse_ok": raw.get("parse_ok"),
        "composition_match": raw.get("target_formula_match"),
        "detected_space_group": raw.get("detected_space_group"),
        "requested_space_group": raw.get("target_space_group"),
        "space_group_match": raw.get("space_group_consistent"),
        "topology_result": topology,
        "topology_policy": raw.get("topology_policy"),
        "topology_details": raw.get("topology_details"),
        "geometry_valid": raw.get("geometry_ok"),
        "bad_contacts": contacts,
        "minimum_distance_angstrom": raw.get("min_distance"),
        "structure_match_result": raw.get("novel_by_structure_matcher"),
    }


def evaluate(
    *, freeze_manifest: Path, primary_root: Path, condition_root: Path, reuse_existing: bool = False
) -> dict[str, Any]:
    stages = None
    if not reuse_existing:
        roots = ComponentRoots.load(REPO_ROOT)
        roots.activate_imports(include_sca=True)
        from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages

        stages = ProductionWorkflowStages()

    freeze = read_json(freeze_manifest)
    rows: list[dict[str, Any]] = []
    for target in freeze["targets"]:
        row_id = str(target["row_id"])
        candidate = condition_root / row_id / "generated" / "candidate.cif"
        if not candidate.is_file():
            rows.append({"row_id": row_id, "sca_status": "SKIPPED_NO_CANDIDATE"})
            continue
        before = sha256_file(candidate)
        row_root = condition_root / row_id / "sca"
        result_path = row_root / "result.json"
        if reuse_existing:
            if not result_path.is_file():
                rows.append({"row_id": row_id, "sca_status": "SKIPPED_NO_CANDIDATE"})
                continue
            raw = read_json(result_path)
        else:
            assert stages is not None
            task = read_json(primary_root / row_id / "structured_task" / "structured_task.json")
            raw = stages.evaluate(candidate, task)
            after = sha256_file(candidate)
            if before != after:
                raise RuntimeError(f"SCA mutated ablation candidate: {row_id}")
            write_json(result_path, raw)
        summary = summarize_sca(row_id, before, raw)
        write_json(row_root / "summary.json", summary)
        rows.append(summary)

    output = {
        "schema_version": "paper1_spp_ablation_sca.v2",
        "condition": "B_GLOBAL_REGULATOR_ONLY",
        "reuse_existing": reuse_existing,
        "rows": rows,
    }
    write_json(condition_root / "SCA_RUN_SUMMARY.json", output)
    write_csv(condition_root / "SCA_RUN_SUMMARY.csv", rows, SUMMARY_FIELDS)
    return output


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--freeze-manifest",
        type=Path,
        default=root
        / "artifacts"
        / "paper1_spp_positive_domain"
        / "ablation_freeze_v1"
        / "FROZEN_SPP_ABLATION_MANIFEST.json",
    )
    parser.add_argument("--primary-root", type=Path, default=root / "outputs" / "paper1_simple_ordered_v1")
    parser.add_argument(
        "--condition-root",
        type=Path,
        default=root / "outputs" / "paper1_spp_ablation_v1" / "global_regulator_only",
    )
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="re-derive summaries from already-persisted sca/result.json without re-invoking SCA",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = evaluate(
        freeze_manifest=args.freeze_manifest.resolve(),
        primary_root=args.primary_root.resolve(),
        condition_root=args.condition_root.resolve(),
        reuse_existing=args.reuse_existing,
    )
    counts: dict[str, int] = {}
    for row in result["rows"]:
        status = str(row["sca_status"])
        counts[status] = counts.get(status, 0) + 1
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
