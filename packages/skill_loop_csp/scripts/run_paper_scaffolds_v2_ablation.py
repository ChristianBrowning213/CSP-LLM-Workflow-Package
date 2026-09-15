"""Run the frozen 12-row request-vs-global SPP ablation on scaffold v2.

The source retrieval and POT packages are immutable Result-D artifacts.  Each
discrete v2 geometry is submitted to unmodified QLIP as an independent solve;
the condition winner is the feasible, solver/scorer-verified SPP minimum.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
import hashlib
from itertools import combinations_with_replacement
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
from sok_llm_orchestrator.workflow.paper_scaffolds_library_v2 import (  # noqa: E402
    ScaffoldAlternative,
    build_family_scaffold_alternatives,
    select_objective_minimum,
)
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages  # noqa: E402


SOURCE = REPO / "outputs" / "Paper_scaffolds_september" / "result_D_stress40"
GLOBAL = REPO / "outputs" / "Paper_scaffolds_september" / "result_D_ablation_global_only"
ARTIFACT = REPO / "artifacts" / "Paper_scaffolds_september" / "scaffold_v2" / "spp_ablation"
OUTPUT = REPO / "outputs" / "Paper_scaffolds_september" / "scaffold_v2_ablation"
PANEL = (
    "S01_SP_Zn_SbO2_2", "S06_SP_MgMn2O4", "S10_SP_Al2NiO4",
    "S11_LY_LiCuO2", "S12_LY_NaCuO2", "S13_LY_NaNiO2",
    "S21_OL_LiMnVO4", "S28_OL_LiMgAsO4", "S29_OL_NaCdPO4",
    "S31_RS_EuS", "S37_RS_MgO", "S39_RS_ZrN",
)
CONDITIONS = {"request": SOURCE, "global": GLOBAL}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_records(row_root: Path) -> list[dict[str, Any]]:
    manifest = _json(row_root / "retrieval" / "retrieval_manifest.json")
    records = []
    for item in manifest["selected"]:
        relative = item.get("portable_cif_path")
        cif = row_root / str(relative) if relative else Path(item["cif_export"]["path"])
        structure = Structure.from_file(cif)
        records.append({
            "structure_id": item["structure_id"],
            "formula": structure.composition.reduced_formula,
            "vpa_A3_per_atom": structure.volume / len(structure),
        })
    return records


def freeze_panel() -> None:
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT / "SPP_V2_ABLATION_PANEL_FREEZE.json"
    if path.exists():
        return
    rows = []
    for row_id in PANEL:
        source = SOURCE / row_id
        global_root = GLOBAL / row_id
        task_path = source / "structured_task" / "structured_task.json"
        request_cache = source / "spp" / "request_spp_cache.json"
        global_cache = global_root / "spp" / "request_spp_cache.json"
        for required in (task_path, request_cache, global_cache):
            if not required.is_file():
                raise FileNotFoundError(required)
        task = _json(task_path)
        rows.append({
            "row_id": row_id,
            "formula": task["formula"],
            "family": task["family"],
            "task_sha256": _sha(task_path),
            "request_spp_cache_sha256": _sha(request_cache),
            "global_spp_cache_sha256": _sha(global_cache),
        })
    payload = {
        "schema_version": "paper_scaffolds_v2_ablation_panel.v1",
        "created_at": _now(),
        "selected_before_v2_generation": not OUTPUT.exists(),
        "zero_objective_condition": "NOT_RUN_NO_EXISTING_SCIENTIFICALLY_VALID_MODE",
        "rows": rows,
    }
    if not payload["selected_before_v2_generation"]:
        raise RuntimeError("refusing to freeze panel after v2 output exists")
    _write_json(path, payload)


class V2Stages(ProductionWorkflowStages):
    alternative: ScaffoldAlternative | None = None

    def _scaffold(self, task, config=None):  # noqa: ANN001
        if self.alternative is None:
            raise RuntimeError("v2 alternative was not selected")
        item = self.alternative
        return item.scaffold_id, item.structure.copy(), [dict(orbit) for orbit in item.ordered_orbits]


def _parsed_rows(stages: ProductionWorkflowStages) -> dict[str, Any]:
    workflow = cw.load_workflow_config()
    return {row.row_id: row for row in cw.validate_csv(SOURCE / "input.csv", workflow, stages=stages)}


def run(selected_rows: tuple[str, ...] = PANEL, selected_conditions: tuple[str, ...] = tuple(CONDITIONS)) -> None:
    freeze_panel()
    roots = ComponentRoots.load(REPO)
    roots.activate_imports(include_sca=True)
    stages = V2Stages()
    parsed = _parsed_rows(stages)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for row_id in selected_rows:
        task = _json(SOURCE / row_id / "structured_task" / "structured_task.json")
        alternatives = build_family_scaffold_alternatives(task, evidence_records=_evidence_records(SOURCE / row_id))
        for condition in selected_conditions:
            condition_root = CONDITIONS[condition]
            result_path = OUTPUT / row_id / condition / "result.json"
            if result_path.is_file():
                print(f"SKIP {row_id} {condition}")
                continue
            condition_dir = OUTPUT / row_id / condition
            request_spp = _json(condition_root / row_id / "spp" / "request_spp_cache.json")
            rows = []
            for alternative in alternatives:
                stages.alternative = alternative
                solve_root = condition_dir / "alternatives" / alternative.alternative_id / "qlip"
                metrics_path = solve_root.parent / "metrics.json"
                if metrics_path.is_file():
                    rows.append(_json(metrics_path))
                    print(f"SKIP {row_id} {condition} {alternative.alternative_id}")
                    continue
                config = cw._workflow_config(parsed[row_id], solve_root, roots)
                config = replace(
                    config,
                    output_root=solve_root,
                    qlip_runtime_root=REPO / "outputs",
                    run_id=f"scaffold-v2-{row_id}-{condition}-{alternative.alternative_id}",
                    attempt_id="v2_ablation",
                    request_spp_mode="disabled" if condition == "global" else "enabled",
                    native_qlip=False,
                    scaffold_mode="loose",
                    scaffold_dir=None,
                    cell_mode="native",
                    native_grid_density=None,
                )
                started = time.perf_counter()
                solved = stages.solve(task, request_spp, config, solve_root)
                runtime = time.perf_counter() - started
                components = asdict(solved["components"]) if is_dataclass(solved["components"]) else dict(solved["components"])
                independent = float(components["solver_objective"])
                solver_objective = float(solved["solver_objective"])
                if abs(solver_objective - independent) > 1e-6:
                    raise RuntimeError(f"solver/scorer mismatch: {row_id}/{condition}/{alternative.alternative_id}")
                cif = Path(solved["cif_path"])
                record = {
                    "alternative_id": alternative.alternative_id,
                    "scaffold_id": alternative.scaffold_id,
                    "geometry_class": alternative.geometry_class,
                    "vpa_A3_per_atom": alternative.provenance["vpa_A3_per_atom"],
                    "internal_parameter": alternative.provenance["internal_parameter"],
                    "feasible_state_count": alternative.feasible_state_count,
                    "solver_status": solved["status"],
                    "solver_objective": solver_objective,
                    "independent_objective": independent,
                    "runtime_s": runtime,
                    "cif_path": str(cif),
                    "cif_sha256": _sha(cif),
                    "components": components,
                }
                _write_json(metrics_path, record)
                rows.append(record)
                print(f"{row_id} {condition} {alternative.alternative_id}: {solved['status']} {solver_objective:.6g}")
            winner = dict(select_objective_minimum(rows))
            selected_dir = condition_dir / "selected"
            selected_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(winner["cif_path"], selected_dir / "candidate.cif")
            winner["selected_cif_path"] = str(selected_dir / "candidate.cif")
            winner["selected_cif_sha256"] = _sha(selected_dir / "candidate.cif")
            _write_json(result_path, {
                "schema_version": "paper_scaffolds_v2_condition_result.v1",
                "row_id": row_id,
                "formula": task["formula"],
                "family": task["family"],
                "condition": condition,
                "alternative_count": len(alternatives),
                "winner": winner,
                "alternatives": rows,
            })
    if all((OUTPUT / row_id / condition / "result.json").is_file() for row_id in PANEL for condition in CONDITIONS):
        summarize()


def summarize() -> None:
    from qlip.interactions.spp import SPPCollection

    def score(cif_path: str, cache: dict[str, Any], condition: str) -> float:
        species = [str(element) for element in Structure.from_file(cif_path).composition.elements]
        pairs = list(combinations_with_replacement(species, 2))
        root = cache["regulator_root"] if condition == "global" else cache["pot_root"]
        weight = 20.0 if condition == "global" else 10.0
        collection = SPPCollection(root, cutoff=10.0, missing_pair_policy="block")
        collection.load(pairs)
        structure = Structure.from_file(cif_path)
        atoms = structure.to_ase_atoms()
        return weight * float(collection.score(atoms.get_chemical_symbols(), atoms.positions, atoms.cell.array))

    rows = []
    for row_id in PANEL:
        request = _json(OUTPUT / row_id / "request" / "result.json")
        global_only = _json(OUTPUT / row_id / "global" / "result.json")
        left, right = request["winner"], global_only["winner"]
        request_cache = _json(SOURCE / row_id / "spp" / "request_spp_cache.json")
        global_cache = _json(GLOBAL / row_id / "spp" / "request_spp_cache.json")
        global_under_request = score(right["selected_cif_path"], request_cache, "request")
        request_under_global = score(left["selected_cif_path"], global_cache, "global")
        rows.append({
            "row_id": row_id,
            "family": request["family"],
            "formula": request["formula"],
            "v2_alternative_count": request["alternative_count"],
            "feasible_states_per_geometry": left["feasible_state_count"],
            "request_alternative": left["alternative_id"],
            "global_alternative": right["alternative_id"],
            "request_objective": left["solver_objective"],
            "global_selection_rescored_request_objective": global_under_request,
            "request_objective_improvement": global_under_request - float(left["solver_objective"]),
            "global_objective_under_global_spp": right["solver_objective"],
            "request_selection_rescored_global_objective": request_under_global,
            "request_solver_status": left["solver_status"],
            "global_solver_status": right["solver_status"],
            "request_runtime_s": left["runtime_s"],
            "global_runtime_s": right["runtime_s"],
            "same_selected_cif": left["selected_cif_sha256"] == right["selected_cif_sha256"],
        })
    path = ARTIFACT / "SPP_V2_ABLATION_RESULTS.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _write_json(ARTIFACT / "SPP_V2_ABLATION_RESULTS.json", rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--rows", default="")
    parser.add_argument("--conditions", default="")
    args = parser.parse_args()
    freeze_panel()
    if not args.freeze_only:
        rows = tuple(value for value in args.rows.split(",") if value) or PANEL
        conditions = tuple(value for value in args.conditions.split(",") if value) or tuple(CONDITIONS)
        unknown_rows = set(rows) - set(PANEL)
        unknown_conditions = set(conditions) - set(CONDITIONS)
        if unknown_rows or unknown_conditions:
            raise ValueError(f"unknown rows/conditions: {sorted(unknown_rows)}, {sorted(unknown_conditions)}")
        run(rows, conditions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
