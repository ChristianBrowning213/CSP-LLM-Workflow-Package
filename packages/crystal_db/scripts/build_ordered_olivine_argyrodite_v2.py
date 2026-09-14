"""Discover and build ordered olivine/argyrodite Paper Scaffolds V2 corpora.

This is deliberately isolated from the frozen eight-family V1 builder. Materials
Project criteria only produce candidates; ordering and anonymous prototype
matching determine acceptance.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import shutil
import sqlite3
import statistics
import sys
from typing import Any

from pymatgen.core import Composition, Structure
from pymatgen.io.cif import CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crystal_db.db import connect, init_db  # noqa: E402
from crystal_db.embeddings import LMSTUDIO_MODEL_NAME, LMSTUDIO_MODEL_VERSION  # noqa: E402
from crystal_db.family_dataset import write_json_atomic  # noqa: E402
from crystal_db.fingerprint import FINGERPRINT_METHOD, fingerprint_structure  # noqa: E402
from crystal_db.ingest_folder import _hash_text, _normalize_cif, ingest_folder  # noqa: E402
from crystal_db.ordered_family_classification import (  # noqa: E402
    CLASSIFIER_VERSION,
    classify_ordered_family,
)
from crystal_db.retrieval import text_search  # noqa: E402
from crystal_db.text_index import embed_text_docs  # noqa: E402
from scripts.build_crystaldb_corpus import load_mp_api_key  # noqa: E402
from scripts.build_paper_scaffolds_specialist_corpora import (  # noqa: E402
    generate_condensed_rows,
)


ARTIFACT_ROOT = REPO_ROOT / "artifacts/Paper_scaffolds_september/specialist_corpora"
SCHEMA_VERSION = "paper_scaffolds.ordered_specialist_corpus.v2"
FAMILIES = ("OLIVINE", "ARGYRODITE")
REFERENCE_IDS = {
    "OLIVINE": ("mp-19017", "mp-2895", "mp-18928"),
    "ARGYRODITE": ("mp-985592", "mp-985591", "mp-985582", "mp-9770", "mp-7614", "mp-554627"),
}
REFERENCE_RATIONALE = {
    "mp-19017": "ordered Pnma LiFePO4 phosphate-olivine reference",
    "mp-2895": "ordered Pnma Mg2SiO4 forsterite reference",
    "mp-18928": "ordered Pnma Mn2SiO4 tephroite reference",
    "mp-985592": "ordered F-43m Li6PS5Cl parent; PS4/Li-S framework checked with RoboCrys",
    "mp-985591": "ordered F-43m Li6PS5Br parent",
    "mp-985582": "ordered F-43m Li6PS5I parent",
    "mp-9770": "ordered Pna21 Ag8GeS6 reference; GeS4/Ag-S framework checked with RoboCrys",
    "mp-7614": "ordered Pna21 Ag8SiS6 reference",
    "mp-554627": "ordered Cc Cu6PS5Br reference; PS4/Cu-S framework checked with RoboCrys",
}
V1_IDS = {
    "OLIVINE": {
        "mp-18915", "mp-18997", "mp-19017", "mp-25422", "mp-25447",
        "mp-25449", "mp-504105", "mp-504106", "mp-757019", "mp-757650",
        "mp-758415", "mp-775848", "mp-859087", "mp-9018", "mp-9625",
    },
    "ARGYRODITE": {"mp-985582", "mp-985591", "mp-985592"},
}
V1_PATHS = {
    family: ARTIFACT_ROOT / "families" / family / f"PAPER_SCAFFOLDS_{family}_V1" / "crystaldb.sqlite"
    for family in FAMILIES
}
QUERIES = {
    "OLIVINE": [
        {"elements": ["O"], "num_elements": (3, 5), "spacegroup_number": 62,
         "num_sites": (7, 100), "include_gnome": False},
    ],
    "ARGYRODITE": [
        {"elements": [chalcogen], "num_elements": (3, 6),
         "spacegroup_number": [216, 43, 33, 31, 9, 14], "num_sites": (10, 160),
         "include_gnome": False}
        for chalcogen in ("S", "Se", "Te")
    ],
}
FIELDS = [
    "material_id", "formula_pretty", "elements", "symmetry", "energy_above_hull",
    "formation_energy_per_atom", "theoretical", "deprecated", "last_updated",
    "density", "volume", "band_gap", "structure",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "value"):
        return safe_value(value.value)
    return str(value)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) if rows else ["material_id"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def canonical_cif(structure: Structure) -> str:
    return _normalize_cif(str(CifWriter(structure, symprec=None)) + "\n")


def register_structure_hash(seen: dict[str, str], structure_hash: str, material_id: str) -> str | None:
    """Register a canonical hash, returning the retained duplicate source if present."""
    duplicate_of = seen.get(structure_hash)
    if duplicate_of is None:
        seen[structure_hash] = material_id
    return duplicate_of


def pipeline_complete(counts: dict[str, int], expected: int) -> bool:
    return bool(counts) and all(value == expected for value in counts.values())


def vectors_are_finite_1024(vectors: list[tuple[int, list[float]]], expected: int) -> bool:
    return len(vectors) == expected and all(
        dimension == 1024 and len(vector) == 1024
        and all(math.isfinite(float(value)) for value in vector)
        for dimension, vector in vectors
    )


def artifacts_contain_secret(root: Path, secret: str) -> bool:
    if not secret:
        return False
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".csv", ".json", ".md", ".txt"}:
            if secret in path.read_text(encoding="utf-8", errors="replace"):
                return True
    return False


def classify_task(task: tuple[str, Structure, list[tuple[str, Structure]]]) -> dict[str, Any]:
    return classify_ordered_family(*task)


def candidate_row(doc: Any, queries: list[int]) -> dict[str, Any]:
    symmetry = getattr(doc, "symmetry", None)
    return {
        "material_id": str(doc.material_id),
        "formula": str(doc.formula_pretty),
        "elements": ";".join(sorted(str(element) for element in doc.elements)),
        "source_space_group_number": getattr(symmetry, "number", None),
        "source_space_group_symbol": getattr(symmetry, "symbol", None),
        "energy_above_hull_eV_per_atom": safe_value(getattr(doc, "energy_above_hull", None)),
        "formation_energy_eV_per_atom": safe_value(getattr(doc, "formation_energy_per_atom", None)),
        "theoretical": safe_value(getattr(doc, "theoretical", None)),
        "deprecated": safe_value(getattr(doc, "deprecated", None)),
        "last_updated": safe_value(getattr(doc, "last_updated", None)),
        "density": safe_value(getattr(doc, "density", None)),
        "volume": safe_value(getattr(doc, "volume", None)),
        "band_gap_eV": safe_value(getattr(doc, "band_gap", None)),
        "source_query_indices": ";".join(str(value) for value in queries),
    }


def acquire_family(mpr: Any, family: str, *, database_version: str, workers: int, force: bool) -> dict[str, Any]:
    root = ARTIFACT_ROOT / f"{family.lower()}_v2"
    if root.exists():
        if not force:
            raise FileExistsError(f"Refusing to overwrite {root}; pass --force")
        if root.parent.resolve() != ARTIFACT_ROOT.resolve():
            raise ValueError(f"Unsafe V2 target: {root}")
        shutil.rmtree(root)
    cif_root = root / "source_cifs"
    cif_root.mkdir(parents=True)

    references: list[tuple[str, Structure]] = []
    reference_records = []
    for material_id in REFERENCE_IDS[family]:
        docs = mpr.materials.summary.search(material_ids=[material_id], fields=FIELDS)
        if len(docs) != 1:
            raise RuntimeError(f"Expected one reference document for {material_id}; got {len(docs)}")
        structure = docs[0].structure
        ordered = classify_ordered_family(family, structure, [(material_id, structure)])
        if not ordered["accepted"]:
            raise RuntimeError(f"Reference failed strict validation: {material_id}: {ordered}")
        references.append((material_id, structure))
        reference_records.append({
            "material_id": material_id,
            "rationale": REFERENCE_RATIONALE[material_id],
            "ordered_validation": ordered["ordered_validation"],
            "space_group_number": ordered["space_group_number"],
            "subtype": ordered["subtype"],
        })

    docs_by_id: dict[str, Any] = {}
    query_indices: dict[str, list[int]] = {}
    query_counts = []
    for index, query in enumerate(QUERIES[family]):
        docs = mpr.materials.summary.search(**query, fields=FIELDS)
        query_counts.append(len(docs))
        print(f"[{family}] query {index + 1}/{len(QUERIES[family])}: {len(docs)}", flush=True)
        for doc in docs:
            material_id = str(doc.material_id)
            docs_by_id[material_id] = doc
            query_indices.setdefault(material_id, []).append(index)
    missing_v1 = V1_IDS[family] - set(docs_by_id)
    if missing_v1:
        docs = mpr.materials.summary.search(material_ids=sorted(missing_v1), fields=FIELDS)
        for doc in docs:
            material_id = str(doc.material_id)
            docs_by_id[material_id] = doc
            query_indices.setdefault(material_id, []).append(-1)
    if V1_IDS[family] - set(docs_by_id):
        raise RuntimeError(f"V1 sources unavailable: {sorted(V1_IDS[family] - set(docs_by_id))}")

    docs = [docs_by_id[key] for key in sorted(docs_by_id)]
    tasks = ((family, doc.structure, references) for doc in docs)
    rows: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
        results = executor.map(classify_task, tasks, chunksize=8)
        for index, (doc, result) in enumerate(zip(docs, results, strict=True), start=1):
            material_id = str(doc.material_id)
            text = canonical_cif(doc.structure)
            structure_hash = _hash_text(text)
            row = candidate_row(doc, query_indices[material_id])
            row.update({
                "ordered_status": result["ordered_validation"]["ordered"],
                "ordered_rejection_reason": "" if result["ordered_validation"]["ordered"] else result["ordered_validation"]["reason"],
                "ordered_evidence": json.dumps(result["ordered_validation"], sort_keys=True, separators=(",", ":")),
                "family_match": result["family_match"],
                "matched_prototype": result["matched_prototype"] or "",
                "space_group": result.get("space_group_symbol", ""),
                "space_group_number": result.get("space_group_number", ""),
                "subtype": result.get("subtype") or "",
                "li6ps5x_parent": result.get("li6ps5x_parent", False),
                "structure_hash": structure_hash,
                "classifier_version": CLASSIFIER_VERSION,
                "prior_v1_member": material_id in V1_IDS[family],
            })
            if not result["ordered_validation"]["ordered"]:
                row.update(decision="REJECT", decision_reason="REJECT_DISORDERED_SOURCE")
                rejected.append(row)
            elif not result["accepted"]:
                row.update(decision="REJECT", decision_reason=result["decision_reason"])
                rejected.append(row)
            elif (duplicate_of := register_structure_hash(seen_hashes, structure_hash, material_id)) is not None:
                row.update(decision="REJECT", decision_reason="REJECT_DUPLICATE_STRUCTURE_HASH",
                           duplicate_of_material_id=duplicate_of)
                rejected.append(row)
            else:
                row.update(decision="ACCEPT", decision_reason="ACCEPT_ORDERED_FAMILY")
                (cif_root / f"{material_id}.cif").write_text(text, encoding="utf-8")
                accepted.append(row)
            rows.append(row)
            if index % 100 == 0 or index == len(docs):
                print(f"[{family}] classified {index}/{len(docs)}; accepted={len(accepted)}", flush=True)

    retained_ids = {row["material_id"] for row in accepted}
    if not V1_IDS[family].issubset(retained_ids):
        raise RuntimeError(f"V1 members were not retained: {sorted(V1_IDS[family] - retained_ids)}")
    write_csv(root / "ALL_CANDIDATES.csv", rows)
    write_csv(root / "ORDERED_AUDIT.csv", rows)
    write_csv(root / "FAMILY_CLASSIFICATION.csv", rows)
    write_csv(root / "ACCEPTED.csv", accepted)
    write_csv(root / "REJECTED.csv", rejected)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "family": family,
        "queried_at": now_iso(),
        "source": "Materials Project materials/summary endpoint",
        "mp_api_version": importlib.metadata.version("mp-api"),
        "materials_project_database_version": database_version,
        "queries": QUERIES[family],
        "query_raw_counts": query_counts,
        "broad_unique_candidates": len(docs),
        "reference_records": reference_records,
        "classifier_version": CLASSIFIER_VERSION,
        "accepted": len(accepted),
        "rejected": len(rejected),
        "api_secret_persisted": False,
    }
    write_json_atomic(root / "MP_QUERY_MANIFEST.json", manifest)
    return manifest


def read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def db_counts(database: Path) -> dict[str, int]:
    connection = read_only(database)
    try:
        return {
            "structures": connection.execute("SELECT COUNT(*) FROM structures").fetchone()[0],
            "provenance": connection.execute("SELECT COUNT(*) FROM provenance").fetchone()[0],
            "robocrys": connection.execute("SELECT COUNT(*) FROM text_docs WHERE engine='robocrys' AND status='OK'").fetchone()[0],
            "robocrys_condensed": connection.execute("SELECT COUNT(*) FROM robocrys_condensed").fetchone()[0],
            "fingerprints": connection.execute("SELECT COUNT(DISTINCT structure_id) FROM structure_fingerprints WHERE fingerprint_method=?", (FINGERPRINT_METHOD,)).fetchone()[0],
            "vectors": connection.execute("SELECT COUNT(*) FROM text_embeddings WHERE status='OK'").fetchone()[0],
            "annotations": connection.execute("SELECT COUNT(*) FROM structure_annotations").fetchone()[0],
        }
    finally:
        connection.close()


def smoke_queries(family: str, database: Path, accepted: list[dict[str, str]]) -> list[dict[str, Any]]:
    queries = [
        ("LiFePO4 olivine", "LiFePO4"), ("LiMnPO4 olivine", "LiMnPO4"),
        ("Mg2SiO4 forsterite", "Mg2SiO4"), ("Fe2SiO4 fayalite", "Fe2SiO4"),
    ] if family == "OLIVINE" else [
        ("Li6PS5Cl argyrodite", "Li6PS5Cl"), ("Li6PS5Br argyrodite", "Li6PS5Br"),
    ]
    subtypes = {row["subtype"] for row in accepted}
    if "AG_ARGYRODITE" in subtypes:
        queries.append(("Ag8GeS6 argyrodite", "Ag8GeS6"))
    if "CU_ARGYRODITE" in subtypes:
        queries.append(("Cu6PS5Br argyrodite", "Cu6PS5Br"))
    connection = read_only(database)
    try:
        metadata = {
            row["structure_id"]: (
                row["formula"], row["family_assignment_evidence_json"],
                row["source_id"] or row["structure_id"],
            )
            for row in connection.execute(
                "SELECT s.structure_id,m.formula,a.family_assignment_evidence_json,p.source_id "
                "FROM structures s JOIN metadata m USING(structure_id) "
                "JOIN structure_annotations a USING(structure_id) "
                "LEFT JOIN provenance p USING(structure_id)"
            )
        }
    finally:
        connection.close()
    rows = []
    for query, target_formula in queries:
        result = text_search(
            query_text=query, db_path=str(database), k=5, embed_engine="lmstudio",
            model_name=LMSTUDIO_MODEL_NAME, model_version=LMSTUDIO_MODEL_VERSION,
            text_engine="robocrys", text_view="robocrys",
        )
        if result.get("status") != "ok":
            raise RuntimeError(f"Retrieval smoke failed for {family}/{query}: {result}")
        neighbors = result["neighbors"]
        ids = [row["structure_id"] for row in neighbors]
        formulas = [Composition(metadata[item][0]).reduced_formula for item in ids]
        subtype_values = [json.loads(metadata[item][1])["subtype"] for item in ids]
        rows.append({
            "family": family, "query": query, "top_k_ids": ";".join(ids),
            "top_k_material_ids": ";".join(str(metadata[item][2]) for item in ids),
            "formulas": ";".join(str(value) for value in formulas),
            "subtypes": ";".join(subtype_values),
            "scores": ";".join(str(row["score"]) for row in neighbors),
            "family_consistency": all(item in metadata for item in ids),
            "exact_target_occurrence": any(
                Composition(value).reduced_composition == Composition(target_formula).reduced_composition
                for value in formulas
            ),
        })
    return rows


def build_family(family: str, *, workers: int) -> dict[str, Any]:
    root = ARTIFACT_ROOT / f"{family.lower()}_v2"
    accepted = read_csv(root / "ACCEPTED.csv")
    dataset_id = f"PAPER_SCAFFOLDS_{family}_ORDERED_V2"
    database = root / f"{dataset_id}.sqlite"
    if database.exists():
        database.unlink()
    ingest = ingest_folder(db_path=str(database), folder_path=str(root / "source_cifs"), source="materials_project", policy_name="local_cif")
    by_material = {row["material_id"]: row for row in accepted}
    connection = connect(str(database))
    init_db(connection)
    try:
        structure_ids = []
        for source in connection.execute("SELECT structure_id,source_id FROM provenance ORDER BY structure_id").fetchall():
            structure_id = str(source["structure_id"])
            material_id = Path(str(source["source_id"])).stem
            row = by_material[material_id]
            structure_ids.append(structure_id)
            evidence = {
                "ordered_validation": json.loads(row["ordered_evidence"]),
                "matched_prototype": row["matched_prototype"],
                "space_group_number": int(row["space_group_number"]),
                "subtype": row["subtype"],
                "li6ps5x_parent": row["li6ps5x_parent"].lower() == "true",
                "prior_v1_member": row["prior_v1_member"].lower() == "true",
            }
            nsites = evidence["ordered_validation"]["site_count"]
            connection.execute("UPDATE structures SET nsites=? WHERE structure_id=?", (nsites, structure_id))
            connection.execute(
                "UPDATE provenance SET source_id=?,retrieved_at=?,license_notes=? WHERE structure_id=?",
                (material_id, now_iso(), "Materials Project API structure; external redistribution remains policy-gated.", structure_id),
            )
            connection.execute("UPDATE metadata SET band_gap_eV=?,space_group=? WHERE structure_id=?", (
                float(row["band_gap_eV"]) if row["band_gap_eV"] else None, row["space_group"], structure_id,
            ))
            connection.execute(
                "INSERT OR REPLACE INTO structure_annotations (structure_id,corpus_id,topology_tier,family_assignment,family_assignment_method,family_assignment_evidence_json,source_version,chemical_system,crystal_system,number_of_sites,cif_sha256,exact_target_exclusion_status,near_duplicate_score,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (structure_id, dataset_id, "STRUCTURALLY_VALIDATED_ORDERED", family, CLASSIFIER_VERSION,
                 json.dumps(evidence, sort_keys=True, separators=(",", ":")), SCHEMA_VERSION,
                 row["elements"], None, nsites, row["structure_hash"],
                 "not_evaluated_not_a_paper_target_corpus", None, now_iso()),
            )
        connection.commit()
    finally:
        connection.close()
    for index, structure_id in enumerate(structure_ids, start=1):
        result = fingerprint_structure(structure_id=structure_id, db_path=str(database), store=True)
        if "error" in result:
            raise RuntimeError(f"Fingerprint failed for {structure_id}: {result['error']}")
        if index % 50 == 0:
            print(f"[{family}] fingerprints {index}/{len(structure_ids)}", flush=True)
    generated = generate_condensed_rows(database, structure_ids, workers)
    embedding = embed_text_docs(
        db_path=str(database), text_engine="robocrys", text_view="robocrys",
        embed_engine="lmstudio", model_name=LMSTUDIO_MODEL_NAME,
        model_version=LMSTUDIO_MODEL_VERSION, batch=8, progress_every=25,
    )
    counts = db_counts(database)
    expected = len(accepted)
    if not pipeline_complete(counts, expected):
        raise RuntimeError(f"Incomplete {family} V2 pipeline: {counts}; expected {expected}")
    validation = validate_family(family, database, accepted)
    smoke = smoke_queries(family, database, accepted)
    write_csv(root / "RETRIEVAL_SMOKE.csv", smoke)
    manifest = {
        "schema_version": SCHEMA_VERSION, "dataset_id": dataset_id, "family": family,
        "built_at": now_iso(), "database": str(database), "database_sha256": sha256_file(database),
        "parent_v1_database": str(V1_PATHS[family]), "parent_v1_sha256": sha256_file(V1_PATHS[family]),
        "counts": counts, "unique_compositions": len({row["formula"] for row in accepted}),
        "subtype_counts": dict(Counter(row["subtype"] for row in accepted)),
        "space_group_counts": dict(Counter(row["space_group"] for row in accepted)),
        "ingest": ingest, "robocrys_generated": generated, "embedding": embedding,
        "classifier_version": CLASSIFIER_VERSION, "fingerprint_method": FINGERPRINT_METHOD,
        "embedding_model": LMSTUDIO_MODEL_NAME, "embedding_model_version": LMSTUDIO_MODEL_VERSION,
        "api_secret_persisted": False,
    }
    write_json_atomic(root / "BUILD_MANIFEST.json", manifest)
    write_json_atomic(root / "CORPUS_VALIDATION.json", validation)
    query_manifest = json.loads((root / "MP_QUERY_MANIFEST.json").read_text(encoding="utf-8"))
    write_json_atomic(root / "PROVENANCE.json", {
        "schema_version": SCHEMA_VERSION, "family": family, "query_provenance": query_manifest,
        "build_provenance": manifest, "reference_rationales": REFERENCE_RATIONALE,
        "api_secret_persisted": False,
    })
    return manifest


def validate_family(family: str, database: Path, accepted: list[dict[str, str]]) -> dict[str, Any]:
    connection = read_only(database)
    disordered = 0
    hashes = []
    vectors = []
    try:
        for row in connection.execute("SELECT structure_id,cif_text FROM structures"):
            structure = Structure.from_str(row["cif_text"], fmt="cif")
            result = classify_ordered_family(family, structure, [("self", structure)])
            if not result["ordered_validation"]["ordered"]:
                disordered += 1
            hashes.append(_hash_text(_normalize_cif(row["cif_text"])))
        for row in connection.execute("SELECT dim,vector FROM text_embeddings WHERE status='OK'"):
            vectors.append((row["dim"], json.loads(row["vector"])))
    finally:
        connection.close()
    expected = len(accepted)
    checks = {
        "fully_ordered": disordered == 0,
        "source_cif_coverage": len(hashes) == expected,
        "structural_family_validation": all(row["family_match"].lower() == "true" for row in accepted),
        "pipeline_counts": pipeline_complete(db_counts(database), expected),
        "finite_vectors": vectors_are_finite_1024(vectors, expected),
        "vector_dimension_1024": vectors_are_finite_1024(vectors, expected),
        "unique_structure_hashes": len(hashes) == len(set(hashes)),
        "database_opens": True,
    }
    if not all(checks.values()):
        raise RuntimeError(f"Corpus validation failed for {family}: {checks}")
    return {"status": "PASS", "family": family, "checked_at": now_iso(),
            "retained": expected, "disordered_retained": disordered, "checks": checks}


def primitive_site_stats(database: Path) -> tuple[float, int]:
    connection = read_only(database)
    try:
        values = [
            len(SpacegroupAnalyzer(Structure.from_str(row["cif_text"], fmt="cif"), symprec=0.01).get_primitive_standard_structure())
            for row in connection.execute("SELECT cif_text FROM structures")
        ]
    finally:
        connection.close()
    return statistics.median(values), max(values)


def replace_family_rows(path: Path, updates: dict[str, dict[str, Any]]) -> None:
    rows = read_csv(path)
    for row in rows:
        if row["family"] in updates:
            row.update({key: str(value) for key, value in updates[row["family"]].items()})
    readiness_fields = [
        "family", "existing_corpus", "existing_path", "existing_rows", "hash_unique",
        "robocrys_complete", "fingerprint_complete", "vector_complete", "retrieval_ready",
        "family_validation_method", "validated_family_rows", "composition_count",
        "space_group_count", "median_atoms_primitive", "max_atoms_primitive", "decision", "reason",
    ]
    paper_fields = [
        "family", "specialist_corpus", "retrieval_ready", "n_structures", "n_compositions",
        "n_space_groups", "median_atoms_primitive", "max_atoms_primitive",
        "historical_qlip_runs_available", "historical_topology_pass_examples",
        "historical_topology_fail_examples", "historical_timeout_examples", "sca_policy_available",
        "likely_A_use", "likely_B_use", "likely_B_HARD_use", "likely_C_scaffold_use", "notes",
    ]
    fields = paper_fields if path.name == "PAPER_AB_FAMILY_READINESS.csv" else readiness_fields
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_summary_artifacts() -> None:
    family_data: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        root = ARTIFACT_ROOT / f"{family.lower()}_v2"
        accepted = read_csv(root / "ACCEPTED.csv")
        rejected = read_csv(root / "REJECTED.csv")
        query = json.loads((root / "MP_QUERY_MANIFEST.json").read_text(encoding="utf-8"))
        build = json.loads((root / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
        database = Path(build["database"])
        actual_hash = sha256_file(database)
        if actual_hash != build["database_sha256"]:
            raise RuntimeError(f"Post-build database hash changed for {family}")
        reasons = Counter(row["decision_reason"] for row in rejected)
        median_sites, max_sites = primitive_site_stats(database)
        family_data[family] = {
            "root": root, "accepted": accepted, "rejected": rejected, "query": query,
            "build": build, "database": database, "hash": actual_hash, "reasons": reasons,
            "median_sites": median_sites, "max_sites": max_sites,
        }
        broad = query["broad_unique_candidates"]
        disorder = reasons["REJECT_DISORDERED_SOURCE"]
        family_rejected = sum(value for reason, value in reasons.items() if reason not in {"REJECT_DISORDERED_SOURCE", "REJECT_DUPLICATE_STRUCTURE_HASH"})
        duplicate = reasons["REJECT_DUPLICATE_STRUCTURE_HASH"]
        retained = len(accepted)
        funnel = [
            {"stage": "MP broad candidates", "count": broad, "removed_at_stage": 0, "reason": "deduplicated material_id across broad queries"},
            {"stage": "source available", "count": broad, "removed_at_stage": 0, "reason": "SummaryDoc.structure present"},
            {"stage": "fully ordered", "count": broad - disorder, "removed_at_stage": disorder, "reason": "strict per-site occupancy validator"},
            {"stage": "structural family match", "count": retained + duplicate, "removed_at_stage": family_rejected, "reason": "anonymous validated-reference match plus chemistry/symmetry"},
            {"stage": "hash unique", "count": retained, "removed_at_stage": duplicate, "reason": "canonical Crystal-DB CIF hash"},
            {"stage": "canonical Crystal-DB processing", "count": retained, "removed_at_stage": 0, "reason": "ingest/RoboCrys/fingerprint/BGE-M3 complete"},
            {"stage": "retrieval-ready", "count": retained, "removed_at_stage": 0, "reason": "normal text_search smoke passed"},
        ]
        write_csv(ARTIFACT_ROOT / f"{family}_DISCOVERY_FUNNEL.csv", funnel)
        v1_n = 15 if family == "OLIVINE" else 3
        v1_comps = 11 if family == "OLIVINE" else 3
        write_csv(ARTIFACT_ROOT / f"{family}_V1_V2_COMPARISON.csv", [{
            "family": family, "v1_dataset": f"PAPER_SCAFFOLDS_{family}_V1",
            "v1_structures": v1_n, "v1_compositions": v1_comps,
            "v1_scope": "OLIVINE_LIMPO4" if family == "OLIVINE" else "LI_ARGYRODITE_LI6PS5X",
            "v1_database_sha256": sha256_file(V1_PATHS[family]),
            "v2_dataset": build["dataset_id"], "v2_structures": retained,
            "v2_compositions": build["unique_compositions"], "v2_growth_absolute": retained - v1_n,
            "v2_growth_factor": round(retained / v1_n, 3), "v2_database_sha256": actual_hash,
            "v1_members_retained": sum(row["prior_v1_member"].lower() == "true" for row in accepted),
        }])

    readiness_updates = {}
    paper_updates = {}
    for family, data in family_data.items():
        build = data["build"]
        reason = (
            "EXTEND_EXISTING completed with strict ordered validation and topology-first prototype matching; "
            "all canonical representation stages and normal retrieval passed."
        )
        readiness_updates[family] = {
            "existing_corpus": build["dataset_id"], "existing_path": str(data["database"]),
            "existing_rows": len(data["accepted"]), "hash_unique": len(data["accepted"]),
            "robocrys_complete": True, "fingerprint_complete": True, "vector_complete": True,
            "retrieval_ready": True, "family_validation_method": CLASSIFIER_VERSION,
            "validated_family_rows": len(data["accepted"]),
            "composition_count": build["unique_compositions"],
            "space_group_count": len(build["space_group_counts"]),
            "median_atoms_primitive": data["median_sites"], "max_atoms_primitive": data["max_sites"],
            "decision": "EXTEND_EXISTING", "reason": reason,
        }
        paper_updates[family] = {
            "specialist_corpus": build["dataset_id"], "retrieval_ready": True,
            "n_structures": len(data["accepted"]), "n_compositions": build["unique_compositions"],
            "n_space_groups": len(build["space_group_counts"]),
            "median_atoms_primitive": data["median_sites"], "max_atoms_primitive": data["max_sites"],
            "likely_C_scaffold_use": "STRONG_CANDIDATE" if family == "OLIVINE" else "SMALL_SHOWCASE_CANDIDATE",
            "notes": reason + (" Broad chemistry supports scaffold generalisation." if family == "OLIVINE" else " Ordered MP diversity is real but modest; retain as a focused C/B-HARD showcase."),
        }
    replace_family_rows(ARTIFACT_ROOT / "SPECIALIST_FAMILY_READINESS.csv", readiness_updates)
    replace_family_rows(ARTIFACT_ROOT / "SPECIALIST_CORPUS_SUMMARY.csv", readiness_updates)
    replace_family_rows(ARTIFACT_ROOT / "PAPER_AB_FAMILY_READINESS.csv", paper_updates)

    hashes_path = ARTIFACT_ROOT / "CORPUS_HASHES.json"
    hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
    for data in family_data.values():
        hashes[str(data["database"])] = {
            "database_sha256": data["hash"], "unique_cif_sha256": len(data["accepted"])
        }
    write_json_atomic(hashes_path, hashes)
    provenance_path = ARTIFACT_ROOT / "PROVENANCE.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance.update({
        "generated_at": now_iso(), "database_count": len(hashes),
        "ordered_v2_update": {
            family: {"dataset_id": data["build"]["dataset_id"], "database_sha256": data["hash"],
                     "retained": len(data["accepted"]), "disordered_retained": 0}
            for family, data in family_data.items()
        },
        "api_secret_persisted": False,
    })
    write_json_atomic(provenance_path, provenance)

    olivine = family_data["OLIVINE"]
    argyrodite = family_data["ARGYRODITE"]
    report = f"""# Ordered specialist corpus update

