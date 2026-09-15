"""Run the auditable NASICON retrieval -> SPP -> QLIP -> topology workflow."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import itertools
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from pymatgen.core import Composition, Structure
from pymatgen.core.structure_matcher import StructureMatcher
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.retrieval.specialist_corpora import retrieve_corpus_evidence
from sok_llm_orchestrator.verification.nasicon_topology import validate_nasicon_topology


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_PATH = REPO_ROOT / "benchmarks" / "paper_nasicon_specialist" / "task.json"
REFERENCE_CIF = REPO_ROOT / "data" / "nasicon" / "reference" / "reference.cif"
ORBIT_TABLE = REPO_ROOT / "data" / "nasicon" / "reference" / "orbit_table.csv"
CONDITIONS = {
    "broad": "materials_project_broad_phase6",
    "full": "nasicon_specialist_v1",
    "leave_target_out": "nasicon_specialist_leave_target_out_v1",
}
V2_CONDITIONS = {
    "broad": "materials_project_broad_phase6",
    "full": "nasicon_specialist_v2",
    "leave_target_out": "nasicon_specialist_leave_target_out_v2",
}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _canonical_pair(left: str, right: str) -> str:
    return "-".join(sorted((left, right), key=str.lower))


def _chemical_pair_coverage(rows: list[dict[str, Any]], required_pairs: list[str]) -> dict[str, list[str]]:
    evidence: dict[str, list[str]] = {pair: [] for pair in required_pairs}
    for row in rows:
        try:
            elements = [str(element) for element in Composition(row.get("reduced_formula") or row.get("formula") or "").elements]
        except Exception:
            continue
        present = {_canonical_pair(left, right) for left, right in itertools.combinations_with_replacement(elements, 2)}
        for pair in present & set(required_pairs):
            evidence[pair].append(str(row["structure_id"]))
    return evidence


def _export_evidence(retrieval: dict[str, Any], evidence_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    selected_manifest: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for rank, row in enumerate(retrieval["selected"], start=1):
        record = {key: value for key, value in row.items() if key != "cif_text"}
        record["rank"] = rank
        if row.get("eligible_for_internal_spp"):
            cif_path = evidence_dir / f"{row['structure_id']}.cif"
            cif_path.write_text(str(row["cif_text"]), encoding="utf-8")
            record["internal_spp_cif_path"] = str(cif_path)
            eligible.append(row)
        selected_manifest.append(record)
    return eligible, selected_manifest


def _load_qlip_runner(qlip_repo: Path):
    sys.path.insert(0, str((qlip_repo / "src").resolve()))
    path = qlip_repo / "scripts" / "run_nasicon_qlip_smoke.py"
    spec = importlib.util.spec_from_file_location("nasicon_qlip_smoke_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load QLIP NASICON runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_spp(evidence_dir: Path, spp_root: Path, formula: str, spp_repo: Path) -> dict[str, Any]:
    sys.path.insert(0, str((spp_repo / "src").resolve()))
    from spp_maker_qlip.required_pair_extraction import (  # noqa: PLC0415
        collect_required_pair_distances,
        export_required_pair_spp_root,
    )

    preflight = collect_required_pair_distances(
        cif_dir=evidence_dir, formula=formula, cutoff=11.0, supercell=(2, 2, 2)
    )
    if preflight["missing_pairs"]:
        return {"stage_status": "BLOCKED_PAIR_COVERAGE", "preflight": preflight, "generation": None}
    generation = export_required_pair_spp_root(
        cif_dir=evidence_dir, formula=formula, out_root=spp_root,
        name=f"row_specific_{evidence_dir.parent.name}", cutoff=11.0,
        supercell=(2, 2, 2), alpha=1e-3, d_min=0.5, bin_width=0.05,
    )
    compatible = len(list(spp_root.rglob("*.POT"))) == len(preflight["required_pairs"])
    return {
        "stage_status": "COMPLETE_DIAGNOSTIC_QUALITY" if compatible and not generation["ok"] else "COMPLETE" if compatible else "FAILED",
        "preflight": preflight, "generation": generation,
    }


def _crystallographic_validation(solution_cif: Path) -> dict[str, Any]:
    structure = Structure.from_file(solution_cif)
    reference = Structure.from_file(REFERENCE_CIF)
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5.0, primitive_cell=False, scale=False, attempt_supercell=False)
    distances = structure.distance_matrix.copy()
    distances[distances < 1e-12] = float("inf")
    return {
        "parseable_cif": True,
        "formula": structure.composition.formula,
        "reduced_formula": structure.composition.reduced_formula,
        "formula_correct": structure.composition.reduced_composition == Composition("Na3Zr2Si2PO12").reduced_composition,
        "analyzed_space_group_symbol": analyzer.get_space_group_symbol(),
        "analyzed_space_group_number": analyzer.get_space_group_number(),
        "analyzed_crystal_system": analyzer.get_crystal_system(),
        "declared_scaffold_space_group_number": 5,
        "scaffold_symmetry_match": analyzer.get_space_group_number() == 5,
        "minimum_distance_angstrom": float(distances.min()),
        "severe_short_contact": bool(float(distances.min()) < 1.0),
        "structure_matcher_fit_to_reference": bool(matcher.fit(reference, structure)),
        "structure_matcher_rms_to_reference": matcher.get_rms_dist(reference, structure),
    }


def run_condition(
    condition: str,
    *,
    qlip_repo: Path,
    spp_repo: Path,
    runs_root: Path,
    artifacts_root: Path,
) -> dict[str, Any]:
    task = json.loads(TASK_PATH.read_text(encoding="utf-8"))
    corpus_id = CONDITIONS[condition]
    run_dir = (runs_root / condition).resolve()
    artifact_dir = (artifacts_root / condition).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "task.json", {**task, "specialist_corpus_id": corpus_id, "retrieval_condition": condition})

    started = time.perf_counter()
    retrieval = retrieve_corpus_evidence(
        corpus_id, query_text=task["natural_language_request"] + " " + task["retrieval_query"],
        target_formula=task["target_formula"], depth=int(task["retrieval_depth"]),
    )
    eligible, selected_manifest = _export_evidence(retrieval, run_dir / "retrieved_evidence_cifs")
    retrieval_record = {key: value for key, value in retrieval.items() if key != "selected"}
    retrieval_record["selected"] = selected_manifest
    _write_json(run_dir / "retrieval.json", retrieval_record)
    required_pairs = list(task["required_spp_pairs"])
    chemical_coverage = _chemical_pair_coverage(eligible, required_pairs)
    missing_chemical_pairs = [pair for pair, ids in chemical_coverage.items() if not ids]
    _write_json(run_dir / "pair_coverage_preflight.json", {
        "required_pairs": required_pairs, "chemical_pair_evidence": chemical_coverage,
        "missing_pairs": missing_chemical_pairs, "complete": not missing_chemical_pairs,
    })

    base_summary = {
        "schema_version": "paper_nasicon_condition.v1", "condition": condition,
        "corpus_id": corpus_id, "retrieval_method": retrieval["retrieval_method"],
        "retrieved_count": retrieval["selected_count"], "eligible_evidence_count": len(eligible),
        "exact_target_leakage_count": retrieval["exact_target_leakage_count"],
        "required_pair_count": len(required_pairs), "chemical_pair_coverage_complete": not missing_chemical_pairs,
        "missing_chemical_pairs": missing_chemical_pairs,
    }
    if not eligible or missing_chemical_pairs:
        summary = {**base_summary, "workflow_status": "BLOCKED_BEFORE_SPP", "runtime_s": time.perf_counter() - started}
        _write_json(run_dir / "workflow_summary.json", summary)
        _write_json(artifact_dir / "workflow_summary.json", summary)
        return summary

    spp = _run_spp(run_dir / "retrieved_evidence_cifs", run_dir / "row_specific_spp" / "spp_root", task["target_formula"], spp_repo)
    _write_json(run_dir / "spp_result.json", spp)
    if not str(spp["stage_status"]).startswith("COMPLETE"):
        summary = {**base_summary, "workflow_status": "BLOCKED_SPP", "spp_stage_status": spp["stage_status"], "runtime_s": time.perf_counter() - started}
        _write_json(run_dir / "workflow_summary.json", summary)
        _write_json(artifact_dir / "workflow_summary.json", summary)
        return summary

    allowed_roots = [REPO_ROOT, qlip_repo.resolve(), run_dir, (run_dir / "row_specific_spp" / "spp_root").resolve()]
    os.environ["QLIP_ALLOWED_PATH_ROOTS"] = os.pathsep.join(str(path) for path in allowed_roots)
    qlip_runner = _load_qlip_runner(qlip_repo)
    qlip_summary = qlip_runner.run(
        REFERENCE_CIF, ORBIT_TABLE, (run_dir / "row_specific_spp" / "spp_root").resolve(),
        run_dir / "qlip", 11.0,
    )
    solution_cif = run_dir / "qlip" / "solution.cif"
    crystal = _crystallographic_validation(solution_cif)
    topology = validate_nasicon_topology(solution_cif)
    _write_json(run_dir / "crystallographic_validation.json", crystal)
    _write_json(run_dir / "nasicon_topology_validation.json", topology)
    shutil.copy2(solution_cif, artifact_dir / "generated_nasicon.cif")
    for name in ("solve_request.json", "solve_result.json", "smoke_summary.json"):
        shutil.copy2(run_dir / "qlip" / name, artifact_dir / name)
    _write_json(artifact_dir / "retrieval_evidence.json", retrieval_record)
    _write_json(artifact_dir / "nasicon_topology_validation.json", topology)
    success = (
        qlip_summary["status"] in {"OPTIMAL", "FEASIBLE"}
        and crystal["formula_correct"] and not crystal["severe_short_contact"]
        and topology["topology_status"] in {"PASS", "PARTIAL"}
    )
    summary = {
        **base_summary, "workflow_status": "COMPLETE" if success else "COMPLETE_VALIDATION_FAILED",
        "spp_stage_status": spp["stage_status"], "spp_quality_status": spp["generation"]["spp_pot_quality"].get("spp_pot_quality_status"),
        "spp_pair_coverage_complete": not spp["preflight"]["missing_pairs"],
        "solver_mode": "QLIP binary symmetry-closed Si/P orbit allocation",
        "solver_status": qlip_summary["status"], "objective": qlip_summary["solver_objective"],
        "objective_parity": qlip_summary["objective_parity"], "generated_formula": crystal["reduced_formula"],
        "model_build_time_ms": qlip_summary.get("model_build_time_ms"),
        "solver_time_ms": qlip_summary.get("solver_time_ms"),
        "chosen_si_p_assignment": qlip_summary["alternative_objectives"][0]["assignment"],
        "analyzed_space_group": crystal["analyzed_space_group_symbol"], "analyzed_space_group_number": crystal["analyzed_space_group_number"],
        "contact_screen": "PASS" if not crystal["severe_short_contact"] else "FAIL",
        "topology_status": topology["topology_status"], "framework_dimensionality": topology["framework_dimensionality"],
        "similarity_to_reference": crystal["structure_matcher_rms_to_reference"],
        "structure_matcher_fit_to_reference": crystal["structure_matcher_fit_to_reference"],
        "runtime_s": time.perf_counter() - started,
        "scientific_limitations": [
            "Raw objectives from independently fitted condition-specific SPPs are not cross-condition calibrated.",
            "Diagnostic-only POT quality is reported and not hidden.",
            "No stability, novelty, conductivity, or experimental realizability claim is made.",
        ],
    }
    _write_json(run_dir / "workflow_summary.json", summary)
    _write_json(artifact_dir / "workflow_summary.json", summary)
    return summary


def _comparison(summaries: list[dict[str, Any]], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    columns = [
        "condition", "corpus_id", "workflow_status", "retrieved_count", "eligible_evidence_count",
        "exact_target_leakage_count", "chemical_pair_coverage_complete", "spp_pair_coverage_complete",
        "spp_quality_status", "solver_status", "objective", "generated_formula", "analyzed_space_group",
        "analyzed_space_group_number", "contact_screen", "topology_status", "framework_dimensionality",
        "structure_matcher_fit_to_reference", "similarity_to_reference", "model_build_time_ms", "solver_time_ms",
        "chosen_si_p_assignment", "runtime_s",
    ]
    with (root / "NASICON_CONDITION_COMPARISON.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for summary in summaries:
            writer.writerow({key: summary.get(key, "") for key in columns})
    lines = [
        "# NASICON condition comparison", "",
        "All conditions use the same target, ordered orbit scaffold, QLIP settings, 11 Å cutoff, and seed. Raw SPP objectives are not compared as calibrated energies.", "",
    ]
    for summary in summaries:
        lines.extend([
            f"## {summary['condition']}", "",
            f"- Workflow: {summary['workflow_status']}",
            f"- Evidence: {summary['eligible_evidence_count']} eligible rows; exact-target leakage: {summary['exact_target_leakage_count']}",
            f"- Pair coverage: {summary.get('spp_pair_coverage_complete', summary['chemical_pair_coverage_complete'])}",
            f"- Solver/topology: {summary.get('solver_status', 'not run')} / {summary.get('topology_status', 'not run')}", "",
        ])
    (root / "NASICON_CONDITION_COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")
    evidence_lines = ["# NASICON retrieval evidence", ""]
    for summary in summaries:
        evidence_lines.append(f"- {summary['condition']}: corpus `{summary['corpus_id']}`, {summary['retrieved_count']} retrieved, {summary['eligible_evidence_count']} internally SPP-eligible.")
    (root / "NASICON_RETRIEVAL_EVIDENCE.md").write_text("\n".join(evidence_lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conditions", nargs="+", choices=sorted(CONDITIONS), default=["full"])
    parser.add_argument("--qlip-repo", type=Path, default=REPO_ROOT.parent / "qlip")
    parser.add_argument("--spp-repo", type=Path, default=REPO_ROOT.parent / "SPP-Maker-QLIP")
    parser.add_argument("--runs-root", type=Path, default=REPO_ROOT / "runs" / "paper_nasicon_specialist")
    parser.add_argument("--artifacts-root", type=Path, default=REPO_ROOT / "artifacts" / "paper_nasicon_specialist")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--corpus-version", choices=["v1", "v2"], default="v1")
    args = parser.parse_args()
    if args.corpus_version == "v2":
        CONDITIONS.update(V2_CONDITIONS)
    completed_now = [] if args.report_only else [
        run_condition(condition, qlip_repo=args.qlip_repo.resolve(), spp_repo=args.spp_repo.resolve(), runs_root=args.runs_root.resolve(), artifacts_root=args.artifacts_root.resolve())
        for condition in args.conditions
    ]
    summaries = []
    for condition in CONDITIONS:
        summary_path = args.runs_root.resolve() / condition / "workflow_summary.json"
        if summary_path.is_file():
            summaries.append(json.loads(summary_path.read_text(encoding="utf-8")))
    _comparison(summaries, REPO_ROOT / "artifacts" / "nasicon_comparison")
    print(json.dumps(completed_now, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
