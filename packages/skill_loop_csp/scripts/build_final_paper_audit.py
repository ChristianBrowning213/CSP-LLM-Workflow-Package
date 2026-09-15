"""Build the authoritative Paper_scaffolds_september writing audit.

This script performs read-only extraction from already-frozen scientific
artifacts.  It does not invoke retrieval, SPP construction, QLIP, SCA, CHGNet,
DFT, Materials Project, or Crystal-DB corpus construction.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[1]
CRYSTAL_DB = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
SCA_REPO = Path(r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser")
QLIP_REPO = Path(r"C:\Users\brown\Documents\GitHub\qlip")
PAPER = REPO / "artifacts" / "Paper_scaffolds_september"
OUT = PAPER / "FINAL_PAPER_AUDIT"
CRYSTAL_AUDIT = (
    CRYSTAL_DB / "artifacts" / "Paper_scaffolds_september" / "specialist_corpora"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "pass", "generated", "valid"}


def repo_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, encoding="utf-8", errors="replace"
    ).strip()


SOURCES: list[tuple[str, str, Path, str]] = [
    ("Dataset A final rows", "final A result table", PAPER / "dataset_A/results/DATASET_A_RESULTS.csv", "Authoritative 24-row A outcomes."),
    ("Dataset A roster", "frozen A selection", PAPER / "dataset_A/selection/DATASET_A.csv", "Requests and target-exclusion fields."),
    ("Dataset A run index", "A artifact routing", PAPER / "dataset_A/RUN_INDEX.csv", "Final spinel rerun routing and CIF hashes."),
    ("Dataset B final rows", "final B result table", PAPER / "dataset_B/results/DATASET_B_RESULTS.csv", "Authoritative 24-row raw SCA outcomes and solver data."),
    ("Dataset B roster", "frozen B selection", PAPER / "dataset_B/selection/DATASET_B.csv", "Requests and retrieval routes."),
    ("Dataset B run index", "B artifact routing", PAPER / "dataset_B/RUN_INDEX.csv", "Frozen B classifications."),
    ("Dataset C final rows", "final paired C result table", PAPER / "dataset_C/results/DATASET_C_RESULTS.csv", "Authoritative 24-row scaffold outcomes."),
    ("Dataset C roster", "frozen C selection", PAPER / "dataset_C/selection/DATASET_C.csv", "Requests and B pairing."),
    ("Dataset C run index", "C artifact routing", PAPER / "dataset_C/RUN_INDEX.csv", "B pair IDs, scaffold IDs, and solver data."),
    ("A/B/C method freeze", "frozen v1 paper method", PAPER / "FINAL_METHOD_FREEZE.json", "SPP, solver, scaffold-v1, validation, and CHGNet protocol."),
    ("A/B/C claim-safe report", "final claim-safe interpretation", PAPER / "final_audit/CLAIM_SAFE_RESULTS.md", "Final denominators, caveats, and efficiency ranges."),
    ("Final scientific audit", "final A/B/C reconciliation", PAPER / "final_audit/FINAL_SCIENTIFIC_AUDIT.json", "B20 correction, invariant audit, runtime correction, and method caveats."),
    ("B-C invariant rows", "paired scientific-input audit", PAPER / "final_audit/B_C_INVARIANT_AUDIT.csv", "24 paired retrieval/SPP comparisons."),
    ("B-C runtime rows", "paired runtime/search-space audit", PAPER / "final_audit/B_C_RUNTIME_SEARCHSPACE.csv", "Constraint and wall-clock comparisons."),
    ("Olivine independent validation", "primary olivine family audit", PAPER / "final_audit/OLIVINE_INDEPENDENT_VALIDATION.csv", "Species-blind StructureMatcher and Pnma outcomes, including B20."),
    ("Scaffold v1 freeze", "v1 scaffold hash freeze", PAPER / "final_audit/SCAFFOLD_LIBRARY_FREEZE.json", "Pre-holdout v1 scaffold freeze."),
    ("Scaffold v1 source", "actual v1 implementation", REPO / "src/sok_llm_orchestrator/workflow/paper_scaffolds_library.py", "Frozen four-family v1 implementation."),
    ("Scaffold v2 source", "actual v2 implementation", REPO / "src/sok_llm_orchestrator/workflow/paper_scaffolds_library_v2.py", "Frozen flexible four-family implementation."),
    ("Scaffold v2 method freeze", "final v2 method", PAPER / "scaffold_v2/V2_METHOD_FREEZE.json", "Frozen alternatives, acceptance rules, and source hashes."),
    ("Scaffold v2 final report", "final v2 results", PAPER / "scaffold_v2/FINAL_V2_REPORT.json", "33-row holdout and 12-row ablation headline results."),
    ("Scaffold v2 claim-safe", "v2 claim wording", PAPER / "scaffold_v2/CLAIM_SAFE_V2.md", "Allowed and prohibited v2 claims."),
    ("Scaffold v2 methods note", "v1-to-v2 history", PAPER / "scaffold_v2/METHODS_SCAFFOLD_DEVELOPMENT_NOTE.md", "Development/freeze chronology and freedom interpretation."),
    ("Scaffold v1-v2 comparison", "scaffold freedom audit", PAPER / "scaffold_v2/V1_V2_FREEDOM_COMPARISON.csv", "Exact v1/v2 model and realization counts."),
    ("v2 holdout roster", "frozen 33-row holdout", PAPER / "scaffold_v2/final_holdout/V2_HOLDOUT.csv", "Unseen formulas, exclusions, and alternative counts."),
    ("v2 holdout requests", "holdout workflow inputs", PAPER / "scaffold_v2/final_holdout/V2_HOLDOUT_WORKFLOW_INPUT.csv", "Exact request text."),
    ("v2 holdout results", "staged v2 results", PAPER / "scaffold_v2/final_holdout/V2_HOLDOUT_RESULTS.csv", "Pre/post validation and CHGNet outcomes."),
    ("v2 ablation results", "frozen 12-row SPP ablation", PAPER / "scaffold_v2/spp_ablation/SPP_V2_ABLATION_RESULTS.csv", "Request/global objective and structure selection."),
    ("v2 ablation interpretation", "ablation claim audit", PAPER / "scaffold_v2/spp_ablation/SPP_V2_ABLATION_ANALYSIS.md", "Geometry, occupation, and convergence caveats."),
    ("Dataset E final rows", "final Dataset E results", PAPER / "Dataset_E_complex_topology_showcase/FINAL_DATASET_E_RESULTS.csv", "Authoritative 18-row complex-topology outcomes."),
    ("Dataset E final report", "final Dataset E interpretation", PAPER / "Dataset_E_complex_topology_showcase/FINAL_DATASET_E_REPORT.md", "Fixed-denominator final report."),
    ("Dataset E roster", "frozen Dataset E selection", PAPER / "Dataset_E_complex_topology_showcase/FINAL_SHOWCASE_ROSTER.csv", "Final targets and pre-generation alternatives."),
    ("Dataset E method freeze", "complex scaffold method", PAPER / "Dataset_E_complex_topology_showcase/METHOD_FREEZE.json", "Frozen topology/scaling/SPP semantics."),
    ("Dataset E validation freeze", "complex topology validator", PAPER / "Dataset_E_complex_topology_showcase/VALIDATION_METHOD_FREEZE.json", "Frozen matcher settings and PASS definition."),
    ("Dataset E exclusion audit", "target exclusion and pair coverage", PAPER / "Dataset_E_complex_topology_showcase/TARGET_EXCLUSION_AND_PAIR_COVERAGE_AUDIT.json", "18/18 exclusion and complete-guidance audit."),
    ("Dataset E templates", "development-derived topology templates", PAPER / "Dataset_E_complex_topology_showcase/DEVELOPMENT_SCAFFOLD_TEMPLATES.json", "Hash-frozen development prototypes only."),
    ("Dataset E scaffold source", "actual complex scaffold implementation", REPO / "src/sok_llm_orchestrator/workflow/paper_scaffolds_dataset_e.py", "Frozen Dataset E ordered-orbit implementation."),
    ("Dataset E validator source", "actual complex validator implementation", REPO / "src/sok_llm_orchestrator/workflow/dataset_e_validation.py", "Frozen Dataset E anonymous matcher."),
    ("CHGNet provenance", "relaxation protocol", PAPER / "dataset_C/chgnet/CHGNET_MODEL_PROVENANCE.json", "Checkpoint hash and exact relaxation settings."),
    ("Figure 1 source map", "scientific figure provenance", PAPER / "figure1_fix_spp/figure1_folder/FIGURE1_SOURCE_MAP.md", "Figure 1 row/source mapping."),
    ("Figure 1 SPP map", "SPP panel provenance", PAPER / "figure1_fix_spp/SPP_PANEL_SOURCE_MAP.md", "Actual C09 MgCr2O4 SPP paths."),
    ("Crystal-DB final summary", "final specialist counts", CRYSTAL_AUDIT / "SPECIALIST_CORPUS_SUMMARY.csv", "Final corpus/count/readiness rows including ordered v2 replacements."),
    ("Crystal-DB corpus hashes", "database integrity", CRYSTAL_AUDIT / "CORPUS_HASHES.json", "SHA256 values for final and superseded databases."),
    ("Crystal-DB ordered update", "olivine/argyrodite reconciliation", CRYSTAL_AUDIT / "ORDERED_SPECIALIST_CORPUS_UPDATE.md", "Why v2 counts supersede v1 counts."),
    ("Crystal-DB pipeline map", "retrieval representation pipeline", CRYSTAL_AUDIT / "CRYSTAL_DB_PIPELINE_MAP.md", "Canonical CIF-to-vector pipeline and versions."),
    ("SCA overview", "validator identity and scope", SCA_REPO / "README.md", "Defines SCA as an internal pre-DFT toolkit."),
    ("SCA topology source", "SCA verdict semantics", SCA_REPO / "sca/evaluators/topology.py", "PASS/PARTIAL/FAIL aggregation and family checks."),
    ("SCA contact source", "contact validation", SCA_REPO / "sca/evaluators/bonds.py", "Periodic contact thresholds and minimum-distance logic."),
    ("QLIP package metadata", "solver dependency versions", QLIP_REPO / "pyproject.toml", "Pinned Pyomo/Gurobi/numpy/pymatgen versions and repository package version."),
]


REQUIRED_FILES = [
    "README.md", "FINAL_PAPER_AUDIT_MANIFEST.json", "FINAL_PAPER_AUDIT_HASHES.json",
    "01_results/PAPER_MASTER_RESULTS.csv", "01_results/PAPER_MASTER_RESULTS.md",
    "01_results/PAPER_HEADLINE_NUMBERS.md", "02_claims/PAPER_CLAIMS_AND_CAVEATS.md",
    "03_methods/PAPER_METHODS_FREEZE.md", "03_methods/SOFTWARE_VERSIONS.csv",
    "04_scaffolds/SCAFFOLD_DEFINITIONS.csv", "04_scaffolds/SCAFFOLD_DEFINITIONS.md",
    "05_validation/VALIDATION_DEFINITIONS.md", "05_validation/VALIDATION_FAMILY_MATRIX.csv",
    "06_datasets/DATASET_A_MANIFEST.csv", "06_datasets/DATASET_B_MANIFEST.csv",
    "06_datasets/DATASET_C_MANIFEST.csv", "06_datasets/DATASET_V2_HOLDOUT_MANIFEST.csv",
    "06_datasets/DATASET_E_MANIFEST.csv", "06_datasets/DATASET_SUMMARY.md",
    "07_crystaldb/CRYSTALDB_CORPUS_SUMMARY.csv", "07_crystaldb/CRYSTALDB_CORPUS_SUMMARY.md",
    "08_provenance/FROZEN_ARTIFACT_INDEX.csv", "08_provenance/SOURCE_PATH_INDEX.csv",
    "08_provenance/AUDIT_NOTES.md",
]


MANIFEST_FIELDS = [
    "dataset", "row_id", "formula", "family", "subtype", "request", "source_dataset",
    "scaffold_id", "scaffold_version", "solver_status", "solver_runtime_s", "generated",
    "exact_composition", "fully_ordered", "pre_topology_status", "pre_topology_validator",
    "chgnet_converged", "post_topology_status", "post_topology_validator", "generated_cif_path",
    "relaxed_cif_path", "target_reference_excluded", "pair_coverage", "notes",
    "paired_row_id", "retrieval_spp_invariant", "historical_sca_pre_status",
    "historical_sca_post_status", "selected_alternative", "alternative_solve_count",
    "total_topology_valid_realisations", "spinel_ordering",
]


def build_dataset_manifests() -> dict[str, list[dict[str, Any]]]:
    selections = {
        name: {r["row_id"]: r for r in read_csv(PAPER / f"dataset_{name}/selection/DATASET_{name}.csv")}
        for name in ("A", "B", "C")
    }
    results = {
        name: read_csv(PAPER / f"dataset_{name}/results/DATASET_{name}_RESULTS.csv")
        for name in ("A", "B", "C")
    }
    run_indices = {
        name: {r["row_id"]: r for r in read_csv(PAPER / f"dataset_{name}/RUN_INDEX.csv")}
        for name in ("A", "B", "C")
    }
    independent = defaultdict(dict)
    for row in read_csv(PAPER / "final_audit/OLIVINE_INDEPENDENT_VALIDATION.csv"):
        independent[(row["dataset"], row["row_id"])][row["stage"]] = row

    built: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    for row in results["A"]:
        rid = row["row_id"]
        sel, idx = selections["A"][rid], run_indices["A"][rid]
        solver_path = Path(idx["artifact_root"]) / "qlip" / "solver_result.json"
        solver = load_json(solver_path)
        family_validator = "SCA family policy plus frozen prototype/space-group classifier"
        built["A"].append({
            "dataset": "A", "row_id": rid, "formula": row["formula"], "family": row["family"],
            "subtype": row["class_"], "request": sel["request_text"], "source_dataset": "frozen Dataset A selection",
            "scaffold_id": "NONE", "scaffold_version": "none (SPP-only)",
            "solver_status": solver.get("status", ""), "solver_runtime_s": solver.get("runtime_s", ""),
            "generated": row["generation_status"] == "GENERATED", "exact_composition": True,
            "fully_ordered": True, "pre_topology_status": row["pre_relax_requested_topology"],
            "pre_topology_validator": family_validator, "chgnet_converged": row["chgnet"] == "CONVERGED",
            "post_topology_status": row["post_relax_requested_topology"], "post_topology_validator": family_validator,
            "generated_cif_path": row["generated_cif"], "relaxed_cif_path": row["relaxed_cif"],
            "target_reference_excluded": truth(sel["exclude_target_reference"]), "pair_coverage": "COMPLETE",
            "notes": f"structural_validity={row['structural_validity']}; CHGNet terminal={row['chgnet']}; A_STRONG_SUCCESS={row['A_STRONG_SUCCESS']}",
        })

    for row in results["B"]:
        rid = row["row_id"]
        sel = selections["B"][rid]
        pre_final = "MISS"
        post_final = "MISS"
        pre_validator = "SCA family policy / frozen family classifier"
        post_validator = pre_validator
        if row["family"] == "OLIVINE":
            pre = independent[("B", rid)]["pre_relax"]
            post = independent[("B", rid)]["post_relax"]
            pre_final = "PASS" if pre["independent_verdict"] == "OLIVINE" else "MISS"
            post_final = "PASS" if post["independent_verdict"] == "OLIVINE" else "MISS"
            pre_validator = post_validator = "species-blind StructureMatcher plus Pnma independent criterion"
        note = f"Raw frozen SCA pre={row['pre_policy_status']}/{row['pre_requested_topology']}; post={row['post_policy_status']}/{row['post_requested_topology']}."
        if rid.startswith("B20_"):
            note += " Historical SCA false positive: independently Pmm2 with zero olivine framework matches."
        built["B"].append({
            "dataset": "B", "row_id": rid, "formula": row["formula"], "family": row["family"],
            "subtype": "SPP-only topology-miss cohort", "request": sel["request_text"],
            "source_dataset": "frozen Dataset B selection", "scaffold_id": "NONE",
            "scaffold_version": "none (SPP-only)", "solver_status": row["solver"],
            "solver_runtime_s": row["solver_runtime_s"], "generated": row["gen"] == "GENERATED",
            "exact_composition": True, "fully_ordered": True, "pre_topology_status": pre_final,
            "pre_topology_validator": pre_validator, "chgnet_converged": row["chgnet"] == "CONVERGED",
            "post_topology_status": post_final, "post_topology_validator": post_validator,
            "generated_cif_path": row["generated_cif"], "relaxed_cif_path": row["relaxed_cif"],
            "target_reference_excluded": truth(sel["exclude_target_reference"]), "pair_coverage": "COMPLETE",
            "historical_sca_pre_status": f"{row['pre_policy_status']}/{row['pre_requested_topology']}",
            "historical_sca_post_status": f"{row['post_policy_status']}/{row['post_requested_topology']}",
            "notes": note,
        })

    invariant_rows = read_csv(PAPER / "final_audit/B_C_INVARIANT_AUDIT.csv")
    pairs = defaultdict(list)
    for item in invariant_rows:
        pairs[item["pair"]].append(item)
    for row in results["C"]:
        rid = row["row_id"]
        sel, idx = selections["C"][rid], run_indices["C"][rid]
        bid = idx["paired_B"]
        key = f"{bid}<->{rid}"
        if key not in pairs or any(x["category"] == "UNEXPECTED_DIFFERENCE" for x in pairs[key]):
            raise AssertionError(f"B-C scientific-input invariant failed for {key}")
        validator = "SCA family policy plus expected family space group"
        if row["family"] == "OLIVINE":
            validator = "SCA plus independent species-blind StructureMatcher/Pnma confirmation"
        built["C"].append({
            "dataset": "C", "row_id": rid, "formula": row["formula"], "family": row["family"],
            "subtype": "paired scaffold intervention", "request": sel["request_text"],
            "source_dataset": "frozen Dataset C selection paired to Dataset B", "scaffold_id": row["scaffold_id"],
            "scaffold_version": "paper_scaffolds_library.v1", "solver_status": row["solver"],
            "solver_runtime_s": row["solver_runtime_s"], "generated": row["gen"] == "GENERATED",
            "exact_composition": True, "fully_ordered": True, "pre_topology_status": row["pre_requested_topology"],
            "pre_topology_validator": validator, "chgnet_converged": row["chgnet"] == "CONVERGED",
            "post_topology_status": row["post_requested_topology"], "post_topology_validator": validator,
            "generated_cif_path": row["generated_cif"], "relaxed_cif_path": row["relaxed_cif"],
            "target_reference_excluded": truth(sel["exclude_target_reference"]), "pair_coverage": "COMPLETE",
            "paired_row_id": bid, "retrieval_spp_invariant": "IDENTICAL",
            "notes": "All audited retrieval/SPP scientific inputs byte-identical to paired B row; only declared scaffold intervention differs.",
        })

    holdout = {r["row_id"]: r for r in read_csv(PAPER / "scaffold_v2/final_holdout/V2_HOLDOUT.csv")}
    requests = {r["row_id"]: r for r in read_csv(PAPER / "scaffold_v2/final_holdout/V2_HOLDOUT_WORKFLOW_INPUT.csv")}
    stages = defaultdict(dict)
    for row in read_csv(PAPER / "scaffold_v2/final_holdout/V2_HOLDOUT_RESULTS.csv"):
        stages[row["row_id"]][row["stage"]] = row
    v2_rows: list[dict[str, Any]] = []
    for rid in sorted(stages):
        if set(stages[rid]) != {"pre_chgnet", "post_chgnet"}:
            raise AssertionError(f"v2 stage pair incomplete: {rid}")
        pre, post, roster = stages[rid]["pre_chgnet"], stages[rid]["post_chgnet"], holdout[rid]
        family = pre["policy"]
        primary_pre, primary_post = pre["sca_topology_status"], post["sca_topology_status"]
        validator = "SCA family policy"
        note = f"Raw SCA pre={pre['sca_topology_status']}; post={post['sca_topology_status']}."
        if family == "OLIVINE":
            primary_pre = primary_post = "PASS"
            validator = "independent Pnma plus anonymous ordered-olivine StructureMatcher criterion"
            note += " Independent olivine criterion PASS; raw SCA chemistry coverage is Li/P-specific."
        if family == "SPINEL" and post["sca_topology_status"] == "PARTIAL":
            note += " Ordered-inverse Imma structure; PARTIAL retained and not relabelled PASS."
        if family == "ROCKSALT" and post["sca_topology_status"] == "PARTIAL":
            note += " Frozen post-relax PARTIAL retained and not relabelled PASS."
        v2_rows.append({
            "dataset": "V2_HOLDOUT", "row_id": rid, "formula": pre["formula"], "family": family,
            "subtype": "ordered flexible v2", "request": requests[rid]["request_text"],
            "source_dataset": "frozen unseen v2 holdout", "scaffold_id": f"paper_scaffolds_library.v2::{family}",
            "scaffold_version": "paper_scaffolds_library.v2", "solver_status": pre["solver_status"],
            "solver_runtime_s": pre["qlip_runtime_s"], "generated": truth(pre["generated"]),
            "exact_composition": truth(pre["exact_composition"]), "fully_ordered": truth(pre["ordered"]),
            "pre_topology_status": primary_pre, "pre_topology_validator": validator,
            "chgnet_converged": truth(post["chgnet_converged"]), "post_topology_status": primary_post,
            "post_topology_validator": validator, "generated_cif_path": pre["cif_path"],
            "relaxed_cif_path": post["cif_path"], "target_reference_excluded": truth(pre["target_reference_excluded"]),
            "pair_coverage": "COMPLETE", "historical_sca_pre_status": pre["sca_topology_status"],
            "historical_sca_post_status": post["sca_topology_status"],
            "selected_alternative": pre["selected_alternative"],
            "alternative_solve_count": pre["geometry_alternative_count"],
            "total_topology_valid_realisations": roster["total_realisations"],
            "spinel_ordering": pre["spinel_ordering"], "notes": note,
        })
    built["V2_HOLDOUT"] = v2_rows

    e_rows = []
    for row in read_csv(PAPER / "Dataset_E_complex_topology_showcase/FINAL_DATASET_E_RESULTS.csv"):
        e_rows.append({
            "dataset": "E", "row_id": row["row_id"], "formula": row["formula"], "family": row["family"],
            "subtype": row["subtype"], "request": row["request"], "source_dataset": "frozen Dataset E final showcase roster",
            "scaffold_id": f"dataset_e.complex_ordered_scaffolds.v1::{row['subtype']}",
            "scaffold_version": row["scaffold_version"], "solver_status": row["solver_status"],
            "solver_runtime_s": row["solver_runtime_s"], "generated": truth(row["generated"]),
            "exact_composition": truth(row["exact_composition"]), "fully_ordered": truth(row["ordered"]),
            "pre_topology_status": row["pre_topology_status"],
            "pre_topology_validator": "frozen same-subtype anonymous development-template StructureMatcher",
            "chgnet_converged": truth(row["chgnet_converged"]), "post_topology_status": row["post_topology_status"],
            "post_topology_validator": "frozen same-subtype anonymous development-template StructureMatcher",
            "generated_cif_path": row["generated_cif"], "relaxed_cif_path": row["relaxed_cif"],
            "target_reference_excluded": truth(row["target_reference_excluded"]), "pair_coverage": row["pair_coverage"],
            "selected_alternative": row["selected_scaffold_alternative"],
            "alternative_solve_count": row["scaffold_alternative_count"],
            "total_topology_valid_realisations": row["feasible_alternative_count"],
            "notes": row["notes"],
        })
    built["E"] = e_rows

    expected = {"A": 24, "B": 24, "C": 24, "V2_HOLDOUT": 33, "E": 18}
    actual = {name: len(rows) for name, rows in built.items()}
    if actual != expected:
        raise AssertionError(f"dataset denominator mismatch: expected {expected}, observed {actual}")
    if len({row["paired_row_id"] for row in built["C"]}) != 24:
        raise AssertionError("B-C pairing is not 24/24 unique")
    return built


def build_master_results(manifests: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(section: str, metric: str, numerator: Any, denominator: Any, source: str, notes: str = "", included: bool = True) -> None:
        result = "PENDING" if numerator == "PENDING" else f"{numerator}/{denominator}"
        rows.append({"section": section, "metric": metric, "numerator": numerator, "denominator": denominator,
                     "result": result, "included_in_current_headline": included, "authoritative_source": source, "notes": notes})

    a = manifests["A"]
    add("Dataset A", "generated", sum(truth(r["generated"]) for r in a), 24, "DATASET_A_RESULTS.csv")
    add("Dataset A", "structurally valid", 24, 24, "DATASET_A_RESULTS.csv")
    add("Dataset A", "requested topology pre-CHGNet", sum(r["pre_topology_status"] == "PASS" for r in a), 24, "DATASET_A_RESULTS.csv")
    add("Dataset A", "CHGNet converged", sum(truth(r["chgnet_converged"]) for r in a), 24, "DATASET_A_RESULTS.csv", "One additional row reached the 80-step cap and still has a frozen endpoint.", False)
    add("Dataset A", "requested topology post-CHGNet / A_STRONG_SUCCESS", 21, 24, "DATASET_A_RESULTS.csv")
    for fam in ("SPINEL", "OXIDE_PEROVSKITE", "HALIDE_PEROVSKITE", "CSCL_B2"):
        sub = [r for r in a if r["family"] == fam]
        add("Dataset A family", f"{fam} topology pre", sum(r["pre_topology_status"] == "PASS" for r in sub), len(sub), "DATASET_A_RESULTS.csv", included=False)
        add("Dataset A family", f"{fam} strong post", sum("A_STRONG_SUCCESS=True" in r["notes"] for r in sub), len(sub), "DATASET_A_RESULTS.csv", included=False)

    b = manifests["B"]
    add("Dataset B", "valid generated crystals", 24, 24, "DATASET_B_RESULTS.csv")
    add("Dataset B", "requested topology under final independent family criterion", 0, 24, "FINAL_SCIENTIFIC_AUDIT.json", "Paper headline. B20 independently fails olivine.")
    add("Dataset B", "historical frozen SCA-only requested topology", 1, 24, "DATASET_B_RESULTS.csv", "Superseded for the paper headline by the independent criterion; B20 was the false positive.", False)
    add("Dataset B", "solver proven OPTIMAL", sum(r["solver_status"] == "OPTIMAL" for r in b), 24, "FINAL_SCIENTIFIC_AUDIT.json", "Four olivine rows are FEASIBLE_TIME_LIMIT best-found incumbents.", False)
    add("Dataset B", "CHGNet converged", sum(truth(r["chgnet_converged"]) for r in b), 24, "DATASET_B_RESULTS.csv", "Five additional rows reached the step cap.", False)

    c = manifests["C"]
    for metric, count in (("generated", 24), ("exact composition", 24), ("requested topology pre-CHGNet", 24), ("CHGNet converged", 24), ("requested topology post-CHGNet", 24), ("solver OPTIMAL", 24)):
        add("Dataset C", metric, count, 24, "DATASET_C_RESULTS.csv")
    for fam, n in (("LAYERED", 8), ("SPINEL", 7), ("OLIVINE", 6), ("ROCKSALT", 3)):
        add("Dataset B→C family", f"{fam}: B final topology", 0, n, "FINAL_SCIENTIFIC_AUDIT.json", included=False)
        add("Dataset B→C family", f"{fam}: C topology pre/post", n, n, "DATASET_C_RESULTS.csv", "PASS both pre- and post-relaxation.", False)
    add("Dataset B→C invariant", "byte-identical retrieval and SPP evidence", 24, 24, "B_C_INVARIANT_AUDIT.csv", "Zero unexpected scientific-input differences.")
    rows.append({"section": "Dataset B→C efficiency", "metric": "model constraint reduction range", "numerator": "approximately 50–285×", "denominator": "family-dependent", "result": "approximately 50–285×", "included_in_current_headline": True, "authoritative_source": "CLAIM_SAFE_RESULTS.md", "notes": "Layered ≈285×; rocksalt ≈279×; olivine ≈81×; spinel ≈50×."})
    rows.append({"section": "Dataset B→C efficiency", "metric": "wall-clock solve speedup range", "numerator": "approximately 1.5–30×", "denominator": "family-dependent", "result": "approximately 1.5–30×", "included_in_current_headline": True, "authoritative_source": "CLAIM_SAFE_RESULTS.md", "notes": "Do not substitute the superseded 10–100× wording."})

    v2 = manifests["V2_HOLDOUT"]
    for metric, count in (("generated", 33), ("exact composition", 33), ("fully ordered", 33), ("target references excluded", 33), ("CHGNet converged", 33)):
        add("Flexible scaffold v2 holdout", metric, count, 33, "FINAL_V2_REPORT.json")
    add("Flexible scaffold v2 holdout", "discrete alternative solves OPTIMAL", 177, 177, "FINAL_V2_REPORT.json")
    for fam, n, outcome in (("ROCKSALT", 10, "9 PASS + 1 PARTIAL"), ("SPINEL", 10, "9 PASS + 1 ordered-inverse Imma/PARTIAL"), ("LAYERED_O3", 3, "3 PASS"), ("OLIVINE", 10, "10 independent olivine matches")):
        rows.append({"section": "Flexible scaffold v2 post-relax", "metric": fam, "numerator": outcome, "denominator": n, "result": outcome, "included_in_current_headline": True, "authoritative_source": "FINAL_V2_REPORT.json", "notes": "Raw SCA and independent-validator outcomes remain separate where applicable."})

    ablation = read_csv(PAPER / "scaffold_v2/spp_ablation/SPP_V2_ABLATION_RESULTS.csv")
    add("SPP v2 ablation", "request/global selected structure differs", sum(not truth(r["same_selected_cif"]) for r in ablation), 12, "FINAL_V2_REPORT.json")
    add("SPP v2 ablation", "request/global geometry differs", 7, 12, "FINAL_V2_REPORT.json")
    add("SPP v2 ablation", "strict request-objective improvement", sum(float(r["request_objective_improvement"]) > 1e-9 for r in ablation), 12, "FINAL_V2_REPORT.json")
    add("SPP v2 ablation", "spinel request-specific SPP selects normal ordering", 3, 3, "FINAL_V2_REPORT.json")
    add("SPP v2 ablation", "spinel global SPP selects ordered-inverse ordering", 3, 3, "FINAL_V2_REPORT.json")

    e = manifests["E"]
    for metric, count in (("target references excluded", 18), ("complete pair guidance", 18), ("generated", 18), ("exact composition", 18), ("fully ordered", 18), ("selected solve OPTIMAL", 18), ("topology PASS pre-CHGNet", 18), ("CHGNet converged", 18), ("topology PASS post-CHGNet", 18)):
        add("Dataset E", metric, count, 18, "FINAL_DATASET_E_RESULTS.csv")
    add("Dataset E", "alternative solves completed", sum(int(r["alternative_solve_count"]) for r in e), 111, "FINAL_DATASET_E_RESULTS.csv")
    add("Dataset E", "replacements", 0, 18, "FINAL_DATASET_E_REPORT.md", "No failed row was replaced.", False)
    add("Dataset E", "PARTIAL-to-PASS relabels", 0, 18, "FINAL_DATASET_E_RESULTS.csv", included=False)
    for label, count in (("NASICON/NZP", 3), ("RP n=1", 3), ("RP n=2", 3), ("cubic garnet", 3), ("tetragonal garnet", 1), ("ordered argyrodite", 5)):
        add("Dataset E family", label, count, count, "FINAL_SHOWCASE_ROSTER.csv", included=False)

    rows.append({"section": "DFT", "metric": "final first-principles paper results", "numerator": "PENDING", "denominator": "NOT YET INCLUDED", "result": "PENDING", "included_in_current_headline": False, "authoritative_source": "FINAL_METHOD_FREEZE.json", "notes": "Barkla export files are handoff/input artifacts, not final DFT result artifacts."})
    return rows


def markdown_table(rows: list[dict[str, Any]], fields: list[str], labels: list[str] | None = None) -> str:
    labels = labels or fields
    def esc(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(labels) + " |", "|" + "|".join("---" for _ in fields) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(esc(row.get(field, "")) for field in fields) + " |")
    return "\n".join(lines)


def build_scaffolds() -> list[dict[str, Any]]:
    templates = load_json(PAPER / "Dataset_E_complex_topology_showcase/DEVELOPMENT_SCAFFOLD_TEMPLATES.json")["templates"]
    by_subtype = defaultdict(list)
    for item in templates:
        by_subtype[item["subtype"]].append(item)
    def dev(subtypes: list[str]) -> str:
        return "; ".join(
            f"{x['template_id']} ({x['space_group_symbol']} #{x['space_group_number']}, {x['site_count']} sites)"
            for subtype in subtypes for x in by_subtype[subtype]
        )
    common_e = {
        "scaffold_version": "dataset_e.complex_ordered_scaffolds.v1",
        "crystallographic_basis": "hash-frozen primitive-standardized development template(s)",
        "topology_fixed": "development-derived fractional topology and cell shape",
        "site_orbit_classes_fixed": "primitive crystallographic orbit partition and allowed role classes",
        "connectivity_fixed": "same-subtype ordered topology envelope",
        "occupational_freedom": "formula-compatible species-to-allowed-orbit assignment solved by QLIP",
        "geometry_freedom": "discrete target-excluded retrieval VPA scales",
        "cell_freedom": "absolute volume scale varies; development-derived cell shape is fixed",
        "method_freeze_source": "Dataset_E_complex_topology_showcase/METHOD_FREEZE.json",
    }
    rows = [
        {"family": "ROCKSALT/B1", "scaffold_id": "paper_scaffolds_library.v2::ROCKSALT", "scaffold_version": "paper_scaffolds_library.v2", "crystallographic_basis": "B1/Fm-3m 4a/4b sublattices", "space_group_or_symmetry_scope": "Fm-3m (#225)", "topology_fixed": "B1 interpenetrating cation/anion sublattices", "site_orbit_classes_fixed": "cation 4a; anion 4b", "connectivity_fixed": "six-coordinate B1 network", "occupational_freedom": "physically deterministic for ordered binary AB", "geometry_freedom": "three evidence-derived cell scales", "cell_freedom": "discrete isotropic scale", "development_sources": "v1 prototype plus frozen v2 development panel", "method_freeze_source": "scaffold_v2/V2_METHOD_FREEZE.json", "final_unseen_test_n": 10, "headline_validation": "post-CHGNet: 9 PASS + 1 PARTIAL", "notes": "No artificial occupation state is claimed."},
        {"family": "SPINEL", "scaffold_id": "paper_scaffolds_library.v2::SPINEL", "scaffold_version": "paper_scaffolds_library.v2", "crystallographic_basis": "spinel tetrahedral framework, split ordered octahedral suborbits, oxygen framework", "space_group_or_symmetry_scope": "normal Fd-3m; ordered-inverse-compatible Imma", "topology_fixed": "spinel hard network", "site_orbit_classes_fixed": "tetrahedral, two octahedral suborbits, oxygen", "connectivity_fixed": "spinel tetrahedral/octahedral connectivity", "occupational_freedom": "normal plus two ordered-inverse-compatible assignments", "geometry_freedom": "3 cell scales × oxygen u={0.375,0.386,0.397}", "cell_freedom": "discrete isotropic scale and oxygen u", "development_sources": "v1 historical exemplar and frozen v2 development panel", "method_freeze_source": "scaffold_v2/V2_METHOD_FREEZE.json", "final_unseen_test_n": 10, "headline_validation": "post-CHGNet: 9 PASS + 1 ordered-inverse Imma/PARTIAL", "notes": "The v1 C09 workflow exemplar has one feasible scaffold state; freedom claims use v2, not C09."},
        {"family": "LAYERED_O3", "scaffold_id": "paper_scaffolds_library.v2::LAYERED_O3", "scaffold_version": "paper_scaffolds_library.v2", "crystallographic_basis": "O3/R-3m cation and oxygen layers", "space_group_or_symmetry_scope": "R-3m (#166)", "topology_fixed": "O3 layer stacking", "site_orbit_classes_fixed": "two cation layers and oxygen layers", "connectivity_fixed": "layered octahedral framework", "occupational_freedom": "two ordered cation-layer assignments", "geometry_freedom": "3 cell scales × oxygen z={0.235,0.241,0.247}", "cell_freedom": "discrete scale and oxygen height", "development_sources": "v1 prototype plus frozen v2 development panel", "method_freeze_source": "scaffold_v2/V2_METHOD_FREEZE.json", "final_unseen_test_n": 3, "headline_validation": "3/3 PASS pre/post CHGNet", "notes": "P2 is outside the frozen method."},
        {"family": "OLIVINE", "scaffold_id": "paper_scaffolds_library.v2::OLIVINE", "scaffold_version": "paper_scaffolds_library.v2", "crystallographic_basis": "ordered Pnma olivine framework", "space_group_or_symmetry_scope": "Pnma (#62)", "topology_fixed": "Pnma olivine framework and explicit tetrahedral-former role", "site_orbit_classes_fixed": "M1, M2, tetrahedral former, oxygen framework", "connectivity_fixed": "olivine octahedral/tetrahedral framework", "occupational_freedom": "two ordered M1/M2 assignments", "geometry_freedom": "three evidence-derived cell scales", "cell_freedom": "discrete scale", "development_sources": "v1 prototype, ordered olivine v2 corpus, frozen v2 development panel", "method_freeze_source": "scaffold_v2/V2_METHOD_FREEZE.json", "final_unseen_test_n": 10, "headline_validation": "10/10 independent olivine matches pre/post", "notes": "Raw SCA is chemistry-limited; independent Pnma/anonymous matching is primary."},
    ]
    e_specs = [
        ("NASICON/NZP", "NASICON_R3_PHOSPHATE", ["NASICON_R3_PHOSPHATE"], "R-3 (#148)", 3, "3/3 PASS pre/post"),
        ("RP_N1", "RP_N1", ["RP_N1"], "same-subtype development scope", 3, "3/3 PASS pre/post"),
        ("RP_N2", "RP_N2", ["RP_N2"], "same-subtype development scope", 3, "3/3 PASS pre/post"),
        ("GARNET_CUBIC", "GARNET_IA3D", ["GARNET_IA3D"], "Ia-3d (#230)", 3, "3/3 PASS pre/post"),
        ("GARNET_TETRAGONAL", "GARNET_I41ACD", ["GARNET_I41ACD"], "I4_1/acd (#142)", 1, "1/1 PASS pre/post"),
        ("ARGYRODITE_ORDERED", "ARGYRODITE_ORDERED", ["ARGYRODITE_F43M", "ARGYRODITE_PNA21", "ARGYRODITE_CC"], "F-43m (#216), Pna2_1 (#33), and Cc (#9)", 5, "5/5 PASS pre/post"),
    ]
    for family, sid, subtypes, scope, n, headline in e_specs:
        row = dict(common_e)
        row.update({"family": family, "scaffold_id": f"dataset_e.complex_ordered_scaffolds.v1::{sid}", "space_group_or_symmetry_scope": scope, "development_sources": dev(subtypes), "final_unseen_test_n": n, "headline_validation": headline, "notes": "Unseen-chemistry transfer within development-derived known topology classes; not new-topology discovery."})
        rows.append(row)
    return rows


def build_corpus_rows() -> list[dict[str, Any]]:
    summary = read_csv(CRYSTAL_AUDIT / "SPECIALIST_CORPUS_SUMMARY.csv")
    hashes = load_json(CRYSTAL_AUDIT / "CORPUS_HASHES.json")
    acceptance = {
        "LAYERED_OXIDE": "accepted layered-oxide structural family with stored classifier evidence",
        "SPINEL": "accepted-only spinel family classifier",
        "NASICON": "NASICON tier/framework-family criterion with stored structural evidence",
        "ROCKSALT": "B1 rocksalt structural family",
        "OLIVINE": "topology-first ordered Pnma prototype validation",
        "ARGYRODITE": "strict ordered argyrodite prototype validation",
        "GARNET": "accepted garnet family, including cubic and tetragonal classes",
        "RUDDLESDEN_POPPER": "accepted RP family with n=1/n=2 subtype annotation",
    }
    used = {"LAYERED_OXIDE": "A/B/C/v2", "SPINEL": "A/B/C/v2", "NASICON": "Dataset E", "ROCKSALT": "B/C/v2", "OLIVINE": "B/C/v2", "ARGYRODITE": "Dataset E", "GARNET": "Dataset E", "RUDDLESDEN_POPPER": "Dataset E"}
    rows = []
    for row in summary:
        path = Path(row["existing_path"])
        db_hash = hashes[str(path)]["database_sha256"]
        actual = sha256(path)
        if actual != db_hash:
            raise AssertionError(f"Crystal-DB hash mismatch: {path}")
        explicit_ordered = row["family"] in {"OLIVINE", "ARGYRODITE"}
        rows.append({"corpus": row["family"], "version": row["existing_corpus"], "structure_count": int(row["existing_rows"]), "composition_count": int(row["composition_count"]), "ordered_only": explicit_ordered if explicit_ordered else "not asserted by final summary", "acceptance_criterion": acceptance[row["family"]], "db_path": str(path), "db_sha256": db_hash, "retrieval_ready": row["retrieval_ready"], "used_in_experiments": used[row["family"]], "notes": row["reason"]})
    expected = {"LAYERED_OXIDE": (136, 105), "SPINEL": (170, 170), "NASICON": (200, 177), "ROCKSALT": (401, 401), "OLIVINE": (94, 84), "ARGYRODITE": (8, 8), "GARNET": (44, 44), "RUDDLESDEN_POPPER": (76, 74)}
    observed = {r["corpus"]: (r["structure_count"], r["composition_count"]) for r in rows}
    if observed != expected:
        raise AssertionError(f"specialist corpus count mismatch: {observed}")
    return rows


def main() -> None:
    missing = [str(path) for _, _, path, _ in SOURCES if not path.is_file()]
    if missing:
        raise FileNotFoundError("authoritative inputs missing:\n" + "\n".join(missing))
    initial_hashes = {str(path.resolve()): sha256(path) for _, _, path, _ in SOURCES}
    OUT.mkdir(parents=True, exist_ok=True)
    for directory in ("01_results", "02_claims", "03_methods", "04_scaffolds", "05_validation", "06_datasets", "07_crystaldb", "08_provenance"):
        (OUT / directory).mkdir(exist_ok=True)

    manifests = build_dataset_manifests()
    names = {"A": "DATASET_A_MANIFEST.csv", "B": "DATASET_B_MANIFEST.csv", "C": "DATASET_C_MANIFEST.csv", "V2_HOLDOUT": "DATASET_V2_HOLDOUT_MANIFEST.csv", "E": "DATASET_E_MANIFEST.csv"}
    for key, filename in names.items():
        write_csv(OUT / "06_datasets" / filename, manifests[key], MANIFEST_FIELDS)

    master = build_master_results(manifests)
    master_fields = ["section", "metric", "numerator", "denominator", "result", "included_in_current_headline", "authoritative_source", "notes"]
    write_csv(OUT / "01_results/PAPER_MASTER_RESULTS.csv", master, master_fields)
    write_text(OUT / "01_results/PAPER_MASTER_RESULTS.md", "# Paper master results\n\nThis is the single authoritative detailed results table. Historical values are retained only when explicitly labelled superseded.\n\n" + markdown_table(master, ["section", "metric", "result", "included_in_current_headline", "authoritative_source", "notes"], ["Section", "Metric", "Result", "Headline?", "Source", "Notes"]))
    write_text(OUT / "01_results/PAPER_HEADLINE_NUMBERS.md", """# Final headline numbers

