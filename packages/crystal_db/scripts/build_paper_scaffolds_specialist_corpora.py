"""Freeze accepted-only specialist corpora for Paper_scaffolds_september.

The builder deliberately reuses already acquired and validated records.  It
never queries Materials Project.  Existing databases are opened read-only and
the output is a new Crystal-DB database under the paper artifact root.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crystal_db.db import connect, init_db  # noqa: E402
from crystal_db.embeddings import LMSTUDIO_MODEL_NAME, LMSTUDIO_MODEL_VERSION  # noqa: E402
from crystal_db.family_dataset import write_json_atomic  # noqa: E402
from crystal_db.fingerprint import fingerprint_structure  # noqa: E402
from crystal_db.ingest_folder import ingest_folder  # noqa: E402
from crystal_db.textgen import generate_robocrys  # noqa: E402
from crystal_db.text_index import embed_text_docs  # noqa: E402
from scripts.build_crystaldb_corpus import copy_structure_rows  # noqa: E402


SCHEMA_VERSION = "paper_scaffolds_specialist_corpus.v1"
OUTPUT_ROOT = REPO_ROOT / "artifacts/Paper_scaffolds_september/specialist_corpora/families"
SKILL_LOOP_ROOT = REPO_ROOT.parent / "Skill-Loop-CSP"
TARGET_BUILD_FAMILIES = (
    "LAYERED_OXIDE",
    "SPINEL",
    "NASICON",
    "ROCKSALT",
    "OLIVINE",
    "ARGYRODITE",
    "GARNET",
    "RUDDLESDEN_POPPER",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def copy_condensed(source: sqlite3.Connection, destination: sqlite3.Connection, structure_id: str) -> None:
    exists = source.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='robocrys_condensed'"
    ).fetchone()
    if not exists:
        return
    row = source.execute(
        "SELECT structure_id,engine_version,condensed_json,condensed_sha256,description_sha256,generated_at "
        "FROM robocrys_condensed WHERE structure_id=?",
        (structure_id,),
    ).fetchone()
    if row:
        destination.execute(
            "INSERT OR REPLACE INTO robocrys_condensed "
            "(structure_id,engine_version,condensed_json,condensed_sha256,description_sha256,generated_at) "
            "VALUES (?,?,?,?,?,?)",
            tuple(row),
        )


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) if rows else ["structure_id"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def condense_cif(task: tuple[str, str]) -> tuple[str, dict[str, Any]]:
    structure_id, cif_text = task
    return structure_id, generate_robocrys(cif_text=cif_text, store=False)


def generate_condensed_rows(database: Path, structure_ids: list[str], workers: int) -> int:
    source = read_only(database)
    try:
        tasks = [
            (structure_id, str(source.execute(
                "SELECT cif_text FROM structures WHERE structure_id=?", (structure_id,)
            ).fetchone()[0]))
            for structure_id in structure_ids
        ]
    finally:
        source.close()
    destination = connect(str(database))
    init_db(destination)
    completed = 0
    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            for structure_id, result in executor.map(condense_cif, tasks, chunksize=1):
                if "error" in result:
                    raise RuntimeError(f"RoboCrys failed for {structure_id}: {result['error']}")
                generated_at = now_iso()
                condensed_json = json.dumps(
                    result["condensed"], sort_keys=True, separators=(",", ":")
                )
                destination.execute(
                    "INSERT INTO text_docs "
                    "(structure_id,engine,text_view,engine_version,text,text_sha256,status,created_at,updated_at) "
                    "VALUES (?,'robocrys','robocrys',?,?,?,'OK',?,?) "
                    "ON CONFLICT(structure_id,engine,text_view) DO UPDATE SET "
                    "engine_version=excluded.engine_version,text=excluded.text,text_sha256=excluded.text_sha256,"
                    "status='OK',error_type=NULL,error_message=NULL,updated_at=excluded.updated_at",
                    (
                        structure_id,
                        result["version"],
                        result["text"],
                        result["description_sha256"],
                        generated_at,
                        generated_at,
                    ),
                )
                destination.execute(
                    "INSERT OR REPLACE INTO robocrys_condensed VALUES (?,?,?,?,?,?)",
                    (
                        structure_id,
                        result["version"],
                        condensed_json,
                        result["condensed_sha256"],
                        result["description_sha256"],
                        generated_at,
                    ),
                )
                destination.commit()
                completed += 1
                if completed % 10 == 0:
                    print(f"[robocrys] {completed}/{len(tasks)}", flush=True)
    finally:
        destination.close()
    return completed


def freeze_selected(
    *,
    family: str,
    source_db: Path,
    selected: list[dict[str, Any]],
    classifier_version: str,
    force: bool,
    generate_missing_condensed: bool = False,
    workers: int = 4,
) -> dict[str, Any]:
    family_root = OUTPUT_ROOT / family
    dataset_id = f"PAPER_SCAFFOLDS_{family}_V1"
    dataset_root = family_root / dataset_id
    database = dataset_root / "crystaldb.sqlite"
    if dataset_root.exists():
        if not force:
            raise FileExistsError(f"Refusing to overwrite {dataset_root}; pass --force")
        if dataset_root.resolve().parent != family_root.resolve():
            raise ValueError(f"Unsafe rebuild target: {dataset_root}")
        shutil.rmtree(dataset_root)
    cif_root = dataset_root / "cifs"
    cif_root.mkdir(parents=True)

    source = read_only(source_db)
    destination = connect(str(database))
    init_db(destination)
    accepted: list[dict[str, Any]] = []
    try:
        for item in selected:
            structure_id = str(item["structure_id"])
            copy_structure_rows(source, destination, structure_id, structure_id)
            copy_condensed(source, destination, structure_id)
            row = destination.execute(
                "SELECT cif_text,reduced_formula,nsites FROM structures WHERE structure_id=?",
                (structure_id,),
            ).fetchone()
            if row is None or not row["cif_text"]:
                raise RuntimeError(f"Selected structure lacks source CIF: {structure_id}")
            cif_path = cif_root / f"{structure_id}.cif"
            cif_path.write_text(str(row["cif_text"]), encoding="utf-8")
            cif_hash = hashlib.sha256(str(row["cif_text"]).encode("utf-8")).hexdigest()
            evidence = item.get("evidence", {})
            destination.execute(
                "INSERT OR REPLACE INTO structure_annotations "
                "(structure_id,corpus_id,topology_tier,family_assignment,family_assignment_method,"
                "family_assignment_evidence_json,source_version,chemical_system,crystal_system,number_of_sites,"
                "cif_sha256,exact_target_exclusion_status,near_duplicate_score,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    structure_id,
                    dataset_id,
                    item.get("topology_tier", "STRUCTURALLY_VALIDATED"),
                    family,
                    classifier_version,
                    json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                    SCHEMA_VERSION,
                    None,
                    None,
                    row["nsites"],
                    cif_hash,
                    "not_evaluated_not_a_paper_target_corpus",
                    None,
                    now_iso(),
                ),
            )
            accepted.append(
                {
                    "structure_id": structure_id,
                    "reduced_formula": row["reduced_formula"],
                    "number_of_sites": row["nsites"],
                    "cif_sha256": cif_hash,
                    "topology_tier": item.get("topology_tier", "STRUCTURALLY_VALIDATED"),
                    "family_assignment_method": classifier_version,
                    "source_database": str(source_db),
                }
            )
        destination.commit()
    finally:
        source.close()
        destination.close()

    regenerated = 0
    if generate_missing_condensed:
        regenerated = generate_condensed_rows(
            database, [str(item["structure_id"]) for item in accepted], workers
        )

    connection = read_only(database)
    try:
        counts = {
            "structures": connection.execute("SELECT COUNT(*) FROM structures").fetchone()[0],
            "provenance": connection.execute("SELECT COUNT(*) FROM provenance").fetchone()[0],
            "robocrys": connection.execute(
                "SELECT COUNT(*) FROM text_docs WHERE engine='robocrys' AND text_view='robocrys' AND status='OK'"
            ).fetchone()[0],
            "robocrys_condensed": connection.execute(
                "SELECT COUNT(*) FROM robocrys_condensed"
            ).fetchone()[0],
            "fingerprints": connection.execute(
                "SELECT COUNT(DISTINCT structure_id) FROM structure_fingerprints"
            ).fetchone()[0],
            "vectors": connection.execute(
                "SELECT COUNT(*) FROM text_embeddings WHERE status='OK'"
            ).fetchone()[0],
            "annotations": connection.execute(
                "SELECT COUNT(*) FROM structure_annotations"
            ).fetchone()[0],
        }
    finally:
        connection.close()
    expected = len(accepted)
    incomplete = {key: value for key, value in counts.items() if value < expected}
    if incomplete:
        raise RuntimeError(f"Incomplete frozen corpus {family}: {incomplete}; expected {expected}")

    write_rows(dataset_root / "accepted.csv", accepted)
    write_rows(dataset_root / "rejected.csv", [])
    build_manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "family": family,
        "built_at": now_iso(),
        "source_database": str(source_db),
        "source_database_sha256": sha256_file(source_db),
        "classifier_version": classifier_version,
        "selected_structure_ids": [row["structure_id"] for row in accepted],
        "counts": counts,
        "regenerated_robocrys_condensed": regenerated,
        "database": str(database),
        "database_sha256": sha256_file(database),
        "api_secret_persisted": False,
    }
    write_json_atomic(dataset_root / "build_manifest.json", build_manifest)
    write_json_atomic(dataset_root / "validation.json", {"status": "PASS", **build_manifest})
    return build_manifest


def oxide_selection(family: str) -> tuple[Path, list[dict[str, Any]], str]:
    source_root = REPO_ROOT / "artifacts/mp_oxide_families_v1"
    names = {
        "LAYERED_OXIDE": "MP_LAYERED_BATTERY_OXIDES_V1",
        "SPINEL": "MP_SPINEL_OXIDES_V1",
    }
    name = names[family]
    root = source_root / name
    manifest = json.loads((root / "dataset_manifest.json").read_text(encoding="utf-8"))
    selected = [{"structure_id": value} for value in manifest["accepted_structure_ids"]]
    return root / f"{name}.db", selected, str(manifest["classifier_version"])


def nasicon_selection() -> tuple[Path, list[dict[str, Any]], str]:
    root = SKILL_LOOP_ROOT / "data/corpora/nasicon_specialist_v3"
    source_db = root / "crystaldb.sqlite"
    source = read_only(source_db)
    mapping = {
        str(row["source_id"]).removesuffix(".cif"): str(row["structure_id"])
        for row in source.execute("SELECT structure_id,source_id FROM provenance")
    }
    source.close()
    selected = []
    for line in (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("topology_tier") != "TIER_1_TOPOLOGY_PROXY":
            continue
        internal_id = str(record["internal_id"])
        selected.append(
            {
                "structure_id": mapping[internal_id],
                "topology_tier": record["topology_tier"],
                "evidence": record.get("family_assignment_evidence", {}),
            }
        )
    return source_db, selected, "nasicon_v3.ordered_coordination_single_component_rank3_proxy"


def build_acquired_family(family: str, *, force: bool, workers: int) -> dict[str, Any]:
    family_root = OUTPUT_ROOT / family
    dataset_id = f"PAPER_SCAFFOLDS_{family}_V1"
    dataset_root = family_root / dataset_id
    acquisition_root = dataset_root / "acquisition"
    accepted_path = acquisition_root / "accepted.csv"
    cif_root = acquisition_root / "accepted_cifs"
    if not accepted_path.is_file() or not cif_root.is_dir():
        raise FileNotFoundError(f"Missing completed acquisition for {family}: {acquisition_root}")
    database = dataset_root / "crystaldb.sqlite"
    if database.exists():
        if not force:
            raise FileExistsError(f"Refusing to overwrite {database}; pass --force")
        database.unlink()
    with accepted_path.open(encoding="utf-8", newline="") as handle:
        accepted = list(csv.DictReader(handle))
    by_material = {str(row["material_id"]): row for row in accepted}
    ingest_folder(
        db_path=str(database),
        folder_path=str(cif_root),
        source="materials_project",
        policy_name="local_cif",
    )
    connection = connect(str(database))
    init_db(connection)
    try:
        structure_rows = connection.execute(
            "SELECT structure_id,source_id FROM provenance ORDER BY structure_id"
        ).fetchall()
        structure_ids = []
        for source_row in structure_rows:
            structure_id = str(source_row["structure_id"])
            material_id = Path(str(source_row["source_id"])).stem
            record = by_material[material_id]
            structure_ids.append(structure_id)
            connection.execute(
                "UPDATE provenance SET source_id=?,retrieved_at=?,license_notes=? WHERE structure_id=?",
                (
                    material_id,
                    now_iso(),
                    "Materials Project API structure; external redistribution remains policy-gated.",
                    structure_id,
                ),
            )
            connection.execute(
                "UPDATE metadata SET band_gap_eV=? WHERE structure_id=?",
                (float(record["band_gap_eV"]) if record.get("band_gap_eV") else None, structure_id),
            )
            connection.execute(
                "INSERT OR REPLACE INTO structure_annotations "
                "(structure_id,corpus_id,topology_tier,family_assignment,family_assignment_method,"
                "family_assignment_evidence_json,source_version,chemical_system,crystal_system,number_of_sites,"
                "cif_sha256,exact_target_exclusion_status,near_duplicate_score,created_at) "
                "SELECT ?,?,?,?,?,?,?,?,?,nsites,?,?,?,? FROM structures WHERE structure_id=?",
                (
                    structure_id,
                    dataset_id,
                    "STRUCTURALLY_VALIDATED",
                    family,
                    record["classifier_version"],
                    record["classifier_evidence"],
                    SCHEMA_VERSION,
                    record.get("elements", ""),
                    None,
                    record["cif_sha256"],
                    "not_evaluated_not_a_paper_target_corpus",
                    None,
                    now_iso(),
                    structure_id,
                ),
            )
        connection.commit()
    finally:
        connection.close()
    for structure_id in structure_ids:
        result = fingerprint_structure(structure_id=structure_id, db_path=str(database), store=True)
        if "error" in result:
            raise RuntimeError(f"Fingerprint failed for {structure_id}: {result['error']}")
    generated = generate_condensed_rows(database, structure_ids, workers)
    embedding = embed_text_docs(
        db_path=str(database),
        text_engine="robocrys",
        text_view="robocrys",
        embed_engine="lmstudio",
        model_name=LMSTUDIO_MODEL_NAME,
        model_version=LMSTUDIO_MODEL_VERSION,
        batch=8,
        progress_every=25,
    )
    connection = read_only(database)
    try:
        counts = {
            "structures": connection.execute("SELECT COUNT(*) FROM structures").fetchone()[0],
            "provenance": connection.execute("SELECT COUNT(*) FROM provenance").fetchone()[0],
            "robocrys": connection.execute("SELECT COUNT(*) FROM text_docs WHERE engine='robocrys' AND status='OK'").fetchone()[0],
            "robocrys_condensed": connection.execute("SELECT COUNT(*) FROM robocrys_condensed").fetchone()[0],
            "fingerprints": connection.execute("SELECT COUNT(*) FROM structure_fingerprints").fetchone()[0],
            "vectors": connection.execute("SELECT COUNT(*) FROM text_embeddings WHERE status='OK'").fetchone()[0],
            "annotations": connection.execute("SELECT COUNT(*) FROM structure_annotations").fetchone()[0],
        }
    finally:
        connection.close()
    if any(value < len(accepted) for value in counts.values()):
        raise RuntimeError(f"Incomplete acquired corpus {family}: {counts}; expected {len(accepted)}")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "family": family,
        "built_at": now_iso(),
        "source": "Materials Project acquisition manifest",
        "classifier_version": accepted[0]["classifier_version"] if accepted else None,
        "counts": counts,
        "regenerated_robocrys_condensed": generated,
        "embedding": embedding,
        "database": str(database),
        "database_sha256": sha256_file(database),
        "api_secret_persisted": False,
    }
    write_json_atomic(dataset_root / "build_manifest.json", manifest)
    write_json_atomic(dataset_root / "validation.json", {"status": "PASS", **manifest})
    return manifest


def refresh_build_manifests(families: list[str]) -> dict[str, int]:
    refreshed: dict[str, int] = {}
    for family in families:
        dataset_root = OUTPUT_ROOT / family / f"PAPER_SCAFFOLDS_{family}_V1"
        database = dataset_root / "crystaldb.sqlite"
        manifest_path = dataset_root / "build_manifest.json"
        if not database.is_file() or not manifest_path.is_file():
            raise FileNotFoundError(f"Missing built corpus for manifest refresh: {dataset_root}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        accepted_path = dataset_root / "accepted.csv"
        if not accepted_path.is_file():
            accepted_path = dataset_root / "acquisition/accepted.csv"
        with accepted_path.open(encoding="utf-8", newline="") as handle:
            accepted = list(csv.DictReader(handle))
        original_hashes = {
            str(row.get("material_id") or row.get("structure_id")): str(row["cif_sha256"])
            for row in accepted
        }
        connection = read_only(database)
        try:
            retained_hashes = {
                str(row["structure_id"]): hashlib.sha256(str(row["cif_text"]).encode("utf-8")).hexdigest()
                for row in connection.execute("SELECT structure_id,cif_text FROM structures ORDER BY structure_id")
            }
            dimensions = sorted(
                {int(row[0]) for row in connection.execute("SELECT DISTINCT dim FROM text_embeddings WHERE status='OK'")}
            )
        finally:
            connection.close()
        manifest.update(
            {
                "original_structure_hashes": original_hashes,
                "retained_structure_hashes": retained_hashes,
                "robocrys": {"engine": "robocrys", "engine_version": "robocrys.v1", "structured_condensed_required": True},
                "fingerprint": {"method": "fp.simple.v1", "version": "v1"},
                "embedding": {"backend": "lmstudio", "model": LMSTUDIO_MODEL_NAME, "model_version": LMSTUDIO_MODEL_VERSION, "dimensions": dimensions},
                "database_sha256": sha256_file(database),
                "api_secret_persisted": False,
            }
        )
        write_json_atomic(manifest_path, manifest)
        refreshed[family] = len(retained_hashes)
    return refreshed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--acquired-families",
        nargs="+",
        choices=("ROCKSALT", "OLIVINE", "ARGYRODITE", "GARNET", "RUDDLESDEN_POPPER"),
    )
    parser.add_argument("--refresh-manifests", action="store_true")
    parser.add_argument(
        "--families",
        nargs="+",
        choices=("LAYERED_OXIDE", "SPINEL", "NASICON"),
        default=["LAYERED_OXIDE", "SPINEL", "NASICON"],
    )
    args = parser.parse_args()
    reports = []
    if args.refresh_manifests:
        print(json.dumps(refresh_build_manifests(list(TARGET_BUILD_FAMILIES)), sort_keys=True))
        return 0
    if args.acquired_families:
        for family in args.acquired_families:
            reports.append(
                build_acquired_family(
                    family, force=args.force, workers=max(1, args.workers)
                )
            )
        print(json.dumps({report["family"]: report["counts"] for report in reports}, sort_keys=True))
        return 0
    for family in args.families:
        if family == "NASICON":
            source_db, selected, classifier = nasicon_selection()
            regenerate = True
        else:
            source_db, selected, classifier = oxide_selection(family)
            regenerate = False
        reports.append(
            freeze_selected(
                family=family,
                source_db=source_db,
                selected=selected,
                classifier_version=classifier,
                force=args.force,
                generate_missing_condensed=regenerate,
                workers=max(1, args.workers),
            )
        )
    print(json.dumps({report["family"]: report["counts"] for report in reports}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
