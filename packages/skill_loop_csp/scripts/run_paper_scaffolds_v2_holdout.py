"""Run the hash-frozen unseen holdout through retrieval, SPP, v2, and QLIP."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, is_dataclass, replace
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any

from pymatgen.core import Structure


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sok_llm_orchestrator.workflow import csv_workflow as cw  # noqa: E402
from sok_llm_orchestrator.workflow.component_paths import ComponentRoots  # noqa: E402
from sok_llm_orchestrator.workflow.dynamic_cell import resolve_dynamic_cell  # noqa: E402
from sok_llm_orchestrator.workflow.paper_scaffolds_library_v2 import (  # noqa: E402
    ScaffoldAlternative,
    build_family_scaffold_alternatives,
    select_objective_minimum,
)
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages  # noqa: E402


ARTIFACT = REPO / "artifacts" / "Paper_scaffolds_september" / "scaffold_v2" / "final_holdout"
HOLDOUT = ARTIFACT / "V2_HOLDOUT.csv"
FREEZE = ARTIFACT / "V2_HOLDOUT_FREEZE.json"
INPUT = ARTIFACT / "V2_HOLDOUT_WORKFLOW_INPUT.csv"
OUTPUT = REPO / "outputs" / "Paper_scaffolds_september" / "scaffold_v2_holdout"
DATABASE = {"ROCKSALT": "rocksalt", "SPINEL": "spinel", "LAYERED_O3": "layered", "OLIVINE": "olivine"}
REQUEST = {
    "ROCKSALT": "Generate a plausible rocksalt crystal structure with composition {formula}.",
    "SPINEL": "Generate a plausible spinel oxide crystal structure with composition {formula}.",
    "LAYERED_O3": "Generate a plausible layered oxide O3 crystal structure with composition {formula}.",
    "OLIVINE": "Generate a plausible olivine crystal structure with composition {formula}.",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def load_holdout() -> list[dict[str, str]]:
    frozen = read_json(FREEZE)
    if sha(HOLDOUT) != frozen["holdout_sha256"]:
        raise RuntimeError("frozen holdout hash mismatch")
    with HOLDOUT.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != int(frozen["row_count"]):
        raise RuntimeError("frozen holdout row count mismatch")
    return rows


def prepare_input() -> None:
    rows = load_holdout()
    expected = [{
        "row_id": row["row_id"],
        "request_text": REQUEST[row["policy"]].format(formula=row["formula"]),
        "database": DATABASE[row["policy"]],
        "target_reference_id": row["target_reference_id"],
        "exclude_target_reference": "true",
        "notes": f"frozen_v2_holdout; policy={row['policy']}; no_replacement",
    } for row in rows]
    if INPUT.exists():
        with INPUT.open(newline="", encoding="utf-8") as handle:
            if list(csv.DictReader(handle)) != expected:
                raise RuntimeError("existing holdout workflow input differs from frozen derivation")
        return
    with INPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(expected[0]))
        writer.writeheader()
        writer.writerows(expected)
    write_json(ARTIFACT / "V2_HOLDOUT_WORKFLOW_INPUT_FREEZE.json", {
        "holdout_freeze_sha256": sha(FREEZE), "input_sha256": sha(INPUT),
        "derived_without_generation": not OUTPUT.exists(), "row_count": len(expected),
    })


def evidence_records(row_root: Path) -> list[dict[str, Any]]:
    manifest = read_json(row_root / "retrieval" / "retrieval_manifest.json")
    records = []
    for item in manifest["selected"]:
        cif = row_root / item["portable_cif_path"]
        structure = Structure.from_file(cif)
        records.append({
            "structure_id": item["structure_id"], "formula": structure.composition.reduced_formula,
            "vpa_A3_per_atom": structure.volume / len(structure),
        })
    return records


class V2Stages(ProductionWorkflowStages):
    alternative: ScaffoldAlternative | None = None

    def _scaffold(self, task, config=None):  # noqa: ANN001
        if self.alternative is None:
            raise RuntimeError("v2 alternative not selected")
        item = self.alternative
        return item.scaffold_id, item.structure.copy(), [dict(orbit) for orbit in item.ordered_orbits]


def run(policies: set[str], row_ids: set[str] | None = None) -> None:
    prepare_input()
    selected = {row["row_id"]: row for row in load_holdout()}
    roots = ComponentRoots.load(REPO)
    roots.activate_imports(include_sca=True)
    stages = V2Stages()
    workflow = cw.load_workflow_config()
    parsed = cw.validate_csv(INPUT, workflow, stages=ProductionWorkflowStages())
    for batch in parsed:
        frozen = selected[batch.row_id]
        if frozen["policy"] not in policies or (row_ids is not None and batch.row_id not in row_ids):
            continue
        row_root = OUTPUT / batch.row_id
        final_path = row_root / "v2_result.json"
        if final_path.is_file():
            print(f"SKIP {batch.row_id}")
            continue
        task = dict(batch.structured_task)
        task["formula"] = frozen["formula"]
        task["family"] = {"ROCKSALT": "rocksalt", "SPINEL": "spinel", "LAYERED_O3": "layered oxide", "OLIVINE": "olivine phosphate"}[frozen["policy"]]
        task["topology_subclass"] = "O3" if frozen["policy"] == "LAYERED_O3" else None
        provisional = build_family_scaffold_alternatives(task)
        stages.alternative = provisional[0]
        try:
            request_spp = cw._prepare_row(
                batch, row_root, roots, stages=stages, dynamic_resolver=resolve_dynamic_cell,
            )
            retrieval = read_json(row_root / "retrieval" / "retrieval_manifest.json")
            retrieved_ids = {str(item["structure_id"]) for item in retrieval["selected"]}
            evidence_bundle = read_json(row_root / "spp" / "provenance.json")["evidence_bundle"]
            evidence_ids = {str(item["structure_id"]) for item in evidence_bundle["selected"]}
            target_audit = [
                item for item in evidence_bundle["exclusion_audit"]
                if item["structure_id"] == frozen["target_reference_id"]
            ]
            if frozen["target_reference_id"] in evidence_ids or not any(
                item["decision"] == "excluded" and item["reason"] == "structure_holdout_id"
                for item in target_audit
            ):
                raise RuntimeError("TARGET_REFERENCE_LEAKAGE")
            alternatives = build_family_scaffold_alternatives(task, evidence_records=evidence_records(row_root))
            solved_rows = []
            for alternative in alternatives:
                stages.alternative = alternative
                metrics = row_root / "v2_alternatives" / alternative.alternative_id / "metrics.json"
                if metrics.is_file():
                    solved_rows.append(read_json(metrics))
                    print(f"SKIP {batch.row_id} {alternative.alternative_id}")
                    continue
                solve_root = metrics.parent / "qlip"
                config = cw._workflow_config(batch, solve_root, roots)
                config = replace(
                    config, output_root=solve_root, qlip_runtime_root=REPO / "outputs",
                    run_id=f"v2-holdout-{batch.row_id}-{alternative.alternative_id}",
                    attempt_id="v2_holdout", request_spp_mode="enabled", native_qlip=False,
                    scaffold_mode="loose", scaffold_dir=None, cell_mode="native", native_grid_density=None,
                )
                started = time.perf_counter()
                solved = stages.solve(task, request_spp, config, solve_root)
                runtime = time.perf_counter() - started
                components = asdict(solved["components"]) if is_dataclass(solved["components"]) else dict(solved["components"])
                record = {
                    "alternative_id": alternative.alternative_id, "scaffold_id": alternative.scaffold_id,
                    "geometry_class": alternative.geometry_class, "vpa_A3_per_atom": alternative.provenance["vpa_A3_per_atom"],
                    "internal_parameter": alternative.provenance["internal_parameter"],
                    "feasible_state_count": alternative.feasible_state_count,
                    "solver_status": solved["status"], "solver_objective": float(solved["solver_objective"]),
                    "independent_objective": float(components["solver_objective"]),
                    "objective_difference": abs(float(solved["solver_objective"]) - float(components["solver_objective"])),
                    "runtime_s": runtime, "cif_path": str(Path(solved["cif_path"]).resolve()),
                    "cif_sha256": sha(Path(solved["cif_path"])), "components": components,
                }
                if record["objective_difference"] > 1e-6:
                    raise RuntimeError("solver/scorer mismatch")
                write_json(metrics, record)
                solved_rows.append(record)
                print(f"{batch.row_id} {alternative.alternative_id}: {solved['status']} {record['solver_objective']:.6g}")
            winner = dict(select_objective_minimum(solved_rows))
            generated = row_root / "generated"
            generated.mkdir(parents=True, exist_ok=True)
            candidate = generated / "candidate.cif"
            if not candidate.exists():
                shutil.copy2(winner["cif_path"], candidate)
            winner["selected_cif_path"] = str(candidate.resolve())
            winner["selected_cif_sha256"] = sha(candidate)
            write_json(final_path, {
                "schema_version": "paper_scaffolds_v2_holdout_result.v1",
                "row_id": batch.row_id, "policy": frozen["policy"], "formula": frozen["formula"],
                "target_reference_id": frozen["target_reference_id"], "target_reference_excluded": True,
                "retrieved_ids": sorted(retrieved_ids), "retrieved_count": len(retrieved_ids),
                "spp_evidence_ids": sorted(evidence_ids), "spp_evidence_count": len(evidence_ids),
                "target_exclusion_audit": target_audit,
                "alternative_count": len(alternatives), "winner": winner, "alternatives": solved_rows,
            })
        except Exception as exc:
            write_json(row_root / "v2_failure.json", {
                "row_id": batch.row_id, "policy": frozen["policy"], "formula": frozen["formula"],
                "error_type": type(exc).__name__, "error": str(exc), "no_replacement": True,
            })
            print(f"FAILED {batch.row_id}: {type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--policies", default=",".join(DATABASE))
    parser.add_argument("--rows", default="")
    args = parser.parse_args()
    prepare_input()
    if not args.prepare_only:
        policies = {value for value in args.policies.split(",") if value}
        if policies - set(DATABASE):
            raise ValueError(f"unknown policies: {sorted(policies - set(DATABASE))}")
        row_ids = {value for value in args.rows.split(",") if value} or None
        run(policies, row_ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