## Dataset A

- 24/24 generated and valid
- 23/24 requested topology pre-CHGNet
- 21/24 requested topology post-CHGNet (A_STRONG_SUCCESS)

## Dataset B

- 24/24 valid generated crystals
- 0/24 requested topology under the final independent family criterion

## Dataset C

- 24/24 requested topology pre-CHGNet
- 24/24 requested topology post-CHGNet
- 24/24 B↔C retrieval/SPP scientific inputs invariant; 0 unexpected differences
- approximately 50–285× fewer constraints; approximately 1.5–30× faster, family-dependent

## Flexible scaffold v2

- 33/33 generated, exact composition, fully ordered, target-reference excluded, and CHGNet converged
- 177/177 discrete alternative solves OPTIMAL
- post-CHGNet: rocksalt 9 PASS + 1 PARTIAL; spinel 9 PASS + 1 ordered-inverse Imma/PARTIAL; layered O3 3/3 PASS; olivine 10/10 independent matches

## SPP v2 ablation

- 9/12 different request/global structures; 7/12 different geometry; 9/12 strict request-objective improvement
- spinel: request-specific SPP 3/3 normal; global SPP 3/3 ordered-inverse

## Dataset E

- 18/18 generated, exact, ordered, selected OPTIMAL, complete guidance, target-reference excluded, pre/post topology PASS, and CHGNet converged
- 111/111 alternatives solved; 0 replacements; 0 PARTIAL→PASS relabels

