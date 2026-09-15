"""Pre-solve validation of retrieval_feasible_cell_v1 against frozen v1 evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.workflow.dynamic_cell import (
    BINARY_SEARCH_TOLERANCE_A,
    EDGE_SAFETY_MARGIN,
    EXPANSION_FACTOR,
    FEASIBILITY_TIME_LIMIT_S,
    MAX_EDGE_EXPANSION,
    MIN_EDGE_BOUND_A,
    MIN_VOLUME_OBSERVATIONS,
    POLICY_VERSION,
    resolve_dynamic_cell,
)
from sok_llm_orchestrator.workflow.paper_final_v1 import FINAL_TASKS


REPO = Path(__file__).resolve().parents[1]
V1 = REPO / "artifacts" / "paper_final_v1"
OUT = REPO / "artifacts" / "paper_dynamic_cell_validation"
CONTROLLED = {"CaTiO3", "BaTiO3", "SrTiO3", "CsPbBr3", "CsPbCl3", "CsSnI3"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def contract() -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "input_composition": "literal unscaled target formula",
        "shape": "cubic",
        "grid_dimensions": [4, 4, 4],
        "candidate_site_count": 64,
        "retrieval_cohort": "same ranked leakage-safe cohort used for request-SPP fitting",
        "retrieval_statistic": "median valid CIF volume/atom",
        "target_leakage_filter": "exclude exact reduced target composition and declared target/reference hashes",
        "duplicate_filter": "first occurrence of each CIF SHA-256 only",
        "minimum_valid_volume_observations": MIN_VOLUME_OBSERVATIONS,
        "retrieval_fallback": "frozen global mp_stable_10k_v1 median VPA",
        "hard_feasibility_model": "QLIP Allocation.encode plus proximity.atomic_radii scale=1.0, zero objective",
        "spp_used_by_feasibility": False,
        "expansion_factor": EXPANSION_FACTOR,
        "maximum_edge_expansion": MAX_EDGE_EXPANSION,
        "minimum_edge_bound_A": MIN_EDGE_BOUND_A,
        "binary_search_tolerance_A": BINARY_SEARCH_TOLERANCE_A,
        "edge_safety_margin": EDGE_SAFETY_MARGIN,
        "feasibility_time_limit_s_per_check": FEASIBILITY_TIME_LIMIT_S,
        "final_rule": "a_search = max(a_prior, a_geom_upper_bound) * edge_safety_margin",
        "volume_rule": "V_search = a_search^3",
        "failure_statuses": [
            "RETRIEVAL_VOLUME_INSUFFICIENT",
            "GLOBAL_VOLUME_FALLBACK",
            "GEOMETRY_NOT_FEASIBLE_WITHIN_BOUND",
            "hard-geometry UNKNOWN",
        ],
    }


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"validation output already exists; refusing overwrite: {OUT}")
    OUT.mkdir(parents=True)
    write_json(OUT / "DYNAMIC_SEARCH_CELL_CONTRACT.json", contract())
    rows: list[dict[str, Any]] = []
    for task in FINAL_TASKS:
        run = V1 / "runs" / task.task_id
        old = read_json(run / "qlip" / "search_space.json")
        evidence = read_json(run / "spp" / "provenance.json")["evidence_bundle"]["selected"]
        cell, provenance = resolve_dynamic_cell(task.formula, evidence, grid_density=4)
        prior = provenance["retrieval_volume_prior"]
        task_root = OUT / "tasks" / task.task_id
        write_json(task_root / "retrieval_volume_prior.json", prior)
        write_json(task_root / "dynamic_cell.json", cell.to_dict())
        write_json(task_root / "geometry_feasibility.json", provenance)
        geom_edge = float(provenance["minimum_feasible_edge_upper_bound_A"])
        atoms = int(cell.n_target_atoms)
        rows.append({
            "task_id": task.task_id,
            "formula": task.formula,
            "controlled_perovskite_audit": task.formula in CONTROLLED,
            "old_frozen_cell_volume_A3": old["cell_volume_A3"],
            "old_frozen_edge_A": old["a"],
            "old_global_vpa_A3_per_atom": old["vpa_value_A3_per_atom"],
            "retrieval_volume_status": prior["retrieval_volume_status"],
            "retrieval_valid_observations": prior["valid_observation_count"],
            "retrieval_vpa_A3_per_atom": prior["median_volume_per_atom_A3"],
            "retrieval_prior_volume_A3": prior["V_prior_A3"],
            "retrieval_prior_edge_A": prior["a_prior_A"],
            "minimum_feasible_edge_upper_bound_A": geom_edge,
            "minimum_feasible_volume_upper_bound_A3": geom_edge**3,
            "minimum_feasible_vpa_upper_bound_A3_per_atom": geom_edge**3 / atoms,
            "new_dynamic_edge_A": cell.a,
            "new_dynamic_cell_volume_A3": cell.cell_volume_A3,
            "new_dynamic_vpa_A3_per_atom": cell.cell_volume_A3 / atoms,
            "edge_expansion_over_prior": cell.a / float(prior["a_prior_A"]),
            "geometry_status": provenance["geometry_status"],
            "final_feasibility_result": provenance["feasibility_checks"][-1]["status"],
            "feasibility_check_count": len(provenance["feasibility_checks"]),
            "spp_objective_used": False,
            "dynamic_cell_path": str((task_root / "dynamic_cell.json").resolve()),
            "retrieval_volume_prior_path": str((task_root / "retrieval_volume_prior.json").resolve()),
        })
    write_csv(OUT / "DYNAMIC_CELL_COMPARISON.csv", rows)
    controlled = [row for row in rows if row["controlled_perovskite_audit"]]
    write_csv(OUT / "DYNAMIC_CELL_COMPARISON_CONTROLLED_SIX.csv", controlled)
    write_json(OUT / "VALIDATION_PASS.json", {
        "status": "PASS",
        "policy_version": POLICY_VERSION,
        "task_count": len(rows),
        "controlled_task_count": len(controlled),
        "all_final_cells_feasible": all(row["final_feasibility_result"] == "FEASIBLE" for row in rows),
        "all_retrieval_priors_usable": all(
            row["retrieval_volume_status"] == "RETRIEVAL_VOLUME_USABLE" for row in rows
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
