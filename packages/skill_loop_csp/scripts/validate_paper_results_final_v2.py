"""Validate the PAPER-RESULTS-FINAL-V2 package and protected evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_results_extension_v3"


def rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def truth(value):
    return str(value).lower() == "true"


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path):
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*.POT")):
        digest.update(str(item.relative_to(path)).replace("\\", "/").encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


def main() -> None:
    required = [
        "01_execution/EXECUTION_FUNNEL.csv", "01_execution/METRIC_CLASSIFICATION.csv", "01_execution/TRACE_EXAMPLE.csv",
        "02_reference/REFERENCE_PROVENANCE.csv", "02_reference/SCA_INITIAL_RESULTS.csv", "02_reference/SCA_RELAXED_RESULTS.csv",
        "02_reference/CHGNET_RELAXATION_RESULTS.csv", "02_reference/REFERENCE_STRUCTURE_BENCHMARK.csv",
        "03_scaffold_spp/CASE_SELECTION.csv", "03_scaffold_spp/FEASIBLE_ASSIGNMENT_SCORES.csv",
        "03_scaffold_spp/SOLVER_CONFIRMATION.csv", "03_scaffold_spp/SCA_CANDIDATE_RESULTS.csv",
        "03_scaffold_spp/CANDIDATE_REFERENCE_COMPARISON.csv", "03_scaffold_spp/ABLATION_RELAXATION_RESULTS.csv",
        "03_scaffold_spp/RETRIEVAL_RESULTS.csv", "03_scaffold_spp/SPP_PAIR_COVERAGE.csv",
        "03_scaffold_spp/SCAFFOLD_SPP_FACTORIAL.csv", "04_extensibility/NASICON_SPECIALIST_RESULTS.csv",
        "04_extensibility/SCAFFOLD_PROVENANCE.csv", "04_extensibility/ABSTENTION_BENCHMARK.csv",
        "05_retrieval/RETRIEVAL_RELEVANCE.csv", "05_retrieval/HUMAN_REVIEW_SHEET.csv",
        "FINAL_RESULTS_REPORT.md", "FINAL_RESULTS_SUMMARY.csv", "MAIN_PAPER_TABLE.csv", "MAIN_PAPER_FIGURE_DATA.csv",
    ]
    assert all((OUT / item).is_file() for item in required)
    funnel = {r["metric"]: int(r["count"]) for r in rows(OUT / "01_execution" / "EXECUTION_FUNNEL.csv")}
    assert funnel["scientific_requests"] == 27 and funnel["workflow_executions"] == 39
    assert funnel["generated_CIF_executions"] == 35 and funnel["unique_generated_structures"] == 24
    assert funnel["duplicate_generated_executions"] == 11 and funnel["scientific_abstentions"] == 1
    assert funnel["blocked_before_solver"] == 3 and funnel["software_errors"] == 0
    assert funnel["explicit_OPTIMAL_solves"] == 5 and funnel["legacy_generated_selections"] == 30

    sca_initial = rows(OUT / "02_reference" / "SCA_INITIAL_RESULTS.csv")
    sca_relaxed = rows(OUT / "02_reference" / "SCA_RELAXED_RESULTS.csv")
    relaxation = rows(OUT / "02_reference" / "CHGNET_RELAXATION_RESULTS.csv")
    assert len(sca_initial) == len(sca_relaxed) == len(relaxation) == 24
    assert sum(r["family_topology_result"] == "PASS" for r in sca_initial) == 21
    assert sum(r["family_topology_result"] == "PASS" for r in sca_relaxed) == 22
    assert sum(truth(r["convergence"]) for r in relaxation) == 24
    assert sum(truth(r["space_group_retained"]) for r in relaxation) == 23
    assert sum(truth(r["crystal_system_retained"]) for r in relaxation) == 23
    li = next(r for r in relaxation if r["formula"] == "Li6PS5Cl")
    assert abs(float(li["volume_change_percent"]) - 46.11860828114279) < 1e-9
    provenance = rows(OUT / "02_reference" / "REFERENCE_PROVENANCE.csv")
    benchmark = rows(OUT / "02_reference" / "REFERENCE_STRUCTURE_BENCHMARK.csv")
    assert len(provenance) == 24 and len(benchmark) == 19
    assert sum(r["reference_independence_class"] == "INDEPENDENT_REFERENCE" for r in provenance) == 1

    cases = rows(OUT / "03_scaffold_spp" / "CASE_SELECTION.csv")
    assert len(cases) == 8
    assert sum(truth(r["included_strict_primary"]) for r in cases) == 5
    assert sum(truth(r["included_supplementary"]) for r in cases) == 2
    sr = next(r for r in cases if r["case_id"] == "srtio3")
    assert sr["SPP_coverage_class"] == "EXCLUDED_INSUFFICIENT_COVERAGE" and "Sr-Ti" in sr["exclusion_reason"]
    factorial = rows(OUT / "03_scaffold_spp" / "SCAFFOLD_SPP_FACTORIAL.csv")
    assert len(factorial) == 35
    strict = {r["case_id"] for r in cases if truth(r["included_strict_primary"])}
    correct = [r for r in factorial if r["case_id"] in strict and r["condition"] == "LOOSE_CORRECT_SPP"]
    perturbed = [r for r in factorial if r["case_id"] in strict and r["condition"] == "LOOSE_PERTURBED_SPP"]
    assert sum(truth(r["reference_top1"]) for r in correct) == 4
    assert sum(truth(r["reference_top1"]) for r in perturbed) == 1
    assert all(r["solver_status"] == "NO_UNIQUE_PREFERENCE" for r in factorial if r["condition"] == "LOOSE_NO_SPP")
    assert all(r["feasible_structure_count"] == "1" for r in factorial if r["scaffold_tightness"] == "TIGHT")
    assert all(r["feasible_structure_count"] == "2" for r in factorial if r["scaffold_tightness"] == "LOOSE")
    solver = rows(OUT / "03_scaffold_spp" / "SOLVER_CONFIRMATION.csv")
    assert len(solver) == 14 and all(r["solver_status"] == "OPTIMAL" and truth(r["objective_parity"]) for r in solver)
    assert max(float(r["absolute_objective_difference"]) for r in solver) < 1e-6
    scores = rows(OUT / "03_scaffold_spp" / "FEASIBLE_ASSIGNMENT_SCORES.csv")
    assert len(scores) == 14 and all(r["correct_spp_score"] != "" and r["perturbed_spp_score"] != "" for r in scores)
    assert len(rows(OUT / "03_scaffold_spp" / "SCA_CANDIDATE_RESULTS.csv")) == 14

    spp_manifest = rows(OUT / "03_scaffold_spp" / "boundary_grid8" / "SPP_SOURCE_MANIFEST.csv")
    for row in spp_manifest:
        if float(row["coverage_percent"]) < 100: continue
        raw = OUT / "03_scaffold_spp" / "raw" / row["case_id"]
        assert tree_hash(raw / "spp_arrays_curves") == row["spp_artifact_hash"]
        for name in ("request_task.json", "retrieval_result.json", "spp_fitter_result.json", "scaffold_definition.json", "tight_solver_input.lp", "loose_solver_input.lp", "tight_solver_result.json", "loose_solver_result.json", "occupation_assignments.csv", "SCA_initial_results.csv", "StructureMatcher_results.csv", "hashes.csv", "software_versions.json"):
            assert (raw / name).is_file(), f"missing raw artifact {row['case_id']}/{name}"
        assert any((raw / "retrieved_source_cifs").glob("*.cif"))
        assert any((raw / "spp_arrays_curves").rglob("*.POT"))

    grid = rows(OUT / "03_scaffold_spp" / "boundary_grid8" / "GRID8_ALL_ASSIGNMENTS.csv")
    recovery = rows(OUT / "03_scaffold_spp" / "boundary_grid8" / "GRID8_REFERENCE_RECOVERY.csv")
    assert len(grid) == 7840 and len(recovery) == 7 and sum(truth(r["reference_top1"]) for r in recovery) == 3
    assert not (OUT / "03_scaffold_spp" / "boundary_grid64").exists()
    nasicon = rows(OUT / "04_extensibility" / "NASICON_SPECIALIST_RESULTS.csv")
    assert len(nasicon) == 3 and all(r["solver_status"] == "OPTIMAL" and float(r["objective_difference"]) <= 1e-12 for r in nasicon)
    abstentions = rows(OUT / "04_extensibility" / "ABSTENTION_BENCHMARK.csv")
    assert len(abstentions) >= 3 and all(truth(r["correctly_abstained"]) and not truth(r["CIF_generated"]) and not truth(r["software_crash"]) for r in abstentions)

    protected = rows(OUT / "PROTECTED_HASH_VERIFICATION.csv")
    assert protected and all(r["status"] == "PASS" for r in protected)
    image_path = OUT / "03_scaffold_spp" / "SCAFFOLD_SPP_MAIN_RESULT.png"
    pdf_path = image_path.with_suffix(".pdf")
    svg_path = image_path.with_suffix(".svg")
    with Image.open(image_path) as image:
        width, height = image.size
        dpi = image.info.get("dpi", (0, 0))
        assert width > 2000 and height > 900 and min(dpi) >= 299
    pdf = pdf_path.read_bytes()
    assert pdf.startswith(b"%PDF-") and b"%%EOF" in pdf[-1024:] and b"/Type /Page" in pdf
    ET.parse(svg_path)
    manifest = rows(OUT / "OUTPUT_HASH_MANIFEST.csv")
    for row in manifest:
        path = OUT / row["path"]
        assert path.is_file() and sha256(path) == row["sha256"] and path.stat().st_size == int(row["bytes"])
    report = (OUT / "FINAL_RESULTS_REPORT.md").read_text(encoding="utf-8")
    for heading in ("1. End-to-end execution and traceability", "2. Recovery of known crystal structures", "3. Complementary contributions of scaffolds and retrieval-derived SPPs", "4. Scaffold extensibility and representability", "5. Retrieval, leakage and SPP coverage audit", "6. GRID8 boundary experiment", "7. Negative and unexpected findings", "8. Manuscript-safe quantitative claims"):
        assert heading in report
    assert "RESULT_B" in report and "GRID64 was not continued" in report
    print(json.dumps({"status": "PASS", "figure_pixels": [width, height], "figure_dpi": dpi, "strict_cases": len(strict), "correct_top1": 4, "perturbed_top1": 1, "protected_records": len(protected)}, indent=2))


if __name__ == "__main__":
    main()