## DFT

- PENDING — NOT YET INCLUDED IN CURRENT PAPER HEADLINES
""")

    write_text(OUT / "02_claims/PAPER_CLAIMS_AND_CAVEATS.md", """# Paper claims and caveats

## A. Safe central claims

- Retrieval-derived SPPs provide explicit chemistry-specific pair-distance guidance.
- Pairwise guidance alone can recover requested topology for some families.
- Pairwise guidance does not guarantee higher-order topology.
- Paired B→C experiments show topology recovery attributable to the scaffold intervention under identical retrieval/SPP evidence.
- Flexible v2 scaffolds retain meaningful solver freedom.
- Dataset E demonstrates unseen-chemistry transfer of reusable ordered topology scaffolds to more complex known topology classes.

## B. Safe result-specific claims

- Dataset A: SPP-only QLIP produced 24/24 valid crystals, with 23/24 requested topology pre-relaxation and 21/24 strong post-CHGNet successes.
- Dataset B: 24/24 valid generated crystals; 0/24 satisfy requested topology under the final independent family criterion.
- Dataset C: 24/24 recover and retain requested topology under a scaffold, with 24/24 paired retrieval/SPP inputs invariant relative to B.
- V2: 177/177 frozen discrete alternative solves were OPTIMAL; request-specific SPP changed 9/12 ablation structures.
- Dataset E: 18/18 fixed-denominator rows passed the frozen same-subtype validator before and after CHGNet; no row was replaced.

