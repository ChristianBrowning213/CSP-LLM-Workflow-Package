"""Preflight and freeze the four unobserved Result-4 completion cases without solving."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pymatgen.core import Composition

from sok_llm_orchestrator.retrieval.corpus_router import route_corpus
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
    _qlip_ordered_orbits_adapter,
    _qlip_target_formula,
    _validate_qlip_species_contract,
)


ROOT = Path(__file__).resolve().parents[1]
V4_1 = ROOT / "artifacts/final_paper_benchmark_result4_v4_1"
PREFLIGHT = ROOT / "artifacts/final_paper_benchmark_result4_completion_v4_2_preflight"
FREEZE = ROOT / "artifacts/final_paper_benchmark_result4_completion_v4_2"
COMMIT = "ac79cf0db324adf4c676ea2b8c288d42613dcd28"
V4_1_COMMIT = "31feff023515b2ac32165fe95fb803412e21a5bc"
V4_1_FREEZE = "03d8c09bcb0986aad4628211d2e9b1c17a929ac86f58fd832c366fd865f9b3a0"
A2_TRACE = "009034c60967d8f9eef47001f0660a4b498bc61bfef25fb5a7caec20655146e5"
A2_CIF = "90f8fc952510051ed6b9415d8100528f4490ebf2941d10573a4e736084a57b85"
C2_TRACE = "8929e2d332ece9557bbd1b4f7576860612bad1002c874cc4a29346af70595ef9"
C2_CIF = "f895e71a6951d1de4c521682d4b66b0a24b59982bd4c155a9d790c47b4e0b399"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def solve_schema() -> dict[str, Any]:
    import qlip
    for parent in Path(qlip.__file__).resolve().parents:
        candidate = parent / "docs/mcp/MCP_SCHEMA.json"
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))["solve_request"]
    raise RuntimeError("QLIP solve schema unavailable")


def schema_request(formula: str, scaffold_id: str, structure: Any, orbits: list[dict[str, Any]]) -> dict[str, Any]:
    lattice = structure.lattice
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": formula},
            "design_space": {
                "template": {"name": scaffold_id, "lattice": {
                    "a": lattice.a, "b": lattice.b, "c": lattice.c,
                    "alpha": lattice.alpha, "beta": lattice.beta, "gamma": lattice.gamma,
                    "units": "angstrom",
                }},
                "sites": {"mode": "explicit_fractional_sites", "explicit_fractional_sites": structure.frac_coords.tolist(), "ordered_orbits": orbits},
            },
            "objective": {"type": "none"},
        },
        "constraints": [], "guidance": [], "guidance_mode": "weighted_sum",
        "solver": {"name": "gurobi"}, "artifacts": {"return_cif": True},
        "runtime": {"max_sites": 64, "max_binary_vars": 500, "max_constraints": 1000},
        "context": {"run_id": "result4-completion-v4-2-preflight", "pot_root": str(ROOT)},
    }


def verify_unobserved(cases: list[dict[str, str]]) -> dict[str, Any]:
    ledger = {row["case_id"]: row for row in read_csv(V4_1 / "results/EXECUTION_LEDGER.csv")}
    f1 = ledger.get("RDX-E4-F1")
    if not f1 or f1["solver_status"] != "NOT_REACHED" or f1["cif_emitted"] != "NO" or f1["reference_match"]:
        raise RuntimeError("F1 has an observed scientific outcome")
    negative_ids = [row["case_id"] for row in cases if row["case_type"] == "NEGATIVE_ABSTENTION"]
    if any(case_id in ledger for case_id in negative_ids):
        raise RuntimeError("a completion negative case was previously attempted")
    return {
        "RDX-E4-F1": {"previous_solution": False, "previous_cif": False, "previous_reference_comparison": False, "previous_recovery_outcome": False},
        **{case_id: {"previously_attempted": False} for case_id in negative_ids},
    }


def main() -> None:
    if PREFLIGHT.exists() or FREEZE.exists():
        raise RuntimeError("completion preflight/freeze already exists; refusing overwrite")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != COMMIT:
        raise RuntimeError(f"unexpected workflow commit: {head}")
    if subprocess.check_output(["git", "diff", "--name-only", COMMIT, "--", "src"], cwd=ROOT, text=True).strip():
        raise RuntimeError("tracked scientific source diff exists")
    if subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--", "src"], cwd=ROOT, text=True).strip():
        raise RuntimeError("untracked scientific source exists")
    all_cases = read_csv(V4_1 / "RESULT4_V4_1_CASES.csv")
    case_ids = {"RDX-E4-F1", "RDX-NEG-E4-A1", "RDX-NEG-E4-A3", "RDX-NEG-E4-A4"}
    cases = [row for row in all_cases if row["case_id"] in case_ids]
    if len(cases) != 4 or {row["case_id"] for row in cases} != case_ids:
        raise RuntimeError("completion case identity mismatch")
    unobserved = verify_unobserved(cases)
    references = [row for row in read_csv(V4_1 / "RESULT4_V4_1_REFERENCES.csv") if row["case_id"] == "RDX-E4-F1"]
    if len(references) != 1:
        raise RuntimeError("frozen F1 reference missing or duplicated")
    reference = references[0]
    reference_path = ROOT / reference["reference_cif_path"]
    if sha256(reference_path) != reference["reference_cif_sha256"]:
        raise RuntimeError("frozen F1 reference hash changed")

    stages = ProductionWorkflowStages()
    records: list[dict[str, Any]] = []
    corpus_id = corpus_hash = ""
    for case in cases:
        request = f"{case['case_id']}: Generate {case['formula']} as a NASICON/NZP crystal with requested {case['space_group']} symmetry."
        task = stages.normalise(request)
        if task["prototype"] != case["prototype"] or task["space_group"] != case["space_group"]:
            raise RuntimeError(f"frozen task mapping mismatch: {case['case_id']}")
        route = route_corpus(request, formula=task["formula"])
        actual_hash = sha256(route.database)
        if route.corpus_id != "nasicon_specialist_v3":
            raise RuntimeError(f"wrong corpus: {case['case_id']}")
        if corpus_id and (route.corpus_id != corpus_id or actual_hash != corpus_hash):
            raise RuntimeError("completion cases do not share one specialist corpus")
        corpus_id, corpus_hash = route.corpus_id, actual_hash
        if case["case_type"] == "POSITIVE":
            scaffold_id, structure, internal = stages._scaffold(task, WorkflowConfig(output_root=PREFLIGHT))
            wire = _qlip_ordered_orbits_adapter(internal)
            formula = _qlip_target_formula(task, len(structure))
            required_pairs = stages.required_pairs(task, WorkflowConfig(output_root=PREFLIGHT))
            guidance = [{"params": {"supported_pairs": required_pairs, "missing_pairs": []}}]
            _validate_qlip_species_contract(formula=formula, ordered_orbits=wire, required_pairs=required_pairs, guidance=guidance)
            errors = list(Draft202012Validator(solve_schema()).iter_errors(schema_request(formula, scaffold_id, structure, wire)))
            if errors:
                raise RuntimeError(f"strict QLIP schema failed: {[error.message for error in errors]}")
            if set(Composition(formula).get_el_amt_dict()) != {"Li", "Zr", "P", "O"}:
                raise RuntimeError("F1 target species contract failed")
            records.append({"case_id": case["case_id"], "case_type": case["case_type"], "formula": case["formula"], "classification": case["classification"], "corpus_id": route.corpus_id, "task_mapping": "PASS", "formula_species_contract": "PASS", "strict_qlip_schema": "PASS", "expected_terminal": case["expected_terminal"], "previous_outcome_unobserved": "YES", "preflight_status": "PASS"})
        else:
            try:
                stages._scaffold(task, WorkflowConfig(output_root=PREFLIGHT))
            except WorkflowStageError as exc:
                expected_stage, expected_code = case["expected_terminal"].split("/", 1)
                if (exc.stage, exc.code) != (expected_stage, expected_code):
                    raise RuntimeError(f"wrong negative terminal: {case['case_id']}: {exc.stage}/{exc.code}") from exc
            else:
                raise RuntimeError(f"negative unexpectedly representable: {case['case_id']}")
            records.append({"case_id": case["case_id"], "case_type": case["case_type"], "formula": case["formula"], "classification": case["classification"], "corpus_id": route.corpus_id, "task_mapping": "PASS", "formula_species_contract": "NOT_REACHED_EXPECTED", "strict_qlip_schema": "NOT_REACHED_EXPECTED", "expected_terminal": case["expected_terminal"], "previous_outcome_unobserved": "YES", "preflight_status": "PASS"})

    PREFLIGHT.mkdir(parents=True)
    write_csv(PREFLIGHT / "RESULT4_COMPLETION_V4_2_PREFLIGHT.csv", records)
    write_json(PREFLIGHT / "RESULT4_COMPLETION_V4_2_PROVENANCE.json", {"workflow_commit": COMMIT, "case_count": 4, "positive_count": 1, "negative_count": 3, "pass_count": 4, "benchmark_solves": 0, "unobserved_evidence": unobserved, "specialist_corpus_id": corpus_id, "specialist_corpus_hash": corpus_hash, "v4_1_completed_case_links": {"A2_trace_sha256": A2_TRACE, "A2_cif_sha256": A2_CIF, "C2_trace_sha256": C2_TRACE, "C2_cif_sha256": C2_CIF}})
    (PREFLIGHT / "RESULT4_COMPLETION_V4_2_REPORT.md").write_text("# Result-4 completion V4.2 preflight\n\n- Cases: 4/4 PASS\n- F1 formula/species contract: PASS\n- Strict QLIP schema: PASS\n- Negative expected terminals: 3/3 PASS\n- All completion outcomes previously unobserved: YES\n- Benchmark solves: 0\n- A2/C2 rerun: NO\n", encoding="utf-8")

    FREEZE.mkdir(parents=True)
    write_csv(FREEZE / "RESULT4_COMPLETION_V4_2_CASES.csv", cases)
    write_csv(FREEZE / "RESULT4_COMPLETION_V4_2_REFERENCE.csv", references)
    old_config = json.loads((V4_1 / "RESULT4_V4_1_CONFIG.json").read_text(encoding="utf-8"))
    config = {**old_config, "schema_version": "result4_completion_v4_2_config.v1", "workflow_commit": COMMIT, "case_count": 4, "positive_count": 1, "negative_count": 3, "execution_status": "FROZEN_NOT_STARTED", "completion_only": True}
    write_json(FREEZE / "RESULT4_COMPLETION_V4_2_CONFIG.json", config)
    (FREEZE / "RESULT4_COMPLETION_V4_2_PROTOCOL.md").write_text("# Result-4 completion V4.2 protocol\n\nThis completion freeze contains only the four scientifically unobserved V4.1 cases: independent-reference F1 and the same three controlled negatives. A2 and C2 are excluded because their V4.1 outcomes were observed and are preserved without rerun. The specialist corpus, request-SPP policy, regulator, scaffolds, solver settings, SCA settings, F1 reference, and negative terminal definitions are unchanged. The formula repair changes only canonical target-composition serialization and adds a pre-QLIP species consistency check. No benchmark solve occurred during preflight or freeze.\n", encoding="utf-8")
    core_names = ["RESULT4_COMPLETION_V4_2_PROTOCOL.md", "RESULT4_COMPLETION_V4_2_CASES.csv", "RESULT4_COMPLETION_V4_2_REFERENCE.csv", "RESULT4_COMPLETION_V4_2_CONFIG.json"]
    core_hashes = {name: sha256(FREEZE / name) for name in core_names}
    freeze_payload = {"schema_version": "result4_completion_v4_2_freeze.v1", "execution_status": "FROZEN_NOT_STARTED", "workflow_commit": COMMIT, "superseded_invalid_v4_1": {"workflow_commit": V4_1_COMMIT, "freeze_sha256": V4_1_FREEZE, "status": "INVALID_HALTED"}, "case_ids": [row["case_id"] for row in cases], "all_completion_outcomes_previously_unobserved": True, "f1_reference": {"id": reference["reference_id"], "sha256": reference["reference_cif_sha256"]}, "specialist_corpus": {"id": corpus_id, "sha256": corpus_hash}, "regulator": {"id": "icsd_broad_regulator_v1", "tree_sha256": "be0a8f620fca62aa3bb755d76ac9edeeb8aa1ac507c4800001e4018b94c6cf0c"}, "v4_1_completed_case_links": {"A2_trace_sha256": A2_TRACE, "A2_cif_sha256": A2_CIF, "C2_trace_sha256": C2_TRACE, "C2_cif_sha256": C2_CIF, "used_as_completion_inputs": False}, "benchmark_solves_after_v4_1_halt": 0, "nonbenchmark_compatibility_smokes_after_halt": 1, "A2_C2_rerun": False, "file_hashes": core_hashes}
    write_json(FREEZE / "RESULT4_COMPLETION_V4_2_FREEZE.json", freeze_payload)
    names = core_names + ["RESULT4_COMPLETION_V4_2_FREEZE.json"]
    write_csv(FREEZE / "OUTPUT_HASH_MANIFEST.csv", [{"path": name, "sha256": sha256(FREEZE / name)} for name in names])
    print(json.dumps({"preflight": "4/4 PASS", "workflow_commit": COMMIT, "hashes": {name: sha256(FREEZE / name) for name in names}}, indent=2))


if __name__ == "__main__":
    main()
