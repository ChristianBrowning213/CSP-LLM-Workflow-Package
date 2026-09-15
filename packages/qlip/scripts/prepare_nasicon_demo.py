"""Prepare the protected three-task NASICON end-to-end demonstration."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from ase.formula import Formula
from pymatgen.core import Composition

from qlip.core.chemistry import preflight_charge
from qlip.paper_diversity.record_identity import RecordIdentity, verify_embedding_record
from qlip.paper_diversity.smoke_preparation import (
    canonical_hash,
    load_frozen_e4_tasks,
    preflight_task,
    resolve_skill_loop_root,
    task_orbits,
)
from qlip.scaffolds import get_scaffold, list_scaffolds


TASK_IDS = ("E4_A2", "E4_C2", "E4_F1")
EVOLVING_DIRS = {"representability", "engineering_smoke", "nasicon_demo", "pilot"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def structured_intent_hash(task: dict[str, str]) -> str:
    return canonical_hash({key: value for key, value in task.items() if key not in {"natural_language_request", "short_request_label"}})


def charge_assumptions(formula: str) -> dict[str, Any]:
    counts = {str(species): int(count) for species, count in Formula(formula).count().items()}
    states = {
        species: 1 if species in {"Li", "Na", "K", "Rb", "Cs"} else -2 if species == "O" else 5 if species == "P" else 4
        for species in counts if species in {"Li", "Na", "K", "Rb", "Cs", "O", "P", "Si"}
    }
    unknown = sorted(set(counts) - set(states))
    if len(unknown) != 1:
        raise ValueError(f"Expected one framework-centre oxidation state for {formula}: {unknown}")
    framework = unknown[0]
    remainder = -sum(counts[species] * states[species] for species in states)
    if remainder % counts[framework]:
        raise ValueError(f"Non-integral inferred oxidation state for {formula}")
    states[framework] = remainder // counts[framework]
    chemistry = {
        "formula": formula,
        "charge_policy": "EXPLICIT_REQUIRED",
        "oxidation_states": states,
        "compensation_operation": "none",
        "assumptions_source": "formal charge balance: alkali +1, O -2, P +5, Si +4; sole octahedral framework state inferred",
    }
    result = preflight_charge(chemistry)
    if not result.accepted or result.charge_sum != 0 or not result.charge_neutral:
        raise ValueError(f"Charge preflight failed: {result.to_dict()}")
    return {"chemistry": chemistry, "result": result.to_dict()}


def add_check(rows: list[dict[str, Any]], category: str, identifier: str, expected: str, actual: str, path: Path | None = None) -> None:
    rows.append({
        "category": category, "identifier": identifier, "path": str(path) if path else "",
        "expected_sha256": expected, "actual_sha256": actual, "status": "PASS" if expected == actual else "FAIL",
    })


def embedding_identity_records(skill: Path) -> tuple[list[RecordIdentity], list[RecordIdentity], dict[str, dict[str, Any]]]:
    corpus_art = skill / "artifacts" / "paper_diversity_v2" / "nasicon_corpus"
    corpus = skill / "data" / "corpora" / "nasicon_specialist_v3"
    manifest = {row["internal_id"]: row for row in (json.loads(line) for line in (corpus / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())}
    audit = read_csv(corpus_art / "NASICON_V3_EMBEDDING_AUDIT.csv")
    archive = [
        RecordIdentity(
            raw_internal_id=row["structure_id"], raw_source=manifest[row["structure_id"]]["source"],
            raw_source_id=manifest[row["structure_id"]]["source_id"], description_sha256=row["description_sha256"],
            embedding_sha256=row["embedding_sha256"], embedding_dimension=int(row["embedding_dimension"]),
            embedding_model=row["embedding_model"],
            archive_key=f"records/{row['structure_id']}.json#representations.text_embedding",
            payload=row,
        ) for row in audit
    ]
    db = sqlite3.connect(corpus / "crystaldb.sqlite"); db.row_factory = sqlite3.Row
    rows = db.execute(
        "select s.structure_id,p.source,p.source_id,td.text_sha256,te.model,te.model_version,te.dim,te.vector "
        "from structures s join provenance p on p.structure_id=s.structure_id join text_docs td on td.structure_id=s.structure_id "
        "join text_embeddings te on te.text_doc_id=td.id where te.embed_engine='lmstudio' and te.model='text-embedding-bge-m3' "
        "and te.model_version='lmstudio_v1' and te.status='OK'"
    ).fetchall()
    db.close()
    database = [
        RecordIdentity(
            raw_internal_id=str(row["structure_id"]), raw_source=str(row["source"]), raw_source_id=str(row["source_id"]),
            description_sha256=str(row["text_sha256"]), embedding_sha256=sha_text(str(row["vector"])),
            embedding_dimension=int(row["dim"]), embedding_model=str(row["model"]), embedding_vector=str(row["vector"]),
            payload={"model_version": row["model_version"]},
        ) for row in rows
    ]
    return archive, database, manifest


def write_embedding_identifier_diagnostic(skill: Path, out: Path) -> None:
    archive, database, manifest = embedding_identity_records(skill)
    rows: list[dict[str, Any]] = []
    for item in archive[:11]:
        result = verify_embedding_record(item, database)
        actual = result.database
        source = manifest[item.raw_internal_id]
        rows.append({
            "corpus_manifest_id": source["internal_id"],
            "embedding_audit_structure_id": item.raw_internal_id,
            "embedding_archive_filename_or_key": item.archive_key,
            "database_internal_structure_id": actual.raw_internal_id if actual else "",
            "database_source": actual.raw_source if actual else "",
            "database_source_id": actual.raw_source_id if actual else "",
            "canonical_source": item.canonical_key.canonical_source,
            "canonical_source_id": item.canonical_key.canonical_source_id,
            "description_sha256": item.description_sha256,
            "embedding_sha256": item.embedding_sha256,
            "embedding_dimension": item.embedding_dimension,
            "embedding_model": item.embedding_model,
            "resolution_method": result.resolution_method,
            "verification_status": result.status,
        })
    write_csv(out / "EMBEDDING_IDENTIFIER_DIAGNOSTIC.csv", rows)
    (out / "EMBEDDING_IDENTIFIER_DIAGNOSTIC.md").write_text(
        "# NASICON embedding identifier diagnostic\n\n"
        "The archive uses internal keys such as `nasicon-mp1229309`, the corpus manifest records Materials Project "
        "source ID `mp-1229309`, and Crystal-DB stores an unrelated database structure ID plus source ID "
        "`nasicon-mp1229309.cif`. These resolve to the structured canonical key "
        "`(materials_project, mp-1229309)`. Resolution uses exact database internal ID first, canonical source/source ID "
        "second, and exact description hash third; substring matching is not used.\n\n"
        f"Diagnostic records: **{len(rows)}**; PASS: **{sum(row['verification_status']=='PASS' for row in rows)}**.\n",
        encoding="utf-8",
    )


def protected_gate(skill: Path, out: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    prior = skill.parent / "Structured_Crystal_Analyser" / "artifacts" / "paper_full_sca_v1" / "input" / "INPUT_HASH_MANIFEST.csv"
    for row in read_csv(prior):
        path = Path(row["path"])
        add_check(checks, "protected_prior_campaign", row["candidate_id"], row["sha256"], sha_file(path) if path.is_file() else "MISSING", path)

    freeze = skill / "artifacts" / "paper_diversity_v2" / "final" / "OUTPUT_HASH_MANIFEST.csv"
    for row in read_csv(freeze):
        path = Path(row["path"])
        try:
            relative = path.resolve().relative_to((skill / "artifacts" / "paper_diversity_v2").resolve())
        except ValueError:
            relative = None
        if relative and relative.parts and relative.parts[0] in EVOLVING_DIRS:
            continue
        if "nasicon_specialist_v3" in path.parts:
            continue
        add_check(checks, "frozen_paper_diversity_preflight", str(path), row["sha256"], sha_file(path) if path.is_file() else "MISSING", path)

    corpus_art = skill / "artifacts" / "paper_diversity_v2" / "nasicon_corpus"
    corpus = skill / "data" / "corpora" / "nasicon_specialist_v3"
    for row in read_csv(corpus_art / "NASICON_V3_RETAINED_MANIFEST.csv"):
        path = corpus / "cifs" / f"{row['internal_id']}.cif"
        add_check(checks, "nasicon_cif", row["internal_id"], row["cif_sha256"], sha_file(path) if path.is_file() else "MISSING", path)

    for row in read_csv(corpus_art / "NASICON_V3_ROBOCRYS_AUDIT.csv"):
        add_check(checks, "robocrys_description", row["structure_id"], row["description_sha256"], sha_text(row["description_text"]))

    archive, database, _ = embedding_identity_records(skill)
    for item in archive:
        result = verify_embedding_record(item, database)
        actual = result.database.embedding_sha256 if result.database else "MISSING"
        checks.append({
            "category": "bge_m3_embedding", "identifier": item.raw_internal_id, "path": item.archive_key,
            "expected_sha256": item.embedding_sha256, "actual_sha256": actual, "status": result.status,
        })

    for scaffold in list_scaffolds():
        path = Path(scaffold.source_cif_path)
        add_check(checks, "scaffold_source", scaffold.scaffold_id, scaffold.source_cif_sha256, sha_file(path) if path.is_file() else "MISSING", path)

    write_csv(out / "PRE_GENERATION_HASH_CHECK.csv", checks)
    failed = [row for row in checks if row["status"] != "PASS"]
    if failed:
        raise AssertionError(f"Protected hash mismatch: {failed[:5]}")
    return checks


def main() -> int:
    skill = resolve_skill_loop_root()
    tasks = load_frozen_e4_tasks(skill)
    out = skill / "artifacts" / "paper_diversity_v2" / "nasicon_demo"
    out.mkdir(parents=True, exist_ok=True)
    leave = [json.loads(line) for line in (skill / "data" / "corpora" / "nasicon_specialist_all_targets_out_v3" / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    leave_formulas = {Composition(row["reduced_formula"]).reduced_formula for row in leave}

    task_rows: list[dict[str, Any]] = []
    preflight_rows: list[dict[str, Any]] = []
    diversity_rows: list[dict[str, Any]] = []
    for task_id in TASK_IDS:
        task = tasks[task_id]
        pf = preflight_task(task, leave_formulas)
        scaffold = get_scaffold(pf["scaffold_id"])
        orbits = task_orbits(task, scaffold)
        fixed = [orbit["orbit_id"] for orbit in orbits if len(orbit["allowed_species"]) == 1]
        variable = [orbit["orbit_id"] for orbit in orbits if len(orbit["allowed_species"]) > 1]
        variable_species = sorted({species for orbit in orbits if len(orbit["allowed_species"]) > 1 for species in orbit["allowed_species"]})
        charge = charge_assumptions(task["target_formula"])
        row = {
            "task_id": task_id,
            "natural_language_request": task["natural_language_request"],
            "structured_intent_hash": structured_intent_hash(task),
            "target_formula": task["target_formula"],
            "requested_space_group": task["allowed_space_groups"],
            "scaffold_id": scaffold.scaffold_id,
            "scaffold_version": scaffold.scaffold_version,
            "scaffold_source_hash": scaffold.source_cif_sha256,
            "search_space_hash": pf["search_space_sha256"],
            "fixed_orbits": ";".join(fixed),
            "variable_orbits": ";".join(variable),
            "variable_species": ";".join(variable_species),
            "orbit_multiplicities": pf["orbit_multiplicities"],
            "charge_policy": charge["result"]["charge_policy"],
            "topology_policy": scaffold.topology_policy,
            "retrieval_database": "nasicon_specialist_all_targets_out_v3",
            "spp_policy": task["spp_policy"],
            "representability_status": "READY_FOR_DEMO",
        }
        task_rows.append(row)
        checks = {
            "request_hash": sha_text(task["natural_language_request"]),
            "integer_occupation_feasible": pf["integer_occupation_feasible"],
            "space_group_match": pf["space_group_match"],
            "topology_policy_applicable": pf["topology_policy_available"],
            "exact_formula_leakage_count": pf["exact_target_leakage_count"],
            "charge_preflight": json.dumps(charge["result"], sort_keys=True, separators=(",", ":")),
            "preflight_status": "READY_FOR_DEMO",
        }
        if not all(bool(checks[key]) for key in ("integer_occupation_feasible", "space_group_match", "topology_policy_applicable")) or checks["exact_formula_leakage_count"] != 0:
            raise AssertionError(f"Demo task not ready: {task_id}: {pf}")
        preflight_rows.append({**row, **checks})
        diversity_rows.append({
            "task_id": task_id, "reduced_formula": Composition(task["target_formula"]).reduced_formula,
            "mobile_ion_chemistry": ";".join(sorted(set(Formula(task["target_formula"]).count()) & {"Li", "Na"})),
            "framework_chemistry": ";".join(sorted(set(Formula(task["target_formula"]).count()) - {"Li", "Na", "O"})),
            "scaffold_id": scaffold.scaffold_id, "space_group": scaffold.source_space_group,
            "occupation_problem": "Si/P closed-orbit choice" if variable else "fixed full-orbit role occupation",
        })

    if len({row["search_space_hash"] for row in task_rows}) != 3 or len({row["reduced_formula"] for row in diversity_rows}) != 3 or len({row["scaffold_id"] for row in diversity_rows}) != 3:
        raise AssertionError("Demo tasks are not distinct in required scientific dimensions")
    write_csv(out / "NASICON_DEMO_TASKS.csv", task_rows)
    write_csv(out / "NASICON_DEMO_PREFLIGHT.csv", preflight_rows)
    (out / "NASICON_DEMO_ABSTENTION_CASE.md").write_text(
        "# NASICON demonstration abstention case\n\n"
        "- task_id: `E4_A1`\n- status: `UNSUPPORTED_ORDERED_MODEL_REQUIRES_DISORDER`\n"
        "- requested_formula: `Na3Zr2Si2PO12`\n- requested_space_group: `R-3c`\n"
        "- tetrahedral_orbit_multiplicity: `6`\n- required_Si_count: `4`\n- required_P_count: `2`\n\n"
        "A single symmetry-closed multiplicity-6 tetrahedral orbit cannot represent an ordered 4:2 Si/P split while retaining R-3c. "
        "Supporting the request would require partial/disordered occupation or symmetry lowering. No CIF was generated, and this is an abstention rather than a failed candidate.\n",
        encoding="utf-8",
    )
    write_embedding_identifier_diagnostic(skill, out)
    hash_checks = protected_gate(skill, out)
    print(json.dumps({"tasks": list(TASK_IDS), "ready": 3, "protected_hash_checks": len(hash_checks), "hash_failures": 0, "generation_launched": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
