"""Run frozen Dataset E retrieval, SPP construction, and ordered QLIP generation."""

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

from pymatgen.core import Composition, Structure


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sok_llm_orchestrator.workflow import csv_workflow as cw  # noqa: E402
from sok_llm_orchestrator.workflow.cell_strategy import ResolvedCell, n_target_atoms  # noqa: E402
from sok_llm_orchestrator.workflow.component_paths import ComponentRoots  # noqa: E402
from sok_llm_orchestrator.workflow.dynamic_cell import retrieval_volume_prior  # noqa: E402
from sok_llm_orchestrator.workflow.paper_scaffolds_dataset_e import (  # noqa: E402
    ScaffoldAlternative,
    build_dataset_e_alternatives,
)
from sok_llm_orchestrator.workflow.paper_scaffolds_library_v2 import (  # noqa: E402
    select_objective_minimum,
)
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages  # noqa: E402


ARTIFACT = REPO / "artifacts" / "Paper_scaffolds_september" / "Dataset_E_complex_topology_showcase"
ROSTER = ARTIFACT / "FINAL_SHOWCASE_ROSTER.csv"
ROSTER_FREEZE = ARTIFACT / "FINAL_SHOWCASE_ROSTER_FREEZE.json"
METHOD_FREEZE = ARTIFACT / "METHOD_FREEZE.json"
INPUT = ARTIFACT / "FINAL_SHOWCASE_WORKFLOW_INPUT.csv"
OUTPUT = REPO / "outputs" / "Paper_scaffolds_september" / "Dataset_E_complex_topology_showcase"
DATABASE = {
    "NASICON": "nasicon",
    "RUDDLESDEN_POPPER": "ruddlesden_popper",
    "GARNET": "garnet",
    "ARGYRODITE": "argyrodite",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def workflow_formula(value: str) -> str:
    """Return an expanded, space-free formula without changing composition."""
    return Composition(value).reduced_composition.formula.replace(" ", "")


def ordered_scaffold_auxiliary_cell(
    formula: str,
    evidence_selected: Any,
    *,
    grid_density: int,
    proximity_scale: float,
) -> tuple[ResolvedCell, dict[str, Any]]:
    """Persist leakage-safe VPA provenance without probing an unused generic grid."""
    prior = retrieval_volume_prior(formula, evidence_selected)
    edge = float(prior["a_prior_A"])
    atoms = n_target_atoms(formula)
    provenance = {
        "policy_version": "dataset_e.ordered_scaffold_auxiliary_cell.v1",
        "scientific_role": "provenance_only_not_used_by_ordered_qlip_scaffold",
        "retrieval_volume_prior": prior,
        "generic_grid_feasibility_check": "NOT_APPLICABLE",
        "ordered_scaffold_lattice_policy": "METHOD_FREEZE.json geometry_policy",
        "proximity_scale": float(proximity_scale),
        "final_edge_A": edge,
        "final_volume_A3": edge**3,
        "final_volume_per_atom_A3": edge**3 / atoms,
        "final_status": "ORDERED_SCAFFOLD_AUXILIARY_ONLY",
    }
    return (
        ResolvedCell(
            cell_mode="dataset_e.ordered_scaffold_auxiliary_cell.v1",
            a=edge,
            b=edge,
            c=edge,
            alpha=90.0,
            beta=90.0,
            gamma=90.0,
            grid_density=grid_density,
            grid_spacing_A=edge / grid_density,
            n_target_atoms=atoms,
            vpa_source=str(prior["vpa_source"]),
            vpa_value=float(prior["median_volume_per_atom_A3"]),
            cell_volume_A3=edge**3,
            provenance=provenance,
        ),
        provenance,
    )


def load_roster() -> list[dict[str, str]]:
    freeze = read_json(ROSTER_FREEZE)
    if sha256(ROSTER) != freeze["roster_sha256"]:
        raise RuntimeError("Dataset E final roster hash mismatch")
    if sha256(METHOD_FREEZE) != freeze["method_freeze_sha256"]:
        raise RuntimeError("Dataset E frozen method hash mismatch")
    with ROSTER.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != int(freeze["row_count"]):
        raise RuntimeError("Dataset E frozen denominator mismatch")
    return rows


def prepare_input() -> None:
    expected = [
        {
            "row_id": row["row_id"],
            "request_text": row["request"],
            "database": DATABASE[row["family"]],
            "target_reference_id": row["target_reference_id"],
            "exclude_target_reference": "true",
            "notes": f"dataset_e_frozen; subtype={row['subtype']}; no_replacement",
        }
        for row in load_roster()
    ]
    if INPUT.exists():
        with INPUT.open(newline="", encoding="utf-8") as handle:
            if list(csv.DictReader(handle)) != expected:
                raise RuntimeError("existing Dataset E input differs from frozen roster derivation")
        return
    with INPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(expected[0]))
        writer.writeheader()
        writer.writerows(expected)
    write_json(
        ARTIFACT / "FINAL_SHOWCASE_WORKFLOW_INPUT_FREEZE.json",
        {
            "schema_version": "dataset_e.workflow_input_freeze.v1",
            "roster_freeze_sha256": sha256(ROSTER_FREEZE),
            "input_sha256": sha256(INPUT),
            "derived_before_generation": not OUTPUT.exists(),
            "row_count": len(expected),
        },
    )