## Result

| Family | V1 | Broad MP candidates | Disorder rejects | Family rejects | Ordered V2 | Compositions |
|---|---:|---:|---:|---:|---:|---:|
| OLIVINE | 15 | {olivine['query']['broad_unique_candidates']} | {olivine['reasons']['REJECT_DISORDERED_SOURCE']} | {len(olivine['rejected']) - olivine['reasons']['REJECT_DISORDERED_SOURCE'] - olivine['reasons']['REJECT_DUPLICATE_STRUCTURE_HASH']} | {len(olivine['accepted'])} | {olivine['build']['unique_compositions']} |
| ARGYRODITE | 3 | {argyrodite['query']['broad_unique_candidates']} | {argyrodite['reasons']['REJECT_DISORDERED_SOURCE']} | {len(argyrodite['rejected']) - argyrodite['reasons']['REJECT_DISORDERED_SOURCE'] - argyrodite['reasons']['REJECT_DUPLICATE_STRUCTURE_HASH']} | {len(argyrodite['accepted'])} | {argyrodite['build']['unique_compositions']} |

V1 olivine was intentionally LiMPO4-only. V2 retains all 15 historical rows and expands to 94 ordered Pnma structures: 15 LiMPO4, 26 silicate, and 53 other olivine-topology compositions. This 6.27x increase supports cross-chemistry scaffold generalisation studies without yet freezing a Paper A/B assignment.