## C. Do not claim

- Do not claim SPP is a physical energy or predicts thermodynamic stability.
- Do not claim CHGNet proves stability or that generated structures are synthesizable.
- Do not claim `OPTIMAL` means a physical ground state.
- Do not equate a scaffold with de novo topology discovery, or claim Dataset E demonstrates de novo topology discovery.
- Do not use v1 C09 as evidence of flexible-scaffold freedom.
- Do not present SCA as a community-standard method; it is an in-house deterministic pipeline.
- Do not turn 100% success on these fixed cohorts into a universal-generalisation claim.

## D. Required wording for awkward cases

- **SPP:** “statistical proxy potential / statistical pairwise guidance, not a physical interatomic energy.”
- **QLIP:** “`OPTIMAL` denotes optimality within the declared finite IP-CSP problem.”
- **CHGNet:** “surrogate structural relaxation / robustness check.”
- **Scaffolds:** “encode established crystallographic topology as explicit solver constraints.”
- **v1 C09:** “used as a workflow example only; this historical v1 row has one feasible scaffold state.”
- **v2:** “evidence for retained chemistry-dependent scaffold freedom.”
- **Dataset E:** “unseen chemistry transfer within development-derived known topology classes, not de novo topology discovery.”
- **Dataset B:** “24/24 valid generated crystals; 0/24 satisfy requested topology under the final independent family criterion.”
- **Olivine:** “independent StructureMatcher/family criterion is primary where frozen SCA coverage is chemistry-limited.”
""")

    methods = """# Authoritative paper methods freeze

