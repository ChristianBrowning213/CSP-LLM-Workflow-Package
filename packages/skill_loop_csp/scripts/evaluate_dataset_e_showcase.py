"""Apply frozen pre/post topology validation and finalize Dataset E tables."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from pymatgen.core import Composition, Structure


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sok_llm_orchestrator.workflow.dataset_e_validation import (  # noqa: E402
    validate_dataset_e_topology,
)


ARTIFACT = REPO / "artifacts" / "Paper_scaffolds_september" / "Dataset_E_complex_topology_showcase"
OUTPUT = REPO / "outputs" / "Paper_scaffolds_september" / "Dataset_E_complex_topology_showcase"
ROSTER = ARTIFACT / "FINAL_SHOWCASE_ROSTER.csv"
ROSTER_FREEZE = ARTIFACT / "FINAL_SHOWCASE_ROSTER_FREEZE.json"
VALIDATION_FREEZE = ARTIFACT / "VALIDATION_METHOD_FREEZE.json"
PRE_RESULTS = ARTIFACT / "PRE_TOPOLOGY_VALIDATION.json"
CHGNET_INPUT = ARTIFACT / "CHGNET_INPUT.csv"
CHGNET_OUTPUT = OUTPUT / "chgnet"
CHGNET_RESULTS = CHGNET_OUTPUT / "SCAFFOLD_CHGNET_RESULTS.csv"
PROTOCOL_ID = "chgnet_0.4.2_fire_fmax0.1_steps200_cell_v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_roster() -> list[dict[str, str]]:
    freeze = read_json(ROSTER_FREEZE)
    if sha256(ROSTER) != freeze["roster_sha256"]:
        raise RuntimeError("Dataset E roster hash mismatch")
    rows = read_csv(ROSTER)
    if len(rows) != int(freeze["row_count"]):
        raise RuntimeError("Dataset E denominator mismatch")
    return rows


def pre_validate() -> list[dict[str, Any]]:
    rows = []
    chgnet = []
    for frozen in load_roster():
        result = read_json(OUTPUT / frozen["row_id"] / "dataset_e_result.json")
        base = {
            "row_id": frozen["row_id"],
            "family": frozen["family"],
            "subtype": frozen["subtype"],
            "formula": frozen["formula"],
            "generated": bool(result["generated"]),
        }
        if not result["generated"]:
            rows.append(
                base
                | {
                    "exact_composition": False,
                    "ordered": False,
                    "pre_topology_status": "FAIL",
                    "pre_topology_details": {"reason": "NO_GENERATED_CANDIDATE"},
                }
            )
            continue
        cif = Path(result["winner"]["selected_cif_path"])
        structure = Structure.from_file(cif)
        exact = (
            structure.composition.reduced_composition
            == Composition(frozen["formula"]).reduced_composition
        )
        topology = validate_dataset_e_topology(structure, frozen["subtype"])
        status = "PASS" if exact and structure.is_ordered and topology["status"] == "PASS" else "FAIL"
        row = base | {
            "generated_cif": str(cif.resolve()),
            "generated_cif_sha256": sha256(cif),
            "exact_composition": exact,
            "ordered": bool(structure.is_ordered),
            "pre_topology_status": status,
            "pre_topology_details": topology,
        }
        rows.append(row)
        if status == "PASS":
            chgnet.append(
                {
                    "row_id": frozen["row_id"],
                    "formula": frozen["formula"],
                    "cif_path": str(cif.resolve()),
                    "cif_sha256": sha256(cif),
                    "protocol_id": PROTOCOL_ID,
                }
            )
    write_json(PRE_RESULTS, rows)
    write_csv(CHGNET_INPUT, chgnet)
    write_json(
        ARTIFACT / "CHGNET_INPUT_FREEZE.json",
        {
            "schema_version": "dataset_e.chgnet_input_freeze.v1",
            "selected_rule": "generated AND exact composition AND ordered AND frozen pre-topology PASS",
            "row_count": len(chgnet),
            "input_sha256": sha256(CHGNET_INPUT),
            "validation_method_freeze_sha256": sha256(VALIDATION_FREEZE),
            "protocol_id": PROTOCOL_ID,
        },
    )
    print(json.dumps({"pre_status": Counter(row["pre_topology_status"] for row in rows), "chgnet_rows": len(chgnet)}, default=dict))
    return rows


def finalize() -> list[dict[str, Any]]:
    pre = {row["row_id"]: row for row in read_json(PRE_RESULTS)}
    chgnet = {row["row_id"]: row for row in read_csv(CHGNET_RESULTS)}
    final_rows = []
    for frozen in load_roster():
        row_id = frozen["row_id"]
        result = read_json(OUTPUT / row_id / "dataset_e_result.json")
        initial = pre[row_id]
        relaxation = chgnet.get(row_id)
        post_status = "NOT_RUN"
        post_details: dict[str, Any] = {"reason": "PRE_TOPOLOGY_NOT_PASS"}
        relaxed_cif = ""
        if relaxation and relaxation["chgnet_status"] == "PASS":
            relaxed_cif = relaxation["relaxed_cif_path"]
            post_details = validate_dataset_e_topology(
                Structure.from_file(relaxed_cif), frozen["subtype"]
            )
            post_status = str(post_details["status"])
        winner = result.get("winner") or {}
        preflight = result.get("preflight") or read_json(OUTPUT / row_id / "dataset_e_preflight_audit.json")
        final_rows.append(
            {
                "row_id": row_id,
                "family": frozen["family"],
                "subtype": frozen["subtype"],
                "formula": frozen["formula"],
                "request": frozen["request"],
                "target_reference_id": frozen["target_reference_id"],
                "target_reference_excluded": result["target_reference_excluded"],
                "retrieval_count": preflight["spp_evidence_count"],
                "pair_coverage": "PASS" if preflight["all_required_pairs_guided"] else "FAIL",
                "local_pair_missing_count": len(preflight["local_pair_missing"]),
                "regulator_fallback_pair_count": preflight["regulator_fallback_pair_count"],
                "scaffold_version": "dataset_e.complex_ordered_scaffolds.v1",
                "scaffold_alternative_count": result["alternative_count"],
                "feasible_alternative_count": result.get("feasible_alternative_count", 0),
                "solver_status": winner.get("solver_status", result.get("solver_status", "")),
                "solver_runtime_s": sum(float(item["runtime_s"]) for item in result.get("alternatives", [])),
                "selected_scaffold_alternative": winner.get("alternative_id", ""),
                "generated": result["generated"],
                "exact_composition": initial["exact_composition"],
                "ordered": initial["ordered"],
                "pre_topology_status": initial["pre_topology_status"],
                "pre_topology_details": initial["pre_topology_details"],
                "chgnet_status": relaxation["chgnet_status"] if relaxation else "NOT_RUN",
                "chgnet_converged": relaxation["converged"] if relaxation else False,
                "pre_volume_A3": relaxation.get("initial_volume", "") if relaxation else "",
                "post_volume_A3": relaxation.get("relaxed_volume", "") if relaxation else "",
                "volume_change_percent": relaxation.get("volume_change_percent", "") if relaxation else "",
                "post_topology_status": post_status,
                "post_topology_details": post_details,
                "generated_cif": winner.get("selected_cif_path", ""),
                "relaxed_cif": relaxed_cif,
                "notes": "no replacement; CHGNet is structural QC, not thermodynamic stability",
            }
        )
    write_csv(ARTIFACT / "FINAL_DATASET_E_RESULTS.csv", final_rows)
    write_json(ARTIFACT / "FINAL_DATASET_E_RESULTS.json", final_rows)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in final_rows:
        groups[row["subtype"]].append(row)
    report = [
        "# Dataset E complex-topology showcase",
        "",
        "This frozen 18-row experiment uses target-excluded specialist-corpus evidence, the unchanged paper SPP/QLIP objective, development-derived ordered topology scaffolds, and a validator frozen before final-target selection.",
        "",
        "CHGNet relaxation is structural quality control and is not a claim of thermodynamic stability.",
        "",
        "## Results by subtype",
        "",
        "| Subtype | N | Generated | OPTIMAL | Pre PASS | CHGNet converged | Post PASS |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for subtype, items in groups.items():
        report.append(
            f"| {subtype} | {len(items)} | {sum(bool(row['generated']) for row in items)} | "
            f"{sum(row['solver_status'] == 'OPTIMAL' for row in items)} | "
            f"{sum(row['pre_topology_status'] == 'PASS' for row in items)} | "
            f"{sum(str(row['chgnet_converged']).lower() == 'true' for row in items)} | "
            f"{sum(row['post_topology_status'] == 'PASS' for row in items)} |"
        )
    report.extend(
        [
            "",
            "## Claim-safe totals",
            "",
            f"- Generation: {sum(bool(row['generated']) for row in final_rows)}/{len(final_rows)}.",
            f"- Exact composition: {sum(bool(row['exact_composition']) for row in final_rows)}/{len(final_rows)}.",
            f"- Solver OPTIMAL: {sum(row['solver_status'] == 'OPTIMAL' for row in final_rows)}/{len(final_rows)}.",
            f"- Pre-relax topology PASS: {sum(row['pre_topology_status'] == 'PASS' for row in final_rows)}/{len(final_rows)}.",
            f"- CHGNet convergence: {sum(str(row['chgnet_converged']).lower() == 'true' for row in final_rows)}/{len(final_rows)}.",
            f"- Post-relax topology PASS: {sum(row['post_topology_status'] == 'PASS' for row in final_rows)}/{len(final_rows)}.",
            "",
            "No PARTIAL verdict is merged into PASS; no failed row was replaced; the denominator remained fixed.",
        ]
    )
    (ARTIFACT / "FINAL_DATASET_E_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[-9:]))
    return final_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("pre", "finalize"))
    args = parser.parse_args()
    if args.phase == "pre":
        pre_validate()
    else:
        finalize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