def evidence_records(row_root: Path) -> list[dict[str, Any]]:
    manifest = read_json(row_root / "retrieval" / "retrieval_manifest.json")
    records = []
    for item in manifest["selected"]:
        cif = row_root / item["portable_cif_path"]
        if not cif.is_file():
            continue
        structure = Structure.from_file(cif)
        records.append(
            {
                "structure_id": item["structure_id"],
                "formula": structure.composition.reduced_formula,
                "vpa_A3_per_atom": structure.volume / len(structure),
            }
        )
    return records


def exclusion_and_coverage(row_root: Path, target_id: str) -> dict[str, Any]:
    provenance = read_json(row_root / "spp" / "provenance.json")["evidence_bundle"]
    selected_ids = {str(item["structure_id"]) for item in provenance["selected"]}
    target_audit = [
        item for item in provenance["exclusion_audit"] if item["structure_id"] == target_id
    ]
    explicit_exclusion = any(
        item["decision"] == "excluded" and item["reason"] == "structure_holdout_id"
        for item in target_audit
    )
    input_manifest = read_json(row_root / "spp" / "build" / "spp_input_manifest.json")
    exclusion_pass = (
        target_id not in selected_ids
        and target_id not in set(input_manifest["spp_input_structure_ids"])
        and bool(input_manifest["NO_TARGET_LEAKAGE"])
    )
    pair_status = provenance["pair_evidence_status"]
    locally_covered = sorted(
        pair for pair, status in pair_status.items() if status["local_evidence_present"]
    )
    locally_missing = sorted(set(pair_status) - set(locally_covered))
    request_spp = read_json(row_root / "spp" / "request_spp_cache.json")
    pair_results = request_spp["quality"]["request_pair_results"]
    guided_pairs = sorted(
        str(item["species_pair"])
        for item in pair_results
        if item.get("selected_pot_path") and item.get("guidance_mode") != "UNSUPPORTED_REQUIRED_PAIR"
    )
    unsupported_pairs = sorted(set(pair_status) - set(guided_pairs))
    result = {
        "target_reference_id": target_id,
        "target_reference_excluded": exclusion_pass,
        "exclusion_proof": (
            "explicit_structure_holdout_id_audit"
            if explicit_exclusion
            else "target_absent_from_ranked_evidence_and_spp_input_manifest"
        ),
        "target_exclusion_audit": target_audit,
        "spp_input_no_target_leakage": input_manifest["NO_TARGET_LEAKAGE"],
        "spp_evidence_ids": sorted(selected_ids),
        "spp_evidence_count": len(selected_ids),
        "required_pairs": sorted(pair_status),
        "local_pair_coverage": locally_covered,
        "local_pair_missing": locally_missing,
        "all_pairs_have_local_evidence": not locally_missing,
        "pair_guidance": pair_results,
        "guided_pairs": guided_pairs,
        "unsupported_pairs": unsupported_pairs,
        "all_required_pairs_guided": not unsupported_pairs,
        "request_supported_pair_count": request_spp["quality"][
            "request_supported_pair_count"
        ],
        "regulator_fallback_pair_count": request_spp["quality"][
            "regulator_fallback_pair_count"
        ],
        "bundle_hash": provenance["bundle_hash"],
    }
    if not exclusion_pass:
        raise RuntimeError(f"TARGET_REFERENCE_LEAKAGE: {target_id}")
    if unsupported_pairs:
        raise RuntimeError(f"GUIDANCE_PAIR_UNSUPPORTED: {', '.join(unsupported_pairs)}")
    return result


