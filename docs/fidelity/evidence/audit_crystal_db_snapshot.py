"""Produce the read-only Ticket 25 Crystal-DB asset audit.

The source repository is evidence. This script opens SQLite files with
``mode=ro`` and never copies, migrates, vacuums, or otherwise mutates them.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
CANONICAL_DB = SOURCE / "data" / "phase6_mp_10k.db"
REVISION = "e33d5cc55be01f800a7cf055cc1793d982deb5bc"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def schema_hash(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT type, name, tbl_name, COALESCE(sql, '') AS sql "
        "FROM sqlite_master ORDER BY type, name, tbl_name"
    ).fetchall()
    encoded = json.dumps([dict(row) for row in rows], sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def database_inventory(path: Path) -> dict[str, object]:
    connection = readonly(path)
    tables = [
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    counts = {
        table: connection.execute(
            f'SELECT COUNT(*) FROM "{table.replace(chr(34), chr(34) * 2)}"'
        ).fetchone()[0]
        for table in tables
    }
    indexes = [
        dict(row)
        for row in connection.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master "
            "WHERE type='index' ORDER BY name"
        )
    ]
    provenance: dict[str, object] = {}
    if "provenance" in tables:
        provenance = {
            "sources": [
                dict(row)
                for row in connection.execute(
                    "SELECT source, COUNT(*) AS records FROM provenance "
                    "GROUP BY source ORDER BY records DESC, source"
                )
            ],
            "retrieval_range": dict(
                connection.execute(
                    "SELECT MIN(retrieved_at) AS earliest, MAX(retrieved_at) AS latest "
                    "FROM provenance"
                ).fetchone()
            ),
            "policies": [
                dict(row)
                for row in connection.execute(
                    "SELECT license_notes, policy_id, allow_cif_store, allow_cif_return, "
                    "allow_derivatives, allow_export, COUNT(*) AS records "
                    "FROM provenance GROUP BY license_notes, policy_id, allow_cif_store, "
                    "allow_cif_return, allow_derivatives, allow_export "
                    "ORDER BY records DESC"
                )
            ],
        }
    result = {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": sha256(path),
        "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
        "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
        "foreign_keys_connection_state": connection.execute("PRAGMA foreign_keys").fetchone()[0],
        "foreign_key_violations": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
        "schema_sha256": schema_hash(connection),
        "tables": tables,
        "row_counts": counts,
        "indexes": indexes,
        "provenance": provenance,
    }
    connection.close()
    return result


def operational_path_evidence() -> dict[str, object]:
    connection = readonly(CANONICAL_DB)
    path_columns = {
        "candidates": ["input_path"],
        "proposed_structures": ["cif_text_or_path", "cif_path"],
        "runs": ["config_json", "args_json"],
        "run_steps": ["input_json", "output_json"],
        "tool_calls": ["input_json", "output_json"],
    }
    patterns = {
        "developer_home": r"C:\Users\brow" + "n",
        "source_checkout": "Crystal-DB",
        "skill_loop_checkout": "Skill-Loop-CSP",
    }
    matches: list[dict[str, object]] = []
    for table, columns in path_columns.items():
        present = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for column in columns:
            if column not in present:
                continue
            for label, pattern in patterns.items():
                escaped = pattern.replace("%", r"\%").replace("_", r"\_")
                count = connection.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" LIKE ? ESCAPE \'\\\'',
                    (f"%{escaped}%",),
                ).fetchone()[0]
                samples = [
                    row[0]
                    for row in connection.execute(
                        f'SELECT "{column}" FROM "{table}" WHERE "{column}" LIKE ? '
                        "ESCAPE '\\' ORDER BY rowid LIMIT 3",
                        (f"%{escaped}%",),
                    )
                ]
                if count:
                    matches.append(
                        {
                            "table": table,
                            "column": column,
                            "pattern": label,
                            "count": count,
                            "samples": samples,
                        }
                    )
    embedded = dict(
        connection.execute(
            "SELECT COUNT(*) AS structures, "
            "SUM(CASE WHEN cif_text IS NOT NULL AND LENGTH(cif_text) > 0 THEN 1 ELSE 0 END) "
            "AS embedded_cifs FROM structures"
        ).fetchone()
    )
    representation_counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "metadata",
            "structure_descriptors",
            "structure_fingerprints",
            "structure_embeddings",
            "structure_texts",
            "text_docs",
            "text_embeddings",
            "query_embeddings",
        )
    }
    embedding_spaces = [
        dict(row)
        for row in connection.execute(
            "SELECT embed_engine, model, model_version, dim, status, COUNT(*) AS records "
            "FROM text_embeddings GROUP BY embed_engine, model, model_version, dim, status "
            "ORDER BY records DESC"
        )
    ]
    connection.close()
    return {
        "embedded_cif_coverage": embedded,
        "persisted_representation_counts": representation_counts,
        "embedding_spaces": embedding_spaces,
        "stored_absolute_path_occurrences": matches,
        "runtime_conclusion": (
            "The canonical retrieval, ID-mode CSP-pack, novelty, and readiness paths use the "
            "SQLite database and package schemas/policies. The external mp_stable_10k and "
            "cache_mp_10k trees are acquisition/reconstruction inputs, not dereferenced by "
            "those stored-data operations. Stored developer paths occur only in historical "
            "run/audit JSON and are not opened by retrieval."
        ),
    }


def classification(name: str) -> tuple[str, str, str, str]:
    if name == "phase6_mp_10k.db":
        return (
            "REQUIRED_BUT_PROVENANCE_BLOCKED",
            "Canonical Crystal MCP/Skill-Loop general database; contains 10,000 Materials Project records and raw CIF text.",
            "MATERIALS_PROJECT_API_DERIVED_CONFIRMED",
            "BLOCKED_PENDING_EXPLICIT_REDISTRIBUTION_APPROVAL",
        )
    if name == "mp_stable_10k":
        return (
            "THIRD_PARTY_REVIEW",
            "10,001-file raw acquisition/CIF corpus; useful for exact rebuild provenance but not dereferenced by stored-data runtime.",
            "MATERIALS_PROJECT_RAW_CIF_CORPUS_CONFIRMED",
            "NOT_APPROVED_FOR_REDISTRIBUTION",
        )
    if name == "cache_mp_10k":
        return (
            "CACHE_ONLY",
            "10,000-file Materials Project acquisition cache; canonical database already persists required runtime records.",
            "MATERIALS_PROJECT_API_CACHE_CONFIRMED",
            "NOT_SELECTED_AND_NOT_APPROVED",
        )
    if name == "artifacts":
        return (
            "GENERATED_OUTPUT",
            "Aggregate reports, plots, paper/evaluation outputs and specialist generated databases; no default runtime lookup.",
            "MIXED_GENERATED_PROJECT_AND_THIRD_PARTY_DERIVED",
            "NOT_SELECTED",
        )
    if name.startswith(("bench", "case_", "cases_")) or name in {"_bench_tmp.cif", "gold"}:
        return (
            "BENCHMARK_ONLY",
            "Benchmark fixture, labeled case set, or benchmark result; not used by default MCP resolution.",
            "BENCHMARK_PROVENANCE_REVIEWED_AT_CATEGORY_LEVEL",
            "NOT_SELECTED",
        )
    if name.startswith("tmp_") or name in {"candidates", "test.txt"}:
        return (
            "STALE_UNUSED",
            "Temporary, empty, or smoke-test holding with no canonical configuration reference.",
            "LOCAL_TEMPORARY",
            "NOT_SELECTED",
        )
    if name in {"calibration_out_smoke", "gate_out", "nasicon_audit", "nasicon_v2_enrichment_20260803", "result_datasets"}:
        return (
            "GENERATED_OUTPUT",
            "Generated calibration, audit, enrichment, gate, or result output; reproducible code is already restored.",
            "PROJECT_GENERATED_FROM_MIXED_INPUTS",
            "NOT_SELECTED",
        )
    if name.endswith(".db"):
        return (
            "BENCHMARK_ONLY",
            "Specialist NASICON/paper/result database selected by explicit experiment routes, not the canonical general workflow.",
            "MATERIALS_PROJECT_DERIVED_OR_SPECIALIST_REVIEW_REQUIRED",
            "NOT_SELECTED",
        )
    return (
        "GENERATED_OUTPUT",
        "No canonical runtime configuration or empirical stored-data dependency.",
        "LOCAL_GENERATED",
        "NOT_SELECTED",
    )


def update_asset_manifest() -> None:
    path = ROOT / "docs" / "fidelity" / "CRYSTAL_DB_ASSET_MANIFEST.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    for field in ("ticket25_classification", "ticket25_evidence"):
        if field not in fields:
            fields.append(field)
    for row in rows:
        category, evidence, provenance, redistribution = classification(Path(row["source_path"]).name)
        row["ticket25_classification"] = category
        row["ticket25_evidence"] = evidence
        row["provenance_status"] = provenance
        row["redistribution_status"] = redistribution
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_snapshot_manifest() -> None:
    path = ROOT / "docs" / "fidelity" / "CRYSTAL_DB_OPERATIONAL_SNAPSHOT.csv"
    fields = [
        "archive_relative_path",
        "source_path",
        "size",
        "sha256",
        "asset_type",
        "runtime_role",
        "required_by",
        "provenance_status",
        "redistribution_status",
        "storage_method",
    ]
    row = {
        "archive_relative_path": "data/crystal_db/phase6_mp_10k.db",
        "source_path": str(CANONICAL_DB),
        "size": str(CANONICAL_DB.stat().st_size),
        "sha256": sha256(CANONICAL_DB),
        "asset_type": "SQLITE_OPERATIONAL_DATABASE",
        "runtime_role": "Canonical general Crystal-DB retrieval/index/representation snapshot",
        "required_by": "Crystal-DB MCP; Skill-Loop crystal.csp_pack and crystal.novelty_check",
        "provenance_status": "MATERIALS_PROJECT_API_DERIVED_CONFIRMED",
        "redistribution_status": "REQUIRED_BUT_PROVENANCE_BLOCKED",
        "storage_method": "NOT_STORED_PROVENANCE_BLOCKED",
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


def update_matrix() -> None:
    path = ROOT / "docs" / "fidelity" / "SOURCE_TO_ARCHIVE_MATRIX.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    for row in rows:
        if (
            row["source_repo"] == "Crystal-DB"
            and row.get("source_entry_point") == "local runtime asset"
        ):
            name = Path(row["source_path_or_capability"]).name
            category = classification(name)[0]
            row["recovery_ticket"] = "25"
            row["recovery_status"] = (
                "BLOCKED_PROVENANCE"
                if category in {"REQUIRED_BUT_PROVENANCE_BLOCKED", "THIRD_PARTY_REVIEW"}
                else "EXCLUDED_GENERATED_OUTPUT"
                if category in {"GENERATED_OUTPUT", "CACHE_ONLY", "STALE_UNUSED"}
                else "DEFERRED_OPTIONAL"
            )
            row["recovery_archive_path"] = ""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    databases = sorted(
        (
            path
            for path in SOURCE.rglob("*.db")
            if ".venv" not in path.parts and ".git" not in path.parts
        ),
        key=lambda path: path.as_posix().lower(),
    )
    inventory = {
        "source_revision": REVISION,
        "inspection_mode": "SQLite URI mode=ro; no source mutation",
        "canonical_database": str(CANONICAL_DB),
        "databases": [database_inventory(path) for path in databases],
        "canonical_operational_path_evidence": operational_path_evidence(),
    }
    output = ROOT / "docs" / "fidelity" / "evidence" / "CRYSTAL_DB_DATABASE_INVENTORY.json"
    output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    update_asset_manifest()
    write_snapshot_manifest()
    update_matrix()
    hashes = ROOT / "docs" / "fidelity" / "CRYSTAL_DB_ASSET_HASHES.txt"
    hashes.write_text(
        "# Ticket 25 required asset hash\n"
        f"{sha256(CANONICAL_DB)}  source:Crystal-DB/data/phase6_mp_10k.db\n"
        "MISSING  archive:data/crystal_db/phase6_mp_10k.db  "
        "REQUIRED_BUT_PROVENANCE_BLOCKED\n",
        encoding="utf-8",
    )
    print(f"Audited {len(databases)} SQLite databases; required asset remains provenance-blocked")


if __name__ == "__main__":
    main()
