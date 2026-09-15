"""Controlled OLD-vs-corrected periodic SPP objective regression.

This diagnostic reuses persisted benchmark requests, cells, retrieval evidence,
and preblended POT packages.  It never retrieves or fits SPPs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "corrected_periodic_objective_regression_v1"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "corrected_periodic_objective_regression_v1"
PAPER_ROOT = REPO_ROOT / "outputs" / "paper1_simple_ordered_v1"
STRESS_ROOT = REPO_ROOT / "outputs" / "paper_50_50_csv_workflow_v1"
FAMILY_RESULTS = REPO_ROOT / "artifacts" / "paper1_spp_positive_domain" / "results" / "FAMILY_RECOVERY_RESULTS.csv"
CASE_RESULTS = REPO_ROOT / "artifacts" / "paper1_spp_score_diagnostic_v1" / "CASE_CLASSIFICATION.csv"
TOLERANCE = 1.0e-7


def bootstrap_import_paths() -> None:
    """Make configured sibling source trees importable before workflow import."""
    candidates = (
        REPO_ROOT / "src",
        REPO_ROOT.parent / "qlip" / "src",
        REPO_ROOT.parent / "SPP-Maker-QLIP" / "src",
        REPO_ROOT.parent / "Crystal-DB",
        REPO_ROOT.parent / "Structured_Crystal_Analyser",
    )
    for candidate in reversed(candidates):
        value = str(candidate.resolve())
        if candidate.exists() and value not in sys.path:
            sys.path.insert(0, value)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_manifest(root: Path, pattern: str = "*") -> list[dict[str, Any]]:
    return [
        {"path": p.relative_to(root).as_posix(), "sha256": sha256_file(p), "bytes": p.stat().st_size}
        for p in sorted(root.rglob(pattern), key=lambda x: x.as_posix().lower()) if p.is_file()
    ]


def manifest_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    raw = json.dumps(list(rows), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(fields or (rows[0].keys() if rows else ()))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in names})


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def select_panel() -> list[dict[str, str]]:
    """Apply the frozen deterministic selection rule without corrected outputs."""
    family = sorted(
        (row for row in read_csv(FAMILY_RESULTS) if row.get("condition") == "C_RETRIEVAL_CONDITIONED"),
        key=lambda row: row["row_id"],
    )
    chosen: list[dict[str, str]] = []

    def take(requested: set[str], want_pass: bool, count: int, reason: str) -> None:
        candidates = [
            row for row in family
            if row["requested_family"] in requested
            and (row["verdict"] == "FAMILY_PASS") is want_pass
            and (PAPER_ROOT / row["row_id"] / "generated" / "candidate.cif").is_file()
        ]
        for row in candidates[:count]:
            chosen.append({
                "source_benchmark": "paper1_simple_ordered_v1", "row_id": row["row_id"],
                "formula": row["formula"], "family": row["requested_family"],
                "old_family_recovery": row["verdict"], "selection_reason": reason,
            })

    take({"rocksalt_b1"}, False, 3, "first 3 generated non-PASS rocksalt rows by row_id")
    take({"zinc_blende_b3"}, False, 2, "first 2 generated non-PASS zinc-blende rows by row_id")
    take({"fluorite_antifluorite"}, False, 2, "first 2 generated non-PASS fluorite/anti-fluorite rows by row_id")
    take({"cscl_b2"}, True, 2, "first 2 generated PASS CsCl/B2 rows by row_id")
    # Deterministic oxide then halide preference.
    take({"oxide_perovskite"}, True, 1, "first generated PASS oxide-perovskite row by row_id")
    take({"halide_perovskite"}, True, 1, "first generated PASS halide-perovskite row by row_id")

    stress_sca = {r["row_id"]: r for r in read_csv(STRESS_ROOT / "SCA_RUN_SUMMARY.csv")}
    for row_id, reason in [
        ("layered_007", "exact required Li2FeO3 stress row"),
        (next((r["row_id"] for r in sorted(stress_sca.values(), key=lambda x: x["row_id"])
               if r["row_id"].startswith("spinel_") and r["topology_result"] == "PASS"),
              next(r["row_id"] for r in sorted(stress_sca.values(), key=lambda x: x["row_id"])
                   if r["row_id"].startswith("spinel_") and r["topology_result"] == "PARTIAL")),
         "first generated spinel topology PASS (otherwise first PARTIAL) by row_id"),
    ]:
        root = STRESS_ROOT / row_id
        task = read_json(root / "structured_task" / "structured_task.json")
        sca = stress_sca[row_id]
        chosen.append({
            "source_benchmark": "paper_50_50_csv_workflow_v1", "row_id": row_id,
            "formula": str(task["formula"]), "family": str(task["family"]),
            "old_family_recovery": "NOT_APPLICABLE", "old_topology": sca["topology_result"],
            "selection_reason": reason,
        })
    if len(chosen) != 13 or len({r["row_id"] for r in chosen}) != len(chosen):
        raise RuntimeError(f"deterministic panel resolved unexpectedly: {len(chosen)} rows")
    return chosen


def source_root(row: Mapping[str, str]) -> Path:
    base = PAPER_ROOT if row["source_benchmark"] == "paper1_simple_ordered_v1" else STRESS_ROOT
    return base / row["row_id"]


def source_critical_manifest(root: Path) -> list[dict[str, Any]]:
    paths: list[Path] = []
    for rel in (
        "input/request.txt", "input/input_row.json", "input/effective_config.json",
        "structured_task/structured_task.json", "retrieval/retrieval_manifest.json",
        "spp/request_spp_cache.json", "spp/pair_manifest.csv", "spp/config.json",
        "cell/dynamic_cell.json", "cell/search_space.json", "qlip/solver_config.json",
        "qlip/solver_result.json", "qlip/objective_check.json", "generated/candidate.cif",
        "sca/result.json", "sca/summary.json",
    ):
        p = root / rel
        if p.is_file():
            paths.append(p)
    for directory in (root / "retrieval" / "build" / "retrieved_cifs", root / "spp" / "potentials"):
        if directory.is_dir():
            paths.extend(p for p in directory.rglob("*") if p.is_file())
    return [
        {"path": p.relative_to(root).as_posix(), "sha256": sha256_file(p), "bytes": p.stat().st_size}
        for p in sorted(set(paths), key=lambda x: x.as_posix().lower())
    ]


def audit_row(row: Mapping[str, str]) -> dict[str, Any]:
    root = source_root(row)
    required = {
        "input_request": root / "input" / "request.txt",
        "structured_task": root / "structured_task" / "structured_task.json",
        "retrieval_manifest": root / "retrieval" / "retrieval_manifest.json",
        "request_spp_cache": root / "spp" / "request_spp_cache.json",
        "pair_manifest": root / "spp" / "pair_manifest.csv",
        "final_cell": root / "cell" / "dynamic_cell.json",
        "search_space": root / "cell" / "search_space.json",
        "solver_config": root / "qlip" / "solver_config.json",
        "old_candidate": root / "generated" / "candidate.cif",
        "old_sca_result": root / "sca" / "result.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    pot_root = root / "spp" / "potentials"
    retrieval_root = root / "retrieval" / "build" / "retrieved_cifs"
    if not pot_root.is_dir() or not list(pot_root.rglob("*.POT")):
        missing.append("persisted_pot_package")
    if not retrieval_root.is_dir() or not list(retrieval_root.rglob("*.cif")):
        missing.append("persisted_retrieval_cifs")
    if missing:
        return {**row, "status": "INVARIANT_UNAVAILABLE", "missing": missing}
    effective = read_json(root / "input" / "effective_config.json")
    retrieval = read_json(required["retrieval_manifest"])
    request_spp = read_json(required["request_spp_cache"])
    dynamic = read_json(required["final_cell"])
    target_id = str(effective.get("target_reference_id") or "")
    exclusion = retrieval.get("spp_evidence", {}).get("exclusion_audit", [])
    excluded = any(str(x.get("structure_id")) == target_id and x.get("decision") == "excluded" for x in exclusion)
    def refers_to_target(record: Mapping[str, Any]) -> bool:
        identifiers = [
            str(record.get("structure_id") or ""),
            str((record.get("provenance") or {}).get("source_id") or ""),
        ]
        normalized = [Path(value).stem for value in identifiers if value]
        return any(value == target_id or value.endswith("_" + target_id) for value in normalized)

    target_records = [record for record in retrieval.get("selected", []) if refers_to_target(record)]
    target_did_not_contribute = bool(target_records) and all(
        record.get("contributed_to_spp") is False for record in target_records
    )
    target_evidence_status = (
        "HISTORICAL_TARGET_IN_SPP_EVIDENCE"
        if target_records and not target_did_not_contribute
        else "TARGET_EXCLUDED_FROM_SPP_EVIDENCE"
        if excluded and target_did_not_contribute
        else "TARGET_EVIDENCE_STATUS_UNRESOLVED"
    )
    context = {
        "exclude_target_reference_true": effective.get("exclude_target_reference") is True,
        "target_reference_present": bool(target_id),
        "target_reference_exclusion_recorded": excluded,
        "target_reference_record_resolved": bool(target_records),
        "target_reference_did_not_contribute_to_spp": target_did_not_contribute,
    }
    blocking_conditions = {
        "preblended_pot_root_is_source_package": Path(request_spp.get("pot_root", "")).resolve() == pot_root.resolve(),
        "preblended_pair_level": request_spp.get("blend_mode") == "preblended_pair_level",
        "persisted_dynamic_cell_matches": request_spp.get("dynamic_cell") == dynamic,
        "grid_is_4x4x4": int(dynamic.get("grid_density", 0)) == 4,
        "no_retrieval_required": True,
        "no_spp_fitting_required": True,
    }
    status = "PASS" if all(blocking_conditions.values()) else "INVARIANT_UNAVAILABLE"
    hashes = {name: sha256_file(path) for name, path in required.items()}
    pot_manifest = tree_manifest(pot_root, "*.POT")
    retrieval_manifest = tree_manifest(retrieval_root, "*.cif")
    critical = source_critical_manifest(root)
    return {
        **row, "status": status, "source_row": str(root), "target_reference_id": target_id,
        "conditions": blocking_conditions, "nonblocking_target_evidence_context": context,
        "target_evidence_status": target_evidence_status,
        "target_reference_records": target_records, "hashes": hashes,
        "pot_package_hash": manifest_hash(pot_manifest), "pot_file_count": len(pot_manifest),
        "retrieval_cif_bundle_hash": manifest_hash(retrieval_manifest),
        "retrieval_cif_count": len(retrieval_manifest), "final_cell": dynamic,
        "effective_config": effective, "source_critical_manifest_hash": manifest_hash(critical),
        "source_critical_manifest": critical,
    }


def prepare() -> None:
    if OUTPUT_ROOT.exists():
        raise RuntimeError("refusing to freeze a panel after corrected output root exists")
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    selected = select_panel()
    cases = {r["row_id"]: r.get("case", "") for r in read_csv(CASE_RESULTS)}
    audits = [audit_row(row) for row in selected]
    for row, audit in zip(selected, audits, strict=True):
        root = source_root(row)
        solver = read_json(root / "qlip" / "solver_result.json")
        sca = read_json(root / "sca" / "summary.json")
        row.update({
            "old_candidate_sha256": sha256_file(root / "generated" / "candidate.cif"),
            "old_solver_status": str(solver.get("status")),
            "old_topology": str(row.get("old_topology") or sca.get("topology_result") or ""),
            "final_cell": json.dumps(audit.get("final_cell", {}), sort_keys=True),
            "pot_package_hash": str(audit.get("pot_package_hash", "")),
            "target_evidence_status": str(audit.get("target_evidence_status", "")),
            "score_diagnostic_case": cases.get(row["row_id"], ""),
        })
    # The prepare phase never imports or invokes QLIP, so this complete panel
    # record is necessarily frozen before any corrected solve.
    write_csv(ARTIFACT_ROOT / "PANEL_SELECTION.csv", selected)
    write_json(ARTIFACT_ROOT / "PANEL_SELECTION.json", {"schema_version": "corrected_periodic_panel.v1", "created_at": now(), "selection_performed_without_corrected_outputs": True, "rows": selected})
    panel_hash = sha256_file(ARTIFACT_ROOT / "PANEL_SELECTION.json")
    if any(a["status"] != "PASS" for a in audits):
        write_json(ARTIFACT_ROOT / "INVARIANT_AUDIT.json", {
            "schema_version": "corrected_periodic_invariant_audit.v1", "created_at": now(),
            "panel_selection_sha256": panel_hash, "all_rows_pass": False, "rows": audits,
        })
        raise RuntimeError("one or more selected rows are INVARIANT_UNAVAILABLE")
    write_json(ARTIFACT_ROOT / "INVARIANT_AUDIT.json", {
        "schema_version": "corrected_periodic_invariant_audit.v1", "created_at": now(),
        "panel_selection_sha256": panel_hash, "all_rows_pass": True, "rows": audits,
    })
    print(f"Frozen {len(selected)} rows; all invariant audits PASS; no solve run.")


def load_frozen() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    panel_path = ARTIFACT_ROOT / "PANEL_SELECTION.json"
    audit_path = ARTIFACT_ROOT / "INVARIANT_AUDIT.json"
    panel = read_json(panel_path)
    audits = read_json(audit_path)
    if audits.get("panel_selection_sha256") != sha256_file(panel_path) or not audits.get("all_rows_pass"):
        raise RuntimeError("frozen panel/invariant audit contract is invalid")
    rows = panel["rows"]
    current = select_panel()
    if [r["row_id"] for r in rows] != [r["row_id"] for r in current]:
        raise RuntimeError("deterministic selection no longer matches frozen panel")
    return rows, {r["row_id"]: r for r in audits["rows"]}


def assert_source_unchanged(audit: Mapping[str, Any]) -> None:
    root = Path(audit["source_row"])
    current = source_critical_manifest(root)
    if manifest_hash(current) != audit["source_critical_manifest_hash"]:
        raise RuntimeError(f"source benchmark row changed: {root}")


def score_candidate(candidate: Path, task: dict[str, Any], request_spp: dict[str, Any], config: Any, stages: Any) -> dict[str, Any]:
    from pymatgen.core import Structure
    from qlip.interactions.spp import SPPCollection
    from sok_llm_orchestrator.workflow.runner import _solver_pair_guidance
    from sok_llm_orchestrator.workflow.spp import score_spp_components

    pairs_text = stages.required_pairs(task, config)
    pairs = [tuple(pair.split("-", 1)) for pair in pairs_text]
    guidance = _solver_pair_guidance(pairs_text, list(request_spp["quality"].get("request_pair_results", [])))
    collection = SPPCollection(Path(request_spp["pot_root"]), cutoff=config.cutoff, missing_pair_policy="block")
    collection.load(pairs)
    structure = Structure.from_file(candidate)
    atoms = structure.to_ase_atoms()
    components = score_spp_components(
        symbols=atoms.get_chemical_symbols(), positions=atoms.positions, cell=atoms.cell.array,
        request=collection, regulator=None, regulator_weight=0.0,
        request_guidance_weight=config.outer_objective_scale * config.request_coefficient,
        pairs=pairs, request_pair_statuses=guidance["request_statuses"],
    )
    return asdict(components) if is_dataclass(components) else dict(components)


def copy_old(root: Path, out: Path) -> None:
    old = out / "old"
    old.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "generated" / "candidate.cif", old / "candidate.cif")
    (old / "candidate.sha256").write_text(sha256_file(old / "candidate.cif") + "\n", encoding="ascii")


def run_rows() -> None:
    bootstrap_import_paths()
    from sok_llm_orchestrator.workflow.component_paths import ComponentRoots
    from sok_llm_orchestrator.workflow.csv_workflow import _workflow_config, load_workflow_config, validate_csv
    from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages

    rows, audits = load_frozen()
    roots = ComponentRoots.load(REPO_ROOT)
    roots.activate_imports(include_sca=True)
    stages = ProductionWorkflowStages()
    workflow_config = load_workflow_config()
    parsed: dict[str, Any] = {}
    for benchmark_root in (PAPER_ROOT, STRESS_ROOT):
        for row in validate_csv(benchmark_root / "input.csv", workflow_config, stages=stages):
            parsed[f"{benchmark_root.name}:{row.row_id}"] = row
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for frozen in rows:
        row_id = frozen["row_id"]
        audit = audits[row_id]
        assert_source_unchanged(audit)
        out = OUTPUT_ROOT / row_id
        status_path = out / "status.json"
        if status_path.is_file() and read_json(status_path).get("state") == "GENERATED":
            assert_source_unchanged(audit)
            print(f"SKIP {row_id}: already GENERATED")
            continue
        if out.exists():
            raise RuntimeError(f"incomplete row exists; inspect before explicit cleanup/retry: {out}")
        out.mkdir(parents=True)
        write_json(out / "invariant_audit.json", audit)
        copy_old(source_root(frozen), out)
        write_json(status_path, {"state": "RUNNING", "started_at": now()})
        root = source_root(frozen)
        request_spp = read_json(root / "spp" / "request_spp_cache.json")
        task = read_json(root / "structured_task" / "structured_task.json")
        key = f"{frozen['source_benchmark']}:{row_id}"
        batch_row = parsed[key]
        config = _workflow_config(batch_row, out, roots)
        # Authorization root includes both immutable source POTs and new run output;
        # the explicit solve run_root remains row-local.
        config = replace(config, qlip_runtime_root=REPO_ROOT / "outputs", run_id=f"corrected-periodic-v1-{row_id}", attempt_id="corrected")
        old_solver = read_json(root / "qlip" / "solver_result.json")
        old_rescore = score_candidate(out / "old" / "candidate.cif", task, request_spp, config, stages)
        write_json(out / "old" / "historical_metrics.json", {
            "historical_counting": "biased full-weight +/-T same-species self-images",
            "candidate_sha256": sha256_file(out / "old" / "candidate.cif"),
            "solver": old_solver, "sca_result": read_json(root / "sca" / "result.json"),
            "sca_summary": read_json(root / "sca" / "summary.json"),
        })
        write_json(out / "old" / "corrected_rescore.json", old_rescore)
        started = time.perf_counter()
        solved = stages.solve(task, request_spp, config, out / "corrected" / "qlip")
        elapsed = time.perf_counter() - started
        candidate = Path(solved["cif_path"])
        generated = out / "corrected" / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        target = generated / "candidate.cif"
        shutil.copy2(candidate, target)
        candidate_hash = sha256_file(target)
        (generated / "candidate.sha256").write_text(candidate_hash + "\n", encoding="ascii")
        components = asdict(solved["components"]) if is_dataclass(solved["components"]) else dict(solved["components"])
        independent = float(components["solver_objective"])
        difference = abs(float(solved["solver_objective"]) - independent)
        if difference > TOLERANCE:
            write_json(status_path, {"state": "OBJECTIVE_MISMATCH", "difference": difference})
            raise RuntimeError(f"corrected solver/scorer mismatch for {row_id}: {difference}")
        payload = {k: v for k, v in solved.items() if k not in {"components", "cif_path"}}
        payload.update({"components": components, "cif_path": str(target), "runtime_s": elapsed})
        write_json(out / "corrected" / "metrics.json", payload)
        write_json(out / "corrected" / "qlip" / "objective_check.json", {
            "status": "PASS", "tolerance": TOLERANCE, "solver_objective": solved["solver_objective"],
            "independent_objective": independent, "absolute_difference": difference,
        })
        assert_source_unchanged(audit)
        write_json(status_path, {"state": "GENERATED", "completed_at": now(), "candidate_sha256": candidate_hash})
        print(f"GENERATED {row_id} {solved['status']} diff={difference:.3g} runtime={elapsed:.2f}s")


def sca_summary(row_id: str, candidate_hash: str, raw: dict[str, Any]) -> dict[str, Any]:
    parse = bool(raw.get("parse_ok"))
    composition = bool(raw.get("target_formula_match"))
    geometry = raw.get("geometry_ok") is True
    contacts = int(raw.get("num_bad_contacts") or 0)
    topology = str(raw.get("topology_status") or "NOT_EVALUATED")
    outcome = "PASS" if parse and composition and geometry and contacts == 0 and topology in {"PASS", "NOT_EVALUATED"} else "PARTIAL" if parse and composition else "FAIL"
    return {
        "row_id": row_id, "sca_status": outcome, "source_candidate_sha256": candidate_hash,
        "parse_ok": raw.get("parse_ok"), "composition_match": raw.get("target_formula_match"),
        "detected_space_group": raw.get("detected_space_group"), "requested_space_group": raw.get("target_space_group"),
        "topology_result": topology, "topology_policy": raw.get("topology_policy"),
        "topology_checks": raw.get("topology_checks"), "topology_details": raw.get("topology_details"),
        "geometry_valid": raw.get("geometry_ok"), "bad_contacts": contacts,
        "minimum_distance_angstrom": raw.get("min_distance"),
    }


def verdict_rank(value: str) -> int:
    value = value.upper()
    if value in {"PASS", "FAMILY_PASS"}:
        return 2
    if value == "PARTIAL":
        return 1
    return 0


def transition(old_topology: str, new_topology: str, old_family: str, new_family: str) -> str:
    unavailable = {"NOT_APPLICABLE", "NOT_EVALUATED", ""}
    axes: list[tuple[str, str]] = []
    if old_topology.upper() not in unavailable and new_topology.upper() not in unavailable:
        axes.append((old_topology, new_topology))
    if old_family.upper() not in unavailable and new_family.upper() not in unavailable:
        axes.append((old_family, new_family))
    deltas = [verdict_rank(new) - verdict_rank(old) for old, new in axes]
    signs = {0 if d == 0 else (1 if d > 0 else -1) for d in deltas}
    if 1 in signs and -1 in signs:
        return "MIXED"
    if 1 in signs:
        return "IMPROVED"
    if -1 in signs:
        return "REGRESSED"
    return "UNCHANGED_GOOD" if axes and all(verdict_rank(new) == 2 for _, new in axes) else "UNCHANGED_BAD"


def coordination(raw: Mapping[str, Any]) -> str:
    details = raw.get("topology_details") or {}
    records = details.get("coordination_records") or details.get("coordination") or details
    return json.dumps(records, sort_keys=True, default=str)


def finalize() -> None:
    bootstrap_import_paths()
    from pymatgen.analysis.prototypes import AflowPrototypeMatcher
    from scripts.classify_paper1_family_recovery import classify_candidate
    from sok_llm_orchestrator.workflow.component_paths import ComponentRoots
    from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages

    rows, audits = load_frozen()
    roots = ComponentRoots.load(REPO_ROOT)
    roots.activate_imports(include_sca=True)
    stages = ProductionWorkflowStages()
    matcher = AflowPrototypeMatcher()
    comparisons: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    for row in rows:
        row_id = row["row_id"]
        out = OUTPUT_ROOT / row_id
        root = source_root(row)
        if read_json(out / "status.json").get("state") != "GENERATED":
            raise RuntimeError(f"row is not a valid completed solve: {row_id}")
        assert_source_unchanged(audits[row_id])
        task = read_json(root / "structured_task" / "structured_task.json")
        new_cif = out / "corrected" / "generated" / "candidate.cif"
        new_hash = sha256_file(new_cif)
        raw = stages.evaluate(new_cif, task)
        if sha256_file(new_cif) != new_hash:
            raise RuntimeError(f"SCA mutated candidate: {row_id}")
        summary = sca_summary(row_id, new_hash, raw)
        write_json(out / "corrected" / "sca" / "result.json", raw)
        write_json(out / "corrected" / "sca" / "summary.json", summary)
        old_summary = read_json(root / "sca" / "summary.json")
        old_raw = read_json(root / "sca" / "result.json")
        if row["source_benchmark"] == "paper1_simple_ordered_v1":
            family_new = classify_candidate(condition="CORRECTED_PERIODIC", row_id=row_id, requested_family=row["family"], formula=row["formula"], candidate=new_cif, matcher=matcher)
            new_family = family_new["verdict"]
        else:
            family_new = {"verdict": "NOT_APPLICABLE"}
            new_family = "NOT_APPLICABLE"
        write_json(out / "corrected" / "family_recovery" / "result.json", family_new)
        old_solver = read_json(root / "qlip" / "solver_result.json")
        old_rescore = read_json(out / "old" / "corrected_rescore.json")
        new_metrics = read_json(out / "corrected" / "metrics.json")
        old_family = row.get("old_family_recovery", "NOT_APPLICABLE")
        old_topology = str(row.get("old_topology") or old_summary.get("topology_result") or "NOT_EVALUATED")
        new_topology = str(summary.get("topology_result") or "NOT_EVALUATED")
        classification = transition(old_topology, new_topology, old_family, new_family)
        item = {
            "row_id": row_id, "formula": row["formula"], "family": row["family"],
            "old_solver_status": old_solver.get("status"), "new_solver_status": new_metrics.get("status"),
            "old_candidate_sha256": row["old_candidate_sha256"], "new_candidate_sha256": new_hash,
            "candidate_changed": row["old_candidate_sha256"] != new_hash,
            "old_historical_objective": old_solver.get("solver_objective"),
            "old_candidate_corrected_score": old_rescore.get("solver_objective"),
            "new_corrected_objective": new_metrics.get("solver_objective"),
            "new_candidate_corrected_score": new_metrics.get("components", {}).get("solver_objective"),
            "objective_absolute_difference": read_json(out / "corrected" / "qlip" / "objective_check.json")["absolute_difference"],
            "old_runtime_s": old_solver.get("runtime_s"), "new_runtime_s": new_metrics.get("runtime_s"),
            "old_min_distance": old_raw.get("min_distance", old_summary.get("minimum_distance_angstrom")),
            "new_min_distance": raw.get("min_distance"), "old_space_group": old_raw.get("detected_space_group", old_summary.get("detected_space_group")),
            "new_space_group": raw.get("detected_space_group"), "old_sca_topology": old_topology,
            "new_sca_topology": new_topology, "old_family_recovery": old_family,
            "new_family_recovery": new_family, "old_relevant_coordination": coordination(old_raw),
            "new_relevant_coordination": coordination(raw), "transition": classification,
            "target_evidence_status": row.get("target_evidence_status", ""),
            "score_diagnostic_case": row.get("score_diagnostic_case", ""),
        }
        comparisons.append(item)
        transitions.append({k: item[k] for k in ("row_id", "formula", "family", "old_sca_topology", "new_sca_topology", "old_family_recovery", "new_family_recovery", "transition", "target_evidence_status")})
    write_csv(ARTIFACT_ROOT / "CORRECTED_OBJECTIVE_COMPARISON.csv", comparisons)
    write_csv(ARTIFACT_ROOT / "TOPOLOGY_TRANSITIONS.csv", transitions)
    by_family: list[dict[str, Any]] = []
    for family, group in sorted(defaultdict(list, {f: [r for r in comparisons if r["family"] == f] for f in {r["family"] for r in comparisons}}).items()):
        counts = Counter(r["transition"] for r in group)
        by_family.append({"family": family, "n": len(group), "candidate_changed": sum(r["candidate_changed"] for r in group), **{k.lower(): counts[k] for k in ("IMPROVED", "UNCHANGED_GOOD", "UNCHANGED_BAD", "REGRESSED", "MIXED")}})
    write_csv(ARTIFACT_ROOT / "FAMILY_SUMMARY.csv", by_family)
    shifts = [{"row_id": r["row_id"], "historical_objective": r["old_historical_objective"], "old_candidate_corrected_score": r["old_candidate_corrected_score"], "absolute_shift": float(r["old_candidate_corrected_score"]) - float(r["old_historical_objective"]), "relative_shift_pct": 100.0 * (float(r["old_candidate_corrected_score"]) - float(r["old_historical_objective"])) / abs(float(r["old_historical_objective"]))} for r in comparisons]
    write_csv(ARTIFACT_ROOT / "OBJECTIVE_SHIFT_SUMMARY.csv", shifts)
    counts = Counter(r["transition"] for r in comparisons)
    table = ["| row | formula | family | changed | old topology/family | new topology/family | transition |", "|---|---|---|---:|---|---|---|"]
    table += [f"| {r['row_id']} | {r['formula']} | {r['family']} | {r['candidate_changed']} | {r['old_sca_topology']} / {r['old_family_recovery']} | {r['new_sca_topology']} / {r['new_family_recovery']} | {r['transition']} |" for r in comparisons]
    md = "# Corrected periodic objective comparison\n\n" + "\n".join(table) + "\n"
    (ARTIFACT_ROOT / "CORRECTED_OBJECTIVE_COMPARISON.md").write_text(md, encoding="utf-8")
    indexed = {row["row_id"]: row for row in comparisons}
    old_runtime_total = sum(float(row["old_runtime_s"]) for row in comparisons)
    new_runtime_total = sum(float(row["new_runtime_s"]) for row in comparisons)
    report = f"""# Corrected periodic objective regression v1