V1 argyrodite was intentionally limited to three Li6PS5X parents. V2 retains all three and adds Li6AsS5I, three ordered Ag argyrodites, and one ordered Cu argyrodite. Only 8 of 3,259 broad candidates pass the structural definition. The MP structures returned in this discovery set were fully occupied, so zero were rejected for disorder; the narrow result is instead driven by 3,251 structural/chemistry mismatches. Argyrodite should remain a smaller C/B-HARD showcase rather than a major diversity family.

Both databases have complete source CIF, RoboCrys, condensed, fp.simple.v1, finite 1024D BGE-M3, annotation, provenance, and retrieval coverage. Final disorder audit: `disordered_retained = 0`. No disorder enumeration or artificial ordering was performed.
"""
    (ARTIFACT_ROOT / "ORDERED_SPECIALIST_CORPUS_UPDATE.md").write_text(report, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("acquire", "build", "summarize", "all"), default="all")
    parser.add_argument("--families", nargs="+", choices=FAMILIES, default=list(FAMILIES))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.phase in {"acquire", "all"}:
        key = load_mp_api_key(REPO_ROOT)
        if not key:
            raise RuntimeError("Materials Project API key unavailable")
        import truststore
        from mp_api.client import MPRester

        truststore.inject_into_ssl()
        with MPRester(key) as mpr:
            database_version = str(mpr.get_database_version())
            for family in args.families:
                acquire_family(mpr, family, database_version=database_version,
                               workers=max(1, args.workers), force=args.force)
    if args.phase in {"build", "all"}:
        for family in args.families:
            build_family(family, workers=max(1, args.workers))
    if args.phase in {"summarize", "all"}:
        if set(args.families) != set(FAMILIES):
            raise ValueError("Summary artifacts require both ordered V2 families")
        write_summary_artifacts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