class DatasetEStages(ProductionWorkflowStages):
    alternative: ScaffoldAlternative | None = None

    def _scaffold(self, task, config=None):  # noqa: ANN001
        if self.alternative is None:
            raise RuntimeError("Dataset E scaffold alternative not selected")
        item = self.alternative
        return item.scaffold_id, item.structure.copy(), [dict(orbit) for orbit in item.ordered_orbits]


def prepare_all() -> tuple[list[Any], dict[str, dict[str, str]], ComponentRoots]:
    prepare_input()
    roster = {row["row_id"]: row for row in load_roster()}
    roots = ComponentRoots.load(REPO)
    roots.activate_imports(include_sca=True)
    workflow = cw.load_workflow_config()
    parsed = cw.validate_csv(INPUT, workflow, stages=ProductionWorkflowStages())
    parsed = [
        replace(
            batch,
            structured_task=dict(batch.structured_task)
            | {
                "formula": workflow_formula(roster[batch.row_id]["formula"]),
                "family": roster[batch.row_id]["family"],
                "topology_subclass": roster[batch.row_id]["subtype"],
                "prototype": None,
                "space_group": None,
                "normalisation": "dataset_e.frozen_roster.v1",
            },
        )
        for batch in parsed
    ]
    stages = DatasetEStages()
    coverage = []
    for batch in parsed:
        frozen = roster[batch.row_id]
        row_root = OUTPUT / batch.row_id
        if (row_root / "spp" / "provenance.json").is_file():
            print(f"SKIP PREFLIGHT {batch.row_id}")
        else:
            task = dict(batch.structured_task)
            task.update(
                formula=workflow_formula(frozen["formula"]),
                family=frozen["family"],
                topology_subclass=frozen["subtype"],
            )
            stages.alternative = build_dataset_e_alternatives(task)[0]
            cw._prepare_row(
                batch,
                row_root,
                roots,
                stages=stages,
                dynamic_resolver=ordered_scaffold_auxiliary_cell,
            )
            print(f"PREFLIGHT {batch.row_id}")
        audit = exclusion_and_coverage(row_root, frozen["target_reference_id"])
        audit.update(row_id=batch.row_id, family=frozen["family"], subtype=frozen["subtype"])
        write_json(row_root / "dataset_e_preflight_audit.json", audit)
        coverage.append(audit)
    write_json(ARTIFACT / "TARGET_EXCLUSION_AND_PAIR_COVERAGE_AUDIT.json", coverage)
    return parsed, roster, roots