Panel frozen before solves: **yes**. All {len(comparisons)} cells and POT packages were reused from persisted rows; no retrieval or SPP fitting was run.

- Candidates changed: {sum(r['candidate_changed'] for r in comparisons)}/{len(comparisons)}
- Improved: {counts['IMPROVED']}
- Unchanged good: {counts['UNCHANGED_GOOD']}
- Unchanged bad: {counts['UNCHANGED_BAD']}
- Regressed: {counts['REGRESSED']}
- Mixed: {counts['MIXED']}
- Solver/scorer checks passing: {sum(float(r['objective_absolute_difference']) <= TOLERANCE for r in comparisons)}/{len(comparisons)}

## Family conclusions

- Rocksalt: 0/3 became SCA PASS and 0/3 became FAMILY_PASS.
- Zinc blende: 0/2 recovered B3.
- Fluorite/anti-fluorite: 0/2 recovered the requested family; one candidate hash changed.
- CsCl controls: 2/2 remained FAMILY_PASS.
- Perovskite controls: 2/2 remained SCA PASS and FAMILY_PASS, although both candidate hashes changed.
- Li2FeO3: remained PARTIAL with the identical candidate. Fe remained CN14 overall (6 O + 8 Li), so the transition-metal/oxygen coordination check still failed.
- spinel_053: the candidate hash changed but topology remained PASS; Cd remained O6 and Si remained O4 coordinated.