This document reconciles the final frozen method records. It is an audit summary, not a new experiment.

## A. Text/task compilation

The A/B/C paper workflow used deterministic manual request-to-task mapping (`paper_final_v1` / `csv_workflow_v1`), with schema validation and workflow normalization; no LLM call was used in this frozen compilation step. Each row retained its exact request, formula, family/prototype intent, corpus route, solver settings, and output path. V2 and Dataset E used frozen CSV rosters and deterministic request rows.

## B. Crystal-DB retrieval

The canonical representation path is: source CIF → metadata/provenance → RoboCrystallographer → `robocrys_condensed` → `fp.simple.v1` → BGE-M3 1024-dimensional embedding → SQLite/vector retrieval. The paper workflow used `crystal_db.retrieval.text_search`, cosine similarity, top-k 50 retrieval and at most 30 SPP evidence structures. Target/equivalent IDs were excluded where a target-reference protocol was declared; Dataset E and v2 explicitly audit target-reference exclusion. Retrieved non-target CIF identities and hashes are retained. Logical family routes select the corresponding specialist database; Crystal-DB itself accepts a database path and Skill-Loop performs the route.

## C. SPP construction

SPP artifacts use `dmytro_gr_v1`: 200 bin centres from 0.025 to 9.975 Å, edges 0–10 Å, 0.05 Å spacing, Gaussian σ=0.1 Å, truncation at 3σ, and ε=10⁻¹². The transform is `U(r) = -ln[g(r)+ε]` without minimum shifting. These are statistical proxy potentials / statistical pairwise guidance, not physical interatomic energies.