def run(row_ids: set[str] | None = None) -> None:
    parsed, roster, roots = prepare_all()
    stages = DatasetEStages()
    for batch in parsed:
        if row_ids is not None and batch.row_id not in row_ids:
            continue
        frozen = roster[batch.row_id]
        row_root = OUTPUT / batch.row_id
        final_path = row_root / "dataset_e_result.json"
        if final_path.is_file():
            print(f"SKIP RESULT {batch.row_id}")
            continue
        task = dict(batch.structured_task)
        task.update(
            formula=workflow_formula(frozen["formula"]),
            family=frozen["family"],
            topology_subclass=frozen["subtype"],
        )
        request_spp = read_json(row_root / "spp" / "request_spp_cache.json")
        alternatives = build_dataset_e_alternatives(
            task, evidence_records=evidence_records(row_root)
        )
        solved_rows = []
        failed_rows = []
        for alternative in alternatives:
            stages.alternative = alternative
            metrics = row_root / "alternatives" / alternative.alternative_id / "metrics.json"
            failure = metrics.parent / "failure.json"
            if metrics.is_file():
                solved_rows.append(read_json(metrics))
                continue
            if failure.is_file():
                failed_rows.append(read_json(failure))
                continue
            solve_root = metrics.parent / "qlip"
            config = cw._workflow_config(batch, solve_root, roots)
            config = replace(
                config,
                output_root=solve_root,
                qlip_runtime_root=REPO / "outputs",
                run_id=f"dataset-e-{batch.row_id}-{alternative.alternative_id}",
                attempt_id="dataset_e_frozen",
                request_spp_mode="enabled",
                native_qlip=False,
                scaffold_mode="loose",
                scaffold_dir=None,
                cell_mode="native",
                native_grid_density=None,
            )
            started = time.perf_counter()
            try:
                solved = stages.solve(task, request_spp, config, solve_root)
                runtime = time.perf_counter() - started
                components = (
                    asdict(solved["components"])
                    if is_dataclass(solved["components"])
                    else dict(solved["components"])
                )
                record = {
                    "alternative_id": alternative.alternative_id,
                    "scaffold_id": alternative.scaffold_id,
                    "development_template_id": alternative.provenance["development_template_id"],
                    "site_count": len(alternative.structure),
                    "orbit_count": len(alternative.ordered_orbits),
                    "vpa_A3_per_atom": alternative.provenance["vpa_A3_per_atom"],
                    "feasible_state_count": alternative.feasible_state_count,
                    "solver_status": solved["status"],
                    "solver_objective": float(solved["solver_objective"]),
                    "independent_objective": float(components["solver_objective"]),
                    "objective_difference": float(solved["difference"]),
                    "runtime_s": runtime,
                    "cif_path": str(Path(solved["cif_path"]).resolve()),
                    "cif_sha256": sha256(Path(solved["cif_path"])),
                    "solver_summary": solved.get("solver_summary"),
                    "solver_diagnostics": solved.get("solver_diagnostics"),
                    "components": components,
                }
                if record["objective_difference"] > 1e-6:
                    raise RuntimeError("solver/scorer mismatch")
                write_json(metrics, record)
                solved_rows.append(record)
                print(
                    f"SOLVED {batch.row_id} {alternative.alternative_id}: "
                    f"{solved['status']} {record['solver_objective']:.6g}"
                )
            except Exception as exc:
                record = {
                    "alternative_id": alternative.alternative_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "runtime_s": time.perf_counter() - started,
                }
                write_json(failure, record)
                failed_rows.append(record)
                print(f"FAILED ALTERNATIVE {batch.row_id} {alternative.alternative_id}: {exc}")
        if not solved_rows:
            write_json(
                final_path,
                {
                    "schema_version": "dataset_e.result.v1",
                    "row_id": batch.row_id,
                    "family": frozen["family"],
                    "subtype": frozen["subtype"],
                    "formula": frozen["formula"],
                    "target_reference_id": frozen["target_reference_id"],
                    "target_reference_excluded": True,
                    "generated": False,
                    "solver_status": "NO_FEASIBLE_ALTERNATIVE",
                    "alternative_count": len(alternatives),
                    "failed_alternatives": failed_rows,
                    "no_replacement": True,
                },
            )
            continue
        winner = dict(select_objective_minimum(solved_rows))
        generated = row_root / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        candidate = generated / "candidate.cif"
        if not candidate.exists():
            shutil.copy2(winner["cif_path"], candidate)
        winner["selected_cif_path"] = str(candidate.resolve())
        winner["selected_cif_sha256"] = sha256(candidate)
        preflight = read_json(row_root / "dataset_e_preflight_audit.json")
        write_json(
            final_path,
            {
                "schema_version": "dataset_e.result.v1",
                "row_id": batch.row_id,
                "family": frozen["family"],
                "subtype": frozen["subtype"],
                "formula": frozen["formula"],
                "request": frozen["request"],
                "target_reference_id": frozen["target_reference_id"],
                "target_reference_excluded": preflight["target_reference_excluded"],
                "generated": True,
                "alternative_count": len(alternatives),
                "feasible_alternative_count": len(solved_rows),
                "failed_alternative_count": len(failed_rows),
                "winner": winner,
                "alternatives": solved_rows,
                "failed_alternatives": failed_rows,
                "preflight": preflight,
                "no_replacement": True,
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--rows", default="")
    args = parser.parse_args()
    if args.prepare_only:
        prepare_all()
    else:
        run({value for value in args.rows.split(",") if value} or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