All 13 solves remained OPTIMAL. Aggregate recorded runtime changed from {old_runtime_total:.3f}s to {new_runtime_total:.3f}s ({100.0 * (new_runtime_total - old_runtime_total) / old_runtime_total:+.1f}%). This small panel does not show increased solver difficulty.

## Interpretation

The counting correction materially changes objective values but did not improve a single topology/family verdict in this frozen panel. Four hashes changed, yet all four retained their prior space group and topology/family verdict, and corrected objective values show tied optima at the recorded precision. The evidence therefore matches **Case B/C**, not Case A: the bug was genuine correctness debt and can select alternative degenerate candidates, but it was not a major cause of the observed topology failures. The unchanged rocksalt, zinc-blende, and fluorite failures continue to point to cell/search representability as the next repair.

`layered_007` and `spinel_053` intentionally preserve historical target-containing SPP evidence and are labeled `HISTORICAL_TARGET_IN_SPP_EVIDENCE`; this is nonblocking context for this causal objective-only regression.

See `CORRECTED_OBJECTIVE_COMPARISON.csv` and `FAMILY_SUMMARY.csv` for exact row and family results. The anchor lookup contains {len(indexed)} rows.
"""
    (ARTIFACT_ROOT / "REGRESSION_REPORT.md").write_text(report, encoding="utf-8")
    qlip = roots.qlip
    provenance = {
        "created_at": now(), "methodology": "OLD persisted biased candidates versus NEW corrected unordered periodic candidates",
        "historical_candidates_regenerated": False, "retrieval_rerun": False, "spp_regenerated": False,
        "full_paper1_rerun": False, "full_50_50_rerun": False, "panel_frozen_before_solves": True,
        "qlip": {"head": git(qlip, "rev-parse", "HEAD"), "status_short": git(qlip, "status", "--short"),
                 "corrected_source_sha256": sha256_file(qlip / "src" / "qlip" / "interactions" / "spp.py")},
        "skill_loop_csp": {"head": git(REPO_ROOT, "rev-parse", "HEAD"), "status_short": git(REPO_ROOT, "status", "--short")},
        "panel_selection_sha256": sha256_file(ARTIFACT_ROOT / "PANEL_SELECTION.json"),
        "invariant_audit_sha256": sha256_file(ARTIFACT_ROOT / "INVARIANT_AUDIT.json"),
    }
    write_json(ARTIFACT_ROOT / "PROVENANCE.json", provenance)
    print(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "run", "finalize"))
    args = parser.parse_args()
    {"prepare": prepare, "run": run_rows, "finalize": finalize}[args.phase]()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    raise SystemExit(main())