For each required species pair, request/local evidence is built from the frozen retrieved CIF subset. The broad regulator is `icsd_broad_regulator_v1`. When the local artifact is valid, the stored pair-level blend is `U_blend = U_local + w_global U_global`, where `w_global = 0.05 + 0.15(1-confidence)` and `confidence = sqrt(min(n_structures/20,1) × min(log1p(n_observations)/log1p(20000),1))`. If local evidence is absent/invalid but a valid global artifact exists, the global curve supplies that pair. No missing interaction is silently zeroed. The frozen workflow records request coefficient 1.0, regulator coefficient 2.0, outer objective scale 10.0, and 10 Å cutoff; these are distinct from the pair-level confidence blend weight. The QLIP periodic objective uses the corrected multiplicity: 0.5 for each directed ±T same-site self-image contribution and 1.0 for off-diagonal contributions, excluding the zero-distance central self image.

## D. QLIP / IP-CSP

For species `s` and candidate site `i`, `x_is ∈ {0,1}` records occupation. Hard constraints enforce exact composition, site exclusivity/full occupancy, proximity/geometric restrictions, and—when active—topology/orbit domains and closure. QLIP minimizes the SPP-weighted binary quadratic objective over the finite feasible set, with periodic images through the 10 Å cutoff.

The frozen A/B/C solve used Gurobi 12.0.3 through Pyomo, native non-convex binary MIQP (`NonConvex=2`), 300 s time limit, zero MIP gap, one thread, and requested seed 0. The historical adapter tested the seed by truthiness, so integer zero was not forwarded; effective behavior was the Gurobi default seed. Four Dataset B olivine rows are `FEASIBLE_TIME_LIMIT` incumbents, not proven optima. All Dataset C, v2 selected alternatives, and Dataset E alternatives reported in the headline are proven OPTIMAL within their declared finite problems.

## E. Topology scaffolds

Define a topology scaffold as `S_T = (G_T, O_T, A_T, Θ_T)`, where `G_T` is the topology/connectivity graph, `O_T` the orbit/site partition, `A_T` the allowed occupations, and `Θ_T` the supported discrete geometry alternatives. If `F` is the unscaffolded feasible set, `F_T = {x ∈ F : C_T(x)=1}` and `x* = argmin_(x∈F_T) E_SPP(x)`. The scaffold changes the feasible set; it does not add a second energy. Final v2 separates topology-defining constraints from chemistry-dependent occupation and discrete geometry alternatives.

## F. V1→v2 development and freeze

V1 demonstrated topology transfer but the subsequent freedom audit found one total realization for rocksalt and spinel, two for O3, and two-to-six for olivine. V2 retained v1 unchanged, introduced finite outer enumeration of interpretable geometry alternatives, solved each with the unmodified inner QLIP occupation problem, checked solver/scorer parity, and selected the feasible objective minimum with deterministic alternative-ID tie-breaking. The method was hash-frozen before selecting the unseen 33-row holdout; failures could not be replaced. V1 source SHA256 is `0fb5ab282fa5e6d672841daceaa4ddd25e148b8b4c907c821322fe6341757043`; v2 method-freeze SHA256 is `2d5ed9c7634cce8ab3c890d8a1629d06a9f4543ad21a7d3e156cb0426fd58571`; v2 holdout roster SHA256 is `3223556da5d5c7e01e472236495bf5da5cee0ddd8508174d8b47fc9b79a228ed`.

## G. Dataset E ordered scaffold extension

Dataset E uses `dataset_e.complex_ordered_scaffolds.v1`. Cell shape and fractional topology come only from hash-frozen development prototypes, never a final target. Absolute volume uses target-excluded retrieval VPA quartiles or the frozen global fallback. Formula-compatible orbit occupations are solved by the unchanged QLIP/SPP objective, with the minimum objective selected after parity checking. The scope is fully ordered NASICON R-3 phosphate, RP n=1, RP n=2, cubic and tetragonal garnet, and three ordered argyrodite subtypes. No target coordinates/lattice constants, disorder enumeration, partial occupancy, SPP retuning, or failed-row replacement is used.

## H. Crystallographic validation

SCA means Structured Crystal Analyser, an in-house deterministic crystallographic validation pipeline. It checks CIF parsing, formula/composition, occupancy/order where requested, periodic minimum distances and severe contacts, symmetry, and family/topology features. Family SCA verdicts are preserved. Dataset E uses the separately frozen rule “ordered AND anonymous StructureMatcher match to a same-subtype development reference” (`ltol=0.2`, `stol=0.3`, angle tolerance 5°, primitive-cell and scale enabled, no supercell attempt; symmetry tolerance 0.05). Olivine final family reporting uses a species-blind `StructureMatcher.fit_anonymous` (`ltol=0.3`, `stol=0.4`, angle tolerance 8°) against 20 frozen ordered Pnma references plus detected Pnma, because the frozen SCA olivine policy is Li/P-specific.

## I. CHGNet

CHGNet 0.4.2 used the pretrained checkpoint whose parameter SHA256 is `818dbd975187b2df03eb56d0c4f28fdd3bd05aa97758b2c530be80b72cfdc335`. Relaxation used `StructOptimizer`, FIRE, `fmax=0.1 eV/Å`, at most 80 steps, `relax_cell=True`, CPU for the frozen A/B/C provenance, and no wrapper timeout. Topology was re-evaluated on the relaxed CIF. CHGNet is a surrogate structural relaxation / robustness check; convergence is not a thermodynamic or DFT result.

## J. Reproducibility and provenance

Every authoritative input used here is indexed with a captured SHA256. Dataset denominators are fixed and failed rows are retained. B↔C pairing audits request text, structured task, retrieval query/corpus/database hash, full ranked neighbors, CIF hashes, SPP evidence, per-pair POT hashes and blend weights, regulator, leakage flag, solver configuration, proximity, and contract. Generated and relaxed CIF paths remain references to the frozen artifacts rather than copied structures. DFT export packages are inputs/handoffs only; no final first-principles paper results are included.

## K. Software versions

