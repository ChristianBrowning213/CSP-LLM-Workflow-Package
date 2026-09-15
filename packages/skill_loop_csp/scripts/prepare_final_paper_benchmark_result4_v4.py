"""Preflight and freeze the Result-4-only V4 benchmark without solving."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from sok_llm_orchestrator.bench.prospective import canonical_structure_sha256
from sok_llm_orchestrator.retrieval.corpus_router import route_corpus
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
    _qlip_ordered_orbits_adapter,
    _tree_hash,
)


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "artifacts" / "final_paper_benchmark_result4_v4_preflight"
FREEZE = ROOT / "artifacts" / "final_paper_benchmark_result4_v4"
V3 = ROOT / "artifacts" / "final_paper_benchmark_v3"
QUALITY = ROOT / "artifacts" / "final_paper_benchmark_v3_quality_preflight"
WORKFLOW_COMMIT = "1238bb09a5f1325d7021422ea406df87a5f7a2e3"
V3_WORKFLOW_COMMIT = "698d82a37d94b1b64a6f2488a2e3b205dbf0f989"

POSITIVE = (
    ("RDX-E4-A2", "Na3Zr2Si2PO12", ROOT / "data/nasicon/reference/reference.cif", "nasicon-mp1221148", "TARGET_DERIVED_DEMONSTRATION"),
    ("RDX-E4-C2", "Na3Ti2(PO4)3", ROOT / "data/corpora/nasicon_specialist_v3/cifs/nasicon-mp761046.cif", "nasicon-mp761046", "TARGET_DERIVED_DEMONSTRATION"),
    ("RDX-E4-F1", "LiZr2(PO4)3", ROOT / "data/corpora/nasicon_specialist_v3/cifs/nasicon-mp10499.cif", "nasicon-mp10499", "INDEPENDENT_REFERENCE_RECOVERY"),
)
NEGATIVE = (
    ("RDX-NEG-E4-A1", "Na3Zr2Si2PO12", "ORBIT_MULTIPLICITY_NOT_REPRESENTABLE"),
    ("RDX-NEG-E4-A3", "Na3Ti2Si2PO12", "TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH"),
    ("RDX-NEG-E4-A4", "Na3Hf2Si2PO12", "TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH"),
)


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


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def qlip_schema() -> dict[str, Any]:
    import qlip

    for parent in Path(qlip.__file__).resolve().parents:
        path = parent / "docs" / "mcp" / "MCP_SCHEMA.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))["solve_request"]
    raise RuntimeError("installed QLIP solve schema is unavailable")


def schema_probe(structure: Any, scaffold_id: str, orbits: list[dict[str, Any]]) -> list[str]:
    cell = structure.lattice
    request = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": structure.composition.formula.replace(" ", "")},
            "design_space": {
                "template": {"name": scaffold_id, "lattice": {
                    "a": cell.a, "b": cell.b, "c": cell.c,
                    "alpha": cell.alpha, "beta": cell.beta, "gamma": cell.gamma,
                    "units": "angstrom",
                }},
                "sites": {
                    "mode": "explicit_fractional_sites",
                    "explicit_fractional_sites": structure.frac_coords.tolist(),
                    "ordered_orbits": orbits,
                },
            },
            "objective": {"type": "none"},
        },
        "constraints": [], "guidance": [], "guidance_mode": "weighted_sum",
        "solver": {"name": "gurobi"}, "artifacts": {"return_cif": True},
        "runtime": {"max_sites": 64, "max_binary_vars": 500, "max_constraints": 1000},
        "context": {"run_id": "result4-v4-preflight", "pot_root": str(ROOT)},
    }
    return [f"/{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in Draft202012Validator(qlip_schema()).iter_errors(request)]


def main() -> None:
    if PREFLIGHT.exists() or FREEZE.exists():
        raise RuntimeError("Result-4 V4 preflight/freeze already exists; refusing to overwrite")
    head = __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != WORKFLOW_COMMIT:
        raise RuntimeError(f"unexpected workflow commit: {head}")
    PREFLIGHT.mkdir(parents=True)
    stages = ProductionWorkflowStages()
    guidance = {row["case_id"]: row for row in read_csv(QUALITY / "RESULT_4_GUIDANCE_READINESS.csv")}
    v3_config = json.loads((V3 / "BENCHMARK_V3_CONFIG.json").read_text(encoding="utf-8"))
    v3_freeze = json.loads((V3 / "BENCHMARK_V3_FREEZE.json").read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    corpus_id = ""
    corpus_hash = ""

    for case_id, formula, reference_path, reference_id, classification in POSITIVE:
        task = stages.normalise(f"{case_id} {formula}")
        route = route_corpus(f"{case_id} {formula}", formula=task["formula"])
        if route.corpus_id != "nasicon_specialist_v3":
            raise RuntimeError(f"wrong corpus route for {case_id}: {route.corpus_id}")
        actual_corpus_hash = sha256(route.database)
        if corpus_id and (route.corpus_id != corpus_id or actual_corpus_hash != corpus_hash):
            raise RuntimeError("positive cases do not share one frozen specialist corpus")
        corpus_id, corpus_hash = route.corpus_id, actual_corpus_hash
        scaffold_id, structure, internal_orbits = stages._scaffold(task, WorkflowConfig(output_root=PREFLIGHT))
        wire_orbits = _qlip_ordered_orbits_adapter(internal_orbits)
        schema_errors = schema_probe(structure, scaffold_id, wire_orbits)
        if schema_errors:
            raise RuntimeError(f"QLIP schema preflight failed for {case_id}: {schema_errors}")
        if [row["site_indices"] for row in wire_orbits] != [list(row["site_indices"]) for row in internal_orbits]:
            raise RuntimeError(f"orbit membership changed for {case_id}")
        if [row["allowed_species"] for row in wire_orbits] != [list(row["allowed_species"]) for row in internal_orbits]:
            raise RuntimeError(f"allowed species changed for {case_id}")
        ready = guidance[case_id]
        if int(ready["unsupported_pair_count"]) != 0 or ready["ready"] != "YES":
            raise RuntimeError(f"guidance coverage is not ready for {case_id}")
        from pymatgen.core import Structure
        reference_structure = Structure.from_file(reference_path)
        record = __import__("qlip.scaffolds", fromlist=["get_scaffold"]).get_scaffold(task["prototype"])
        references.append({
            "case_id": case_id, "formula": formula, "classification": classification,
            "reference_id": reference_id, "reference_cif_path": str(reference_path.relative_to(ROOT)).replace("\\", "/"),
            "reference_cif_sha256": sha256(reference_path),
            "reference_canonical_sha256": canonical_structure_sha256(reference_structure),
            "reference_target_derived": "YES" if classification == "TARGET_DERIVED_DEMONSTRATION" else "NO",
            "scaffold_id": scaffold_id, "scaffold_source_id": record.source_structure_id,
            "scaffold_source_cif_sha256": record.source_cif_sha256,
            "reference_scaffold_source_distinct": "YES" if reference_id != record.source_structure_id else "NO_TARGET_DERIVED_CASE",
        })
        cases.append({
            "case_id": case_id, "formula": formula, "case_type": "POSITIVE",
            "classification": classification, "prototype": task["prototype"], "space_group": task["space_group"],
            "specialist_corpus_id": route.corpus_id, "task_mapping": "PASS", "scaffold_preflight": "PASS",
            "guidance_usable_pairs": ready["request_usable_pair_count"],
            "guidance_fallback_pairs": ready["regulator_fallback_pair_count"],
            "guidance_unsupported_pairs": ready["unsupported_pair_count"],
            "ordered_orbit_serialization": "PASS", "qlip_schema_executability": "PASS",
            "expected_terminal": "CANONICAL_COMPLETION", "preflight_status": "PASS",
        })
        provenance.append({
            "case_id": case_id, "reference_sha256": sha256(reference_path),
            "scaffold_source_id": record.source_structure_id, "scaffold_source_sha256": record.source_cif_sha256,
            "internal_orbit_count": len(internal_orbits), "wire_orbit_count": len(wire_orbits),
            "orbit_membership_hash": hashlib.sha256(json.dumps([row["site_indices"] for row in wire_orbits], separators=(",", ":")).encode()).hexdigest(),
            "allowed_species_hash": hashlib.sha256(json.dumps([row["allowed_species"] for row in wire_orbits], separators=(",", ":")).encode()).hexdigest(),
            "qlip_schema_errors": [], "benchmark_solve_invoked": False,
        })

    for case_id, formula, expected_code in NEGATIVE:
        task = stages.normalise(f"{case_id} {formula}")
        route = route_corpus(f"{case_id} {formula}", formula=task["formula"])
        if route.corpus_id != corpus_id or sha256(route.database) != corpus_hash:
            raise RuntimeError(f"negative case corpus mismatch for {case_id}")
        try:
            stages._scaffold(task, WorkflowConfig(output_root=PREFLIGHT))
        except WorkflowStageError as exc:
            if exc.stage != "representability" or exc.code != expected_code:
                raise RuntimeError(f"wrong negative terminal for {case_id}: {exc.stage}/{exc.code}") from exc
            cases.append({
                "case_id": case_id, "formula": formula, "case_type": "NEGATIVE_ABSTENTION",
                "classification": "CONTROLLED_REPRESENTABILITY", "prototype": task["prototype"], "space_group": task["space_group"],
                "specialist_corpus_id": route.corpus_id, "task_mapping": "PASS", "scaffold_preflight": "EXPECTED_ABSTENTION",
                "guidance_usable_pairs": "NOT_REACHED", "guidance_fallback_pairs": "NOT_REACHED",
                "guidance_unsupported_pairs": "NOT_APPLICABLE", "ordered_orbit_serialization": "NOT_REACHED",
                "qlip_schema_executability": "NOT_REACHED_EXPECTED_TERMINAL",
                "expected_terminal": f"representability/{expected_code}", "preflight_status": "PASS",
            })
            provenance.append({"case_id": case_id, "expected_stage": "representability", "expected_code": expected_code, "observed_stage": exc.stage, "observed_code": exc.code, "benchmark_solve_invoked": False})
        else:
            raise RuntimeError(f"negative case unexpectedly passed representability: {case_id}")

    write_csv(PREFLIGHT / "RESULT4_V4_PREFLIGHT.csv", cases)
    write_json(PREFLIGHT / "RESULT4_V4_PREFLIGHT_PROVENANCE.json", {
        "schema_version": "result4_v4_preflight.v1", "workflow_commit": WORKFLOW_COMMIT,
        "original_v3_workflow_commit": V3_WORKFLOW_COMMIT, "case_count": len(cases),
        "positive_pass": 3, "negative_pass": 3, "benchmark_solves": 0,
        "specialist_corpus_route_id": corpus_id, "specialist_corpus_route_sha256": corpus_hash,
        "records": provenance,
    })
    (PREFLIGHT / "RESULT4_V4_PREFLIGHT_REPORT.md").write_text(
        "# Result-4-only V4 preflight\n\n"
        f"- Workflow commit: `{WORKFLOW_COMMIT}`\n"
        "- Positive cases: 3/3 PASS\n- Negative cases: 3/3 PASS\n"
        "- Specialist routing: 6/6 PASS\n- Guidance coverage: 3/3 positives with zero unsupported pairs\n"
        "- Ordered-orbit strict-schema executability: 3/3 positives PASS\n"
        "- Expected representability terminals: 3/3 negatives PASS\n"
        "- Benchmark solves: 0\n\nNo Result-2 or Result-3 execution was rerun.\n",
        encoding="utf-8",
    )

    if len(cases) != 6 or any(row["preflight_status"] != "PASS" for row in cases):
        raise RuntimeError("6/6 Result-4 V4 preflight did not pass")
    FREEZE.mkdir(parents=True)
    write_csv(FREEZE / "RESULT4_V4_CASES.csv", cases)
    write_csv(FREEZE / "RESULT4_V4_REFERENCES.csv", references)
    config = {
        "schema_version": "result4_v4_config.v1", "execution_status": "FROZEN_NOT_STARTED",
        "entrypoint": "sok_llm_orchestrator.workflow.runner.run_csp_workflow",
        "workflow_commit": WORKFLOW_COMMIT, "original_v3_workflow_commit": V3_WORKFLOW_COMMIT,
        "case_count": 6, "positive_count": 3, "negative_count": 3,
        "retrieval": {**v3_config["retrieval"], "required_route": "nasicon_specialist_v3", "route_database_sha256": corpus_hash},
        "spp": v3_config["spp"], "regulator": v3_config["regulator"],
        "option_1": v3_config["option_1"], "qlip": v3_config["qlip"], "sca": v3_config["sca"],
        "ordered_orbit_serialization": "QLIP solve-request v1.0 strict projection",
    }
    write_json(FREEZE / "RESULT4_V4_CONFIG.json", config)
    (FREEZE / "RESULT4_V4_PROTOCOL.md").write_text(
        "# Result-4-only Benchmark V4 protocol\n\n"
        "This freeze contains only the same six Result-4 cases fixed before any V3 Result-4 scientific output existed. "
        "It does not reopen, rerun, or reinterpret completed V3 Results 2 or 3.\n\n"
        "Three positives use the frozen NASICON specialist corpus, fresh request SPP, unchanged production quality gate, "
        "frozen broad regulator, canonical registered scaffold, QLIP objective-parity verification, CIF, and SCA. "
        "RDX-E4-F1 is the independent-reference recovery case; A2 and C2 are target-derived demonstrations. "
        "Three negatives terminate at their frozen representability stages. The serialization repair changes only the "
        "wire representation of ordered-orbit records and preserves scientific orbit contents.\n\n"
        "No V4 benchmark solve occurred before this freeze.\n",
        encoding="utf-8",
    )
    frozen = ["RESULT4_V4_PROTOCOL.md", "RESULT4_V4_CASES.csv", "RESULT4_V4_CONFIG.json", "RESULT4_V4_REFERENCES.csv"]
    file_hashes = {name: sha256(FREEZE / name) for name in frozen}
    freeze_payload = {
        "schema_version": "result4_v4_freeze.v1", "workflow_commit": WORKFLOW_COMMIT,
        "original_v3_workflow_commit": V3_WORKFLOW_COMMIT,
        "v3_campaign_status": "INVALID_HALTED", "v3_result_2_preserved_sha256": sha256(V3 / "results/result_2_heldout/RESULT_2_HELDOUT_RECOVERY.csv"),
        "v3_result_3_preserved_sha256": sha256(V3 / "results/result_3_factorial/RESULT_3_FACTORIAL.csv"),
        "same_result4_case_identities_as_v3": True, "case_ids": [row["case_id"] for row in cases],
        "positive_classifications": {row["case_id"]: row["classification"] for row in cases if row["case_type"] == "POSITIVE"},
        "specialist_corpus": {"route_id": corpus_id, "route_database_sha256": corpus_hash, "dataset_id": v3_config["retrieval"]["nasicon_specialist_dataset_id"], "dataset_sha256": v3_freeze["nasicon_corpus"]["sha256"] if "nasicon_corpus" in v3_freeze else "feb003aa0f83b7c88db94ffaca9fa645d46ef071fa8371fef79487c5fa4d6e60"},
        "regulator": {"id": v3_freeze["regulator"]["id"], "tree_sha256": v3_freeze["regulator"]["tree_sha256"]},
        "spp": v3_config["spp"], "qlip": v3_config["qlip"], "sca": v3_config["sca"],
        "benchmark_solves_before_v4_freeze": 0, "nonbenchmark_compatibility_smokes": 1,
        "result_2_3_rerun": False, "result4_v4_file_hashes": file_hashes,
    }
    write_json(FREEZE / "RESULT4_V4_FREEZE.json", freeze_payload)
    manifest = [{"path": name, "sha256": sha256(FREEZE / name)} for name in frozen + ["RESULT4_V4_FREEZE.json"]]
    write_csv(FREEZE / "OUTPUT_HASH_MANIFEST.csv", manifest)
    print(json.dumps({"preflight_positive": 3, "preflight_negative": 3, "freeze_hashes": {row["path"]: row["sha256"] for row in manifest}}, indent=2))


if __name__ == "__main__":
    main()
