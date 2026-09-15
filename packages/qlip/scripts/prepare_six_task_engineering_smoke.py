"""Prepare and hash-gate the authorized six-task NASICON engineering smoke."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from ase.formula import Formula

from qlip.core.chemistry import preflight_charge
from qlip.paper_diversity.smoke_preparation import canonical_hash, task_orbits
from qlip.scaffolds import get_scaffold, list_scaffolds


TASK_IDS = ("E4_A2", "E4_C1", "E4_C2", "E4_C4", "E4_F2", "E4_F1")
EVOLVING_PREFLIGHT_DIRS = {"representability", "engineering_smoke", "pilot"}


def repo_root() -> Path:
    cursor = Path(__file__).resolve().parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "qlip").is_dir():
            return candidate
    raise RuntimeError("QLIP repository root not found")


def skill_root() -> Path:
    path = repo_root().parent / "Skill-Loop-CSP"
    if not (path / "benchmarks" / "paper_diversity_v2").is_dir():
        raise RuntimeError(f"Skill-Loop-CSP sibling repository missing: {path}")
    return path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def explicit_charge(formula: str) -> dict[str, Any]:
    counts = {str(species): int(count) for species, count in Formula(formula).count().items()}
    states: dict[str, int] = {}
    for species in counts:
        if species in {"Li", "Na", "K", "Rb", "Cs"}:
            states[species] = 1
        elif species == "O":
            states[species] = -2
        elif species == "P":
            states[species] = 5
        elif species == "Si":
            states[species] = 4
    unknown = sorted(set(counts) - set(states))
    if len(unknown) != 1:
        raise ValueError(f"Expected one framework oxidation state to infer for {formula}, found {unknown}")
    framework = unknown[0]
    known_charge = sum(counts[species] * states[species] for species in states)
    numerator = -known_charge
    if numerator % counts[framework]:
        raise ValueError(f"No integral charge-neutral framework oxidation state for {formula}")
    states[framework] = numerator // counts[framework]
    chemistry = {
        "formula": formula,
        "charge_policy": "EXPLICIT_REQUIRED",
        "oxidation_states": states,
        "compensation_operation": "none",
        "assumptions_source": "formal charge neutrality using alkali +1, O -2, P +5, Si +4; single framework-centre state inferred",
    }
    result = preflight_charge(chemistry)
    if not result.accepted or not result.charge_neutral or result.charge_sum != 0:
        raise ValueError(f"Explicit charge preflight failed for {formula}: {result.to_dict()}")
    return {"chemistry": chemistry, "preflight": result.to_dict()}


def structured_hash(task: dict[str, str]) -> str:
    structured = {key: value for key, value in task.items() if key not in {"natural_language_request", "short_request_label"}}
    return canonical_hash(structured)


def blocker_record(task: dict[str, str], preflight: dict[str, str], codes: list[str], topology_available: bool) -> dict[str, Any]:
    return {
        "task_id": task["task_id"],
        "requested_formula": task["target_formula"],
        "requested_space_group": task["allowed_space_groups"],
        "available_scaffold_id": preflight["scaffold_id"],
        "available_scaffold_space_group": preflight["source_space_group"],
        "exact_composition_match": True,
        "symmetry_match": False,
        "topology_validator_available": topology_available,
        "blocker_codes": ";".join(codes),
        "scientific_reason": (
            "The verified available scaffold does not realize the frozen requested space group."
            + (" The current topology proxy does not cover Hf as a framework octahedral centre." if not topology_available else "")
        ),
        "permitted_resolution": "Find a hash-verified exact-formula scaffold whose redetected symmetry matches the frozen request; independently extend topology validation by generic scaffold roles where needed.",
        "forbidden_shortcuts": "change requested space group;ignore requested symmetry;perturb coordinates to fabricate a scaffold;change target formula;mark topology PASS without an applicable validator",
    }


def write_blocker_report(path: Path, record: dict[str, Any], classification: str) -> None:
    shortcuts = [
        "Changing P2_1/c to Cc.",
        "Changing C2/c to P1.",
        "Ignoring the requested symmetry.",
        "Applying coordinate perturbations to fabricate a new scaffold.",
        "Changing the target formula.",
        "Marking topology PASS without an applicable validator.",
    ]
    path.write_text(
        f"# {record['task_id']} blocker report\n\n"
        f"Classification: **{classification}**.\n\n"
        f"- Requested formula: `{record['requested_formula']}`\n"
        f"- Requested space group: `{record['requested_space_group']}`\n"
        f"- Available scaffold: `{record['available_scaffold_id']}`\n"
        f"- Available scaffold space group: `{record['available_scaffold_space_group']}`\n"
        f"- Exact composition match: `{record['exact_composition_match']}`\n"
        f"- Symmetry match: `{record['symmetry_match']}`\n"
        f"- Topology validator available: `{record['topology_validator_available']}`\n"
        f"- Blocker codes: `{record['blocker_codes']}`\n\n"
        f"Scientific reason: {record['scientific_reason']}\n\n"
        f"Permitted resolution: {record['permitted_resolution']}\n\n"
        "## Forbidden shortcuts\n\n" + "".join(f"- {item}\n" for item in shortcuts),
        encoding="utf-8",
    )


def add_check(rows: list[dict[str, Any]], category: str, identifier: str, path: Path | None, expected: str, actual: str) -> None:
    rows.append({
        "category": category,
        "identifier": identifier,
        "path": str(path) if path else "",
        "expected_sha256": expected,
        "actual_sha256": actual,
        "status": "PASS" if expected == actual else "FAIL",
    })


def protected_hash_gate(skill: Path, smoke: Path, manifest_rows: list[dict[str, Any]], tasks: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    sca_manifest = skill.parent / "Structured_Crystal_Analyser" / "artifacts" / "paper_full_sca_v1" / "input" / "INPUT_HASH_MANIFEST.csv"
    for row in read_csv(sca_manifest):
        path = Path(row["path"])
        actual = sha_file(path) if path.is_file() else "MISSING"
        add_check(checks, "protected_prior_campaign", row["candidate_id"], path, row["sha256"], actual)

    frozen_manifest = skill / "artifacts" / "paper_diversity_v2" / "final" / "OUTPUT_HASH_MANIFEST.csv"
    for row in read_csv(frozen_manifest):
        path = Path(row["path"])
        try:
            relative = path.resolve().relative_to((skill / "artifacts" / "paper_diversity_v2").resolve())
        except ValueError:
            relative = None
        if relative and relative.parts and relative.parts[0] in EVOLVING_PREFLIGHT_DIRS:
            continue
        if "nasicon_specialist_v3" in path.parts:
            continue
        actual = sha_file(path) if path.is_file() else "MISSING"
        add_check(checks, "frozen_paper_diversity_preflight", str(path), path, row["sha256"], actual)

    retained = read_csv(skill / "artifacts" / "paper_diversity_v2" / "nasicon_corpus" / "NASICON_V3_RETAINED_MANIFEST.csv")
    corpus_root = skill / "data" / "corpora" / "nasicon_specialist_v3"
    for row in retained:
        path = corpus_root / "cifs" / f"{row['internal_id']}.cif"
        add_check(checks, "nasicon_cif", row["internal_id"], path, row["cif_sha256"], sha_file(path) if path.is_file() else "MISSING")

    robocrys = read_csv(skill / "artifacts" / "paper_diversity_v2" / "nasicon_corpus" / "NASICON_V3_ROBOCRYS_AUDIT.csv")
    for row in robocrys:
        add_check(checks, "robocrys_description", row["structure_id"], None, row["description_sha256"], sha_text(row["description_text"]))

    embedding = {row["structure_id"]: row for row in read_csv(skill / "artifacts" / "paper_diversity_v2" / "nasicon_corpus" / "NASICON_V3_EMBEDDING_AUDIT.csv")}
    db = sqlite3.connect(corpus_root / "crystaldb.sqlite")
    db.row_factory = sqlite3.Row
    vectors = db.execute(
        "select p.source_id,te.vector from text_embeddings te join text_docs td on td.id=te.text_doc_id "
        "join provenance p on p.structure_id=td.structure_id where te.embed_engine='lmstudio' "
        "and te.model='text-embedding-bge-m3' and te.model_version='lmstudio_v1' and te.status='OK'"
    ).fetchall()
    db.close()
    vector_map = {"nasicon-" + str(row["source_id"]).removesuffix(".cif"): str(row["vector"]) for row in vectors}
    for structure_id, row in embedding.items():
        actual = sha_text(vector_map[structure_id]) if structure_id in vector_map else "MISSING"
        add_check(checks, "bge_m3_embedding", structure_id, None, row["embedding_sha256"], actual)

    for scaffold in list_scaffolds():
        path = Path(scaffold.source_cif_path)
        add_check(checks, "scaffold_source", scaffold.scaffold_id, path, scaffold.source_cif_sha256, sha_file(path) if path.is_file() else "MISSING")

    registry_manifest = skill / "artifacts" / "paper_diversity_v2" / "representability" / "NASICON_SCAFFOLD_PROVENANCE.json"
    expected_registry = next(
        (row["sha256"] for row in read_csv(frozen_manifest) if Path(row["path"]).resolve() == registry_manifest.resolve()),
        "MISSING_EXPECTATION",
    )
    add_check(checks, "scaffold_registry_manifest", registry_manifest.name, registry_manifest, expected_registry, sha_file(registry_manifest))

    by_id = {row["task_id"]: row for row in manifest_rows}
    for task_id in TASK_IDS:
        task = tasks[task_id]
        add_check(checks, "task_request", task_id, None, by_id[task_id]["request_hash"], sha_text(task["natural_language_request"]))
        add_check(checks, "task_structured_intent", task_id, None, by_id[task_id]["structured_intent_hash"], structured_hash(task))

    write_csv(smoke / "PRE_GENERATION_HASH_CHECK.csv", checks)
    failed = [row for row in checks if row["status"] != "PASS"]
    if failed:
        raise AssertionError(f"Protected pre-generation hash mismatch: {failed[:5]}")
    return checks


def main() -> int:
    skill = skill_root()
    benchmark = skill / "benchmarks" / "paper_diversity_v2"
    representability = skill / "artifacts" / "paper_diversity_v2" / "representability"
    smoke = skill / "artifacts" / "paper_diversity_v2" / "engineering_smoke"
    smoke.mkdir(parents=True, exist_ok=True)
    tasks = {row["task_id"]: row for row in read_csv(benchmark / "EXP4_NASICON_32_TASKS.csv")}
    preflight8 = {row["task_id"]: row for row in read_csv(representability / "REVISED_FIRST_EIGHT_PREFLIGHT.csv")}
    revised8 = {row["task_id"]: row for row in read_csv(representability / "REVISED_FIRST_EIGHT_TASKS.csv")}

    a3 = blocker_record(tasks["E4_A3"], preflight8["E4_A3"], ["BLOCKED_MISSING_EXACT_SYMMETRY_SCAFFOLD"], True)
    a4 = blocker_record(
        tasks["E4_A4"], preflight8["E4_A4"],
        ["BLOCKED_MISSING_EXACT_SYMMETRY_SCAFFOLD", "BLOCKED_TOPOLOGY_VALIDATOR_FRAMEWORK_CENTRE"], False,
    )
    write_csv(representability / "FIRST_EIGHT_BLOCKER_SUMMARY.csv", [a3, a4])
    write_blocker_report(representability / "E4_A3_BLOCKER_REPORT.md", a3, "BLOCKED_MISSING_EXACT_SYMMETRY_SCAFFOLD")
    write_blocker_report(
        representability / "E4_A4_BLOCKER_REPORT.md", a4,
        "BLOCKED_MISSING_EXACT_SYMMETRY_SCAFFOLD; BLOCKED_TOPOLOGY_VALIDATOR_FRAMEWORK_CENTRE",
    )

    manifest: list[dict[str, Any]] = []
    preflights: list[dict[str, Any]] = []
    for task_id in TASK_IDS:
        task = tasks[task_id]
        source = revised8[task_id]
        pf = preflight8[task_id]
        charge = explicit_charge(task["target_formula"])
        scaffold = get_scaffold(source["scaffold_id"])
        fixed = [orbit["orbit_id"] for orbit in task_orbits(task, scaffold) if len(orbit["allowed_species"]) == 1]
        variable = [orbit["orbit_id"] for orbit in task_orbits(task, scaffold) if len(orbit["allowed_species"]) > 1]
        row = {
            "task_id": task_id,
            "request_hash": source["natural_language_request_sha256"],
            "structured_intent_hash": source["structured_intent_sha256"],
            "search_space_hash": source["search_space_sha256"],
            "scaffold_id": source["scaffold_id"],
            "scaffold_version": source["scaffold_version"],
            "scaffold_source_id": source["scaffold_source_id"],
            "scaffold_source_hash": source["scaffold_source_sha256"],
            "target_formula": task["target_formula"],
            "requested_space_group": task["allowed_space_groups"],
            "scaffold_space_group": pf["source_space_group"],
            "orbit_multiplicities": pf["orbit_multiplicities"],
            "fixed_orbits": ";".join(fixed),
            "variable_orbits": ";".join(variable),
            "oxidation_states": json.dumps(charge["preflight"]["oxidation_states_used"], sort_keys=True, separators=(",", ":")),
            "charge_policy": charge["preflight"]["charge_policy"],
            "charge_sum": charge["preflight"]["charge_sum"],
            "topology_validator": pf["topology_policy"],
            "retrieval_database": "nasicon_specialist_all_targets_out_v3",
            "exact_target_leakage_policy": "block exact reduced formula and exact StructureMatcher match",
            "spp_policy": task["spp_policy"],
            "expected_formula": task["target_formula"],
            "expected_topology_family": "NASICON/NZP",
            "engineering_smoke_status": "READY_FOR_ENGINEERING_SMOKE",
        }
        manifest.append(row)
        preflights.append({
            **row,
            "request_hash_verified": sha_text(task["natural_language_request"]) == row["request_hash"],
            "structured_intent_hash_verified": structured_hash(task) == row["structured_intent_hash"],
            "scaffold_hash_verified": sha_file(Path(scaffold.source_cif_path)) == row["scaffold_source_hash"],
            "integer_occupation_feasible": pf["integer_occupation_feasible"],
            "fractional_occupation_used": pf["fractional_occupation_used"],
            "space_group_match": pf["space_group_match"],
            "topology_validator_applicable": pf["topology_policy_available"],
            "exact_formula_leakage_count": pf["exact_target_leakage_count"],
            "charge_preflight_accepted": charge["preflight"]["accepted"],
            "preflight_status": "READY_FOR_ENGINEERING_SMOKE",
        })

    if len({row["search_space_hash"] for row in manifest}) != 6:
        raise AssertionError("Six engineering-smoke search spaces are not distinct")
    required_truths = (
        "request_hash_verified", "structured_intent_hash_verified", "scaffold_hash_verified",
        "integer_occupation_feasible", "space_group_match", "topology_validator_applicable", "charge_preflight_accepted",
    )
    if not all(all(str(row[key]).lower() == "true" for key in required_truths) and int(row["exact_formula_leakage_count"]) == 0 for row in preflights):
        raise AssertionError("Not all six rows are READY_FOR_ENGINEERING_SMOKE")
    write_csv(smoke / "SIX_TASK_ENGINEERING_SMOKE_MANIFEST.csv", manifest)
    write_csv(smoke / "SIX_TASK_ENGINEERING_SMOKE_PREFLIGHT.csv", preflights)
    checks = protected_hash_gate(skill, smoke, manifest, tasks)
    print(json.dumps({
        "engineering_smoke_rows": len(manifest),
        "ready": len(preflights),
        "hash_checks": len(checks),
        "hash_failures": 0,
        "generation_launched": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