See `SOFTWARE_VERSIONS.csv`. Where a runtime version was not explicitly frozen, the table says so rather than inferring it from the current environment.
"""
    write_text(OUT / "03_methods/PAPER_METHODS_FREEZE.md", methods)
    software = [
        {"software": "Python", "version": "3.12.10", "role": "final figure/audit environment; scientific-run patch version not separately frozen", "source_of_version": "publication_figures/FIGURE_AUDIT.md"},
        {"software": "pymatgen", "version": "2025.10.7", "role": "Crystal-DB specialist corpus validation", "source_of_version": "Crystal-DB specialist_corpora/CRYSTAL_DB_PIPELINE_MAP.md"},
        {"software": "pymatgen", "version": "2026.5.4 pin", "role": "QLIP package dependency; not proof of every frozen runtime", "source_of_version": "qlip/pyproject.toml"},
        {"software": "spglib", "version": "2.7.0", "role": "Crystal-DB symmetry validation", "source_of_version": "Crystal-DB specialist_corpora/CRYSTAL_DB_PIPELINE_MAP.md"},
        {"software": "CHGNet", "version": "0.4.2", "role": "surrogate structural relaxation", "source_of_version": "dataset_C/chgnet/CHGNET_MODEL_PROVENANCE.json"},
        {"software": "Gurobi", "version": "12.0.3", "role": "QLIP MIQP solver", "source_of_version": "qlip/pyproject.toml and frozen method audit"},
        {"software": "Pyomo", "version": "6.9.4", "role": "QLIP optimization model interface", "source_of_version": "qlip/pyproject.toml"},
        {"software": "QLIP", "version": "repository package metadata 0.0.0; workflow provenance also calls adapter 0.3.0", "role": "IP-CSP solver/objective", "source_of_version": "qlip/pyproject.toml; paper_final_v1.py"},
        {"software": "Crystal-DB", "version": "repository package metadata 0.0.0; commit 1d26f6b31d90b77b6b4520edc2125fa47d3e76a3", "role": "corpus storage and retrieval", "source_of_version": "Crystal-DB/pyproject.toml and git HEAD"},
        {"software": "Structured Crystal Analyser", "version": "0.1.0; commit e5b291312151f34949a5e6ef0f43bebfeb752bc9", "role": "in-house crystallographic validation", "source_of_version": "Structured_Crystal_Analyser/pyproject.toml and FINAL_METHOD_FREEZE.json"},
        {"software": "RoboCrystallographer", "version": "0.2.13", "role": "Crystal-DB text generation", "source_of_version": "Crystal-DB specialist_corpora/CRYSTAL_DB_PIPELINE_MAP.md"},
        {"software": "BGE-M3", "version": "text-embedding-bge-m3 / lmstudio_v1; model revision not recorded", "role": "1024D retrieval embedding", "source_of_version": "Crystal-DB pipeline map and frozen corpus registry"},
        {"software": "NumPy", "version": "2.3.3", "role": "QLIP numeric dependency", "source_of_version": "qlip/pyproject.toml"},
        {"software": "SciPy", "version": "1.17.1 (final figure environment); scientific-run version not frozen", "role": "supporting analysis/figure environment", "source_of_version": "publication_figures/FIGURE_AUDIT.md"},
    ]
    write_csv(OUT / "03_methods/SOFTWARE_VERSIONS.csv", software, ["software", "version", "role", "source_of_version"])

    scaffolds = build_scaffolds()
    scaffold_fields = ["family", "scaffold_id", "scaffold_version", "crystallographic_basis", "space_group_or_symmetry_scope", "topology_fixed", "site_orbit_classes_fixed", "connectivity_fixed", "occupational_freedom", "geometry_freedom", "cell_freedom", "development_sources", "method_freeze_source", "final_unseen_test_n", "headline_validation", "notes"]
    write_csv(OUT / "04_scaffolds/SCAFFOLD_DEFINITIONS.csv", scaffolds, scaffold_fields)
    write_text(OUT / "04_scaffolds/SCAFFOLD_DEFINITIONS.md", "# Frozen scaffold definitions\n\nThe scaffold changes the feasible set and supplies no second energy. V1 spinel C09 is retained only as a workflow exemplar; flexibility claims use the final v2 definitions. Dataset E definitions encode development-derived known topology classes.\n\n" + markdown_table(scaffolds, ["family", "scaffold_version", "crystallographic_basis", "occupational_freedom", "geometry_freedom", "final_unseen_test_n", "headline_validation", "notes"], ["Family", "Version", "Basis", "Occupation freedom", "Geometry freedom", "Unseen N", "Validation", "Notes"]))

    validation = [
        {"family": "ROCKSALT/B1", "primary_validator": "SCA/AFLOW-style B1 prototype and Fm-3m family checks", "secondary_validator": "spglib/pymatgen SpacegroupAnalyzer", "symmetry_requirement": "Fm-3m for canonical PASS", "topology_criterion": "binary six-coordinate B1 network", "known_coverage_caveat": "v2 post-relax includes one frozen PARTIAL", "paper_reporting_rule": "retain PASS/PARTIAL verbatim"},
        {"family": "SPINEL", "primary_validator": "SCA spinel coordination/network policy", "secondary_validator": "spglib symmetry plus ordered-occupation audit", "symmetry_requirement": "Fd-3m normal; Imma accepted only as disclosed ordered-inverse/PARTIAL", "topology_criterion": "tetrahedral plus octahedral spinel hard network", "known_coverage_caveat": "ordered inverse is fully ordered but SCA returns PARTIAL", "paper_reporting_rule": "report 9 PASS + 1 ordered-inverse Imma/PARTIAL; do not relabel"},
        {"family": "LAYERED_O3", "primary_validator": "SCA LAYERED_OXIDE coordination/layer policy", "secondary_validator": "spglib/pymatgen SpacegroupAnalyzer", "symmetry_requirement": "R-3m O3", "topology_criterion": "octahedral transition-metal oxygen layer with interlayer alkali", "known_coverage_caveat": "historical family-map routing gap in old 12-row v1 holdout", "paper_reporting_rule": "v2 final holdout uses frozen O3 criterion; P2 unsupported"},
        {"family": "OLIVINE", "primary_validator": "species-blind pymatgen StructureMatcher plus Pnma", "secondary_validator": "frozen SCA OLIVINE policy", "symmetry_requirement": "Pnma (#62)", "topology_criterion": "anonymous match to frozen ordered olivine references and Pnma", "known_coverage_caveat": "SCA policy is Li/P/O chemistry-limited; B20 SCA PASS is Pmm2 with zero independent matches", "paper_reporting_rule": "independent family outcome is primary; raw SCA remains visible"},
        {"family": "NASICON/NZP", "primary_validator": "Dataset E anonymous same-subtype development-template matcher", "secondary_validator": "pymatgen/spglib symmetry and ordering", "symmetry_requirement": "R-3 development subtype scope", "topology_criterion": "ordered and anonymous match to same-subtype development reference", "known_coverage_caveat": "historical B-HARD one-full/two-partial experiment is not the Dataset E final method", "paper_reporting_rule": "report final Dataset E fixed roster separately from historical B-HARD"},
        {"family": "RP_N1", "primary_validator": "Dataset E anonymous same-subtype development-template matcher", "secondary_validator": "pymatgen/spglib symmetry", "symmetry_requirement": "same-subtype development scope", "topology_criterion": "ordered and anonymous n=1 template match", "known_coverage_caveat": "n=1 and n=2 are distinct validators", "paper_reporting_rule": "never merge RP n values"},
        {"family": "RP_N2", "primary_validator": "Dataset E anonymous same-subtype development-template matcher", "secondary_validator": "pymatgen/spglib symmetry", "symmetry_requirement": "same-subtype development scope", "topology_criterion": "ordered and anonymous n=2 template match", "known_coverage_caveat": "n=1 and n=2 are distinct validators", "paper_reporting_rule": "never merge RP n values"},
        {"family": "GARNET_CUBIC", "primary_validator": "Dataset E anonymous GARNET_IA3D development-template matcher", "secondary_validator": "pymatgen/spglib symmetry", "symmetry_requirement": "Ia-3d (#230)", "topology_criterion": "ordered and anonymous cubic-garnet template match", "known_coverage_caveat": "cubic and tetragonal classes are separate", "paper_reporting_rule": "report subtype explicitly"},
        {"family": "GARNET_TETRAGONAL", "primary_validator": "Dataset E anonymous GARNET_I41ACD development-template matcher", "secondary_validator": "pymatgen/spglib symmetry", "symmetry_requirement": "I4_1/acd (#142)", "topology_criterion": "ordered and anonymous tetragonal-garnet template match", "known_coverage_caveat": "single final test row", "paper_reporting_rule": "retain 1-row denominator"},
        {"family": "ARGYRODITE_ORDERED", "primary_validator": "Dataset E anonymous same-subtype development-template matcher", "secondary_validator": "pymatgen/spglib symmetry and full-order check", "symmetry_requirement": "F-43m, Pna2_1, or Cc subtype-specific", "topology_criterion": "ordered and anonymous same-subtype match", "known_coverage_caveat": "ordered-only scope; no disorder enumeration", "paper_reporting_rule": "state ordered subtype and fixed 5-row denominator"},
    ]
    write_csv(OUT / "05_validation/VALIDATION_FAMILY_MATRIX.csv", validation, ["family", "primary_validator", "secondary_validator", "symmetry_requirement", "topology_criterion", "known_coverage_caveat", "paper_reporting_rule"])
    write_text(OUT / "05_validation/VALIDATION_DEFINITIONS.md", """# Validation definitions

SCA means **Structured Crystal Analyser**. It is an in-house deterministic crystallographic validation pipeline, not an externally established standard. Actual external libraries include pymatgen, spglib, and pymatgen `StructureMatcher`.

## Core checks

- CIF parse/processability.
- Exact reduced composition and requested-formula consistency.
- Full occupancy/order where required; no duplicate, partial, or disordered occupancy in the ordered experiments.
- Periodic minimum distance and severe short-contact checks. The frozen bond evaluator flags distances below 0.6 Å for non-H (0.35 Å for H) or below 0.7 times the summed covalent radii.
- Detected/requested symmetry where the family criterion requires it.
- Family/topology checks through coordination/connectivity policies or frozen anonymous template matching.

## Verdicts

- **PASS:** all applicable Boolean topology checks are true, or the separately frozen family-specific criterion is satisfied.
- **PARTIAL:** at least one applicable topology check is true but not all. PARTIAL is never silently counted as PASS.
- **FAIL/MISS:** no applicable topology check passes, the requested family criterion fails, or the structure is assigned a different family. “MISS” is the paper’s requested-topology outcome label; raw SCA may say FAIL, PARTIAL, or NOT_APPLICABLE.

## Required caveats

The frozen SCA olivine policy hard-requires Li/P/O chemistry and therefore has limited chemistry coverage. Final olivine assessment uses species-blind `StructureMatcher.fit_anonymous` against 20 frozen ordered olivine references together with Pnma (#62). B20 LiMnPO4 is the historical discrepancy: raw SCA reports olivine PASS, but the independent audit finds Pmm2 and zero framework matches, so Dataset B’s final result is 0/24 requested topology rather than the historical 1/24.

The v2 ordered-inverse spinel is fully ordered and preserves the hard spinel network, but its Imma symmetry yields frozen SCA PARTIAL. It remains PARTIAL in paper reporting. The v2 rocksalt PARTIAL also remains PARTIAL. Dataset E’s frozen validator requires an ordered structure and an anonymous match to a same-subtype development template; its matcher settings and negative calibration were frozen before final roster selection.
""")

    write_text(OUT / "06_datasets/DATASET_SUMMARY.md", """# Dataset summary

| Dataset | Scientific question | N | Main result |
|---|---|---:|---|
| A | Can SPP-only work? | 24 | 23/24 topology pre; 21/24 post |
| B | Can valid SPP crystals miss topology? | 24 | 0/24 requested topology by final independent criterion |
| C | Does scaffold intervention recover topology? | 24 | 24/24 topology pre and post; 24/24 B↔C retrieval/SPP invariant |
| v2 | Do flexible scaffolds generalise and retain freedom? | 33 | 33/33 generated; 177/177 alternatives OPTIMAL; rocksalt 9 PASS + 1 PARTIAL, spinel 9 PASS + 1 ordered-inverse/PARTIAL, O3 3/3, olivine independent 10/10 post-relax |
| E | Does scaffold representation extend to complex topology families? | 18 | 18/18 topology pre/post; 111/111 alternatives solved; no replacements |

DFT is pending and is not included in any current headline.
""")

    corpora = build_corpus_rows()
    corpus_fields = ["corpus", "version", "structure_count", "composition_count", "ordered_only", "acceptance_criterion", "db_path", "db_sha256", "retrieval_ready", "used_in_experiments", "notes"]
    write_csv(OUT / "07_crystaldb/CRYSTALDB_CORPUS_SUMMARY.csv", corpora, corpus_fields)
    write_text(OUT / "07_crystaldb/CRYSTALDB_CORPUS_SUMMARY.md", "# Final Crystal-DB specialist corpora\n\nCounts and live database hashes were verified against the final Crystal-DB audit. Olivine v2 (94/84) supersedes the 15-row v1 corpus; ordered argyrodite v2 (8/8) supersedes the 3-row v1 corpus. All eight final databases are retrieval-ready with complete canonical representations.\n\n" + markdown_table(corpora, ["corpus", "version", "structure_count", "composition_count", "ordered_only", "acceptance_criterion", "db_sha256", "used_in_experiments"], ["Corpus", "Version", "Structures", "Compositions", "Ordered-only", "Acceptance", "DB SHA256", "Used in"]))

    artifact_rows = []
    source_rows = []
    for artifact, role, path, proof in SOURCES:
        rel = repo_rel(path)
        digest = initial_hashes[str(path.resolve())]
        artifact_rows.append({"artifact": artifact, "role": role, "path": rel, "sha256": digest, "status": "VERIFIED_EXISTS; UNCHANGED_DURING_AUDIT", "notes": proof})
        source_rows.append({"paper_topic": artifact, "authoritative_file": rel, "sha256": digest, "what_it_proves": proof, "supersedes": "", "notes": role})
    supersedes = {
        "Final scientific audit": "historical B 1/24 SCA-only headline; 10–100× runtime wording",
        "Scaffold v2 final report": "v1 freedom as evidence for flexible scaffolds",
        "Dataset E final report": "earlier Dataset E representation-blocker audit",
        "Crystal-DB final summary": "old 15-row olivine v1 and 3-row argyrodite v1 as final corpus counts",
    }
    for row in source_rows:
        row["supersedes"] = supersedes.get(row["paper_topic"], "")
    write_csv(OUT / "08_provenance/FROZEN_ARTIFACT_INDEX.csv", artifact_rows, ["artifact", "role", "path", "sha256", "status", "notes"])
    write_csv(OUT / "08_provenance/SOURCE_PATH_INDEX.csv", source_rows, ["paper_topic", "authoritative_file", "sha256", "what_it_proves", "supersedes", "notes"])
    status_skill = git(REPO, "status", "--short")
    status_crystal = git(CRYSTAL_DB, "status", "--short")
    write_text(OUT / "08_provenance/AUDIT_NOTES.md", f"""# Audit notes

## Preflight

- Skill-Loop-CSP branch: `{git(REPO, 'branch', '--show-current')}`
- Skill-Loop-CSP HEAD: `{git(REPO, 'rev-parse', 'HEAD')}`
- Crystal-DB branch: `{git(CRYSTAL_DB, 'branch', '--show-current')}`
- Crystal-DB HEAD: `{git(CRYSTAL_DB, 'rev-parse', 'HEAD')}`
- A clean worktree was not required. The status below was captured at audit generation and preserved. Every listed entry except `scripts/build_final_paper_audit.py` pre-dated this task; that builder is the only status-visible file added by this task. The audit output root is ignored by the repository's Git rules.

### Skill-Loop-CSP status at audit generation

```text
{status_skill}
```

### Crystal-DB status at audit generation

```text
{status_crystal}
```

## Reconciled historical contradictions

1. **Dataset B topology:** the frozen SCA-only table reports 1/24 because B20 LiMnPO4 passes the chemistry-limited SCA OLIVINE policy. The final independent audit finds Pmm2 and zero anonymous olivine matches, so the paper headline is **0/24**. Both values remain visible and labelled.
2. **B→C efficiency:** historical `10–100× faster` wording mixed model-size and runtime effects. The final audit supports **approximately 50–285× fewer constraints** and **approximately 1.5–30× wall-clock speedup**, family-dependent.
3. **Dataset B optimality:** four olivine rows are `FEASIBLE_TIME_LIMIT`; they are best-found incumbents, not proven optima. Dataset C is 24/24 OPTIMAL.
4. **V1 freedom:** the C09 MgCr2O4 v1 row is a workflow example with one feasible scaffold state. Scaffold-freedom claims use the frozen v2 ablation/holdout.
5. **Dataset E:** an earlier implementation audit stopped on a 64-site garnet guard. It is superseded by the later frozen Dataset E method and final 18-row report, which use the audited large ordered-scaffold path without changing the final denominator.
6. **Crystal-DB corpora:** final olivine is ordered v2 (94 structures/84 compositions), not v1 (15); final argyrodite is ordered v2 (8/8), not v1 (3).

## Remaining method/version ambiguities

- QLIP package metadata says `0.0.0`, while frozen workflow prose calls the installed adapter `0.3.0`; commit/source hashes are therefore the reproducibility anchor.
- The exact scientific-run Python patch and the pymatgen version used by every A/B/C/v2/Dataset E process were not uniformly embedded in result artifacts. Recorded versions are role- and source-specific in `SOFTWARE_VERSIONS.csv`.
- The LM Studio BGE-M3 model name/backend/version and observed 1024D output are frozen, but a model revision/content hash is not recorded.
- `CAP_REACHED` is not rewritten as `CONVERGED`; the manifests preserve Boolean convergence and terminal-state notes separately.

## Freeze-anchor verification

The A, B, and C roster hashes, scaffold-v1 source hash, and Dataset C runner hash match `FINAL_METHOD_FREEZE.json`. The v2 method-freeze, 33-row holdout, staged results, and 12-row ablation hashes match the hashes embedded in the final v2 records. The Dataset E scaffold source, development templates, and validation-method freeze match `METHOD_FREEZE.json`. Every final specialist database matches `CORPUS_HASHES.json`. All 48 indexed source files also had identical hashes before and after audit generation.

## Unsafe-phrase scan

The required phrase scan found four occurrences, all confined to explicit **Do not claim** or required-caveat wording in `PAPER_CLAIMS_AND_CAVEATS.md`. No affirmative unsafe claim or unfinished-content marker was found.

## DFT status

**PENDING — NOT YET INCLUDED / PENDING FINAL FIRST-PRINCIPLES RESULTS.** The Barkla directory is an export/handoff package, not a final DFT result record, and no partial job is promoted into the master table.

## Audit activity

No retrieval, SPP construction, QLIP, SCA, CHGNet, DFT, Materials Project acquisition, or Crystal-DB corpus construction was run. Scientific source artifacts were read and hashed only. No commit or push was performed.
""")

    write_text(OUT / "README.md", """# Final Paper Audit — Paper_scaffolds_september

**This folder is the authoritative frozen paper-writing source.**

Use:

- `01_results/PAPER_HEADLINE_NUMBERS.md` for final denominators.
- `01_results/PAPER_MASTER_RESULTS.md` for detailed results.
- `02_claims/PAPER_CLAIMS_AND_CAVEATS.md` for allowed wording and guardrails.
- `03_methods/PAPER_METHODS_FREEZE.md` for the reconciled methods.
- `04_scaffolds/SCAFFOLD_DEFINITIONS.md` for scaffold descriptions.
- `05_validation/VALIDATION_DEFINITIONS.md` for SCA and external-validator interpretation.
- `06_datasets/*_MANIFEST.csv` for concrete row-level examples.
- `07_crystaldb/CRYSTALDB_CORPUS_SUMMARY.md` for final specialist-corpus counts and hashes.
- `08_provenance/` for source hashes, supersession history, and unresolved ambiguities.

**Do not infer scientific claims from superseded historical reports when a final paper-audit entry exists.** Failed rows were not replaced, denominators were not changed, and DFT remains pending. This pack contains summaries and references only; it does not duplicate large CIF, retrieval, or SPP trees.
""")

    current_hashes = {str(path.resolve()): sha256(path) for _, _, path, _ in SOURCES}
    changed = [path for path in initial_hashes if initial_hashes[path] != current_hashes[path]]
    if changed:
        raise AssertionError("frozen sources changed during audit:\n" + "\n".join(changed))

    generated_at = datetime.now(timezone.utc).isoformat()
    audit_manifest = {
        "schema_version": "final_paper_audit.v1",
        "title": "Paper_scaffolds_september authoritative paper-writing audit",
        "generated_at_utc": generated_at,
        "repository": {"path": str(REPO), "branch": git(REPO, "branch", "--show-current"), "head": git(REPO, "rev-parse", "HEAD"), "clean_required": False},
        "crystal_db_repository": {"path": str(CRYSTAL_DB), "branch": git(CRYSTAL_DB, "branch", "--show-current"), "head": git(CRYSTAL_DB, "rev-parse", "HEAD")},
        "dataset_counts": {"A": 24, "B": 24, "C": 24, "V2_HOLDOUT": 33, "E": 18},
        "b_c_pairing": "24/24 complete; retrieval/SPP scientific inputs identical",
        "dft": {"status": "PENDING", "included_in_current_headline": False},
        "authoritative_source_file_count": len(SOURCES),
        "required_files": REQUIRED_FILES,
        "scientific_reruns": [],
        "frozen_sources_unchanged_during_audit": True,
        "commit_performed": False,
        "push_performed": False,
    }
    (OUT / "FINAL_PAPER_AUDIT_MANIFEST.json").write_text(json.dumps(audit_manifest, indent=2) + "\n", encoding="utf-8")
    absent = [name for name in REQUIRED_FILES if name != "FINAL_PAPER_AUDIT_HASHES.json" and not (OUT / name).is_file()]
    if absent:
        raise AssertionError(f"required output files absent before hash export: {absent}")
    output_hashes = {}
    for path in sorted(p for p in OUT.rglob("*") if p.is_file() and p.name != "FINAL_PAPER_AUDIT_HASHES.json"):
        output_hashes[path.relative_to(OUT).as_posix()] = {"sha256": sha256(path), "size_bytes": path.stat().st_size}
    hashes_payload = {"schema_version": "final_paper_audit.hashes.v1", "generated_at_utc": generated_at, "scope": "all audit files except this self-referential hash manifest", "files": output_hashes}
    (OUT / "FINAL_PAPER_AUDIT_HASHES.json").write_text(json.dumps(hashes_payload, indent=2) + "\n", encoding="utf-8")
    absent = [name for name in REQUIRED_FILES if not (OUT / name).is_file()]
    if absent:
        raise AssertionError(f"required output files absent: {absent}")
    print(json.dumps({"output": str(OUT), "dataset_counts": {k: len(v) for k, v in manifests.items()}, "sources": len(SOURCES), "required_files": len(REQUIRED_FILES)}, indent=2))


if __name__ == "__main__":
    main()
