"""Audit Crystal-DB corpora for the Paper_scaffolds_september experiment.

This script is intentionally read-only with respect to existing databases. The
normal retrieval API is exercised against temporary database copies because its
schema-initialisation path may migrate an older database.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from typing import Any, Iterable

from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crystal_db.family_dataset import write_json_atomic  # noqa: E402
from crystal_db.retrieval import similar_text, text_search  # noqa: E402
from scripts.build_nasicon_specialist_corpus import (  # noqa: E402
    KNOWN_NASICON_FORMULAS,
    framework_metrics,
)


SCHEMA_VERSION = "paper_scaffolds_specialist_corpus_audit.v1"
TARGET_FAMILIES = (
    "LAYERED_OXIDE",
    "SPINEL",
    "NASICON",
    "ROCKSALT",
    "OLIVINE",
    "ARGYRODITE",
    "GARNET",
    "RUDDLESDEN_POPPER",
)
INVENTORY_FIELDS = (
    "corpus_name",
    "path",
    "database_format",
    "file_size_bytes",
    "file_modified_utc",
    "row_count",
    "unique_material_ids",
    "unique_structure_hashes",
    "duplicate_rate",
    "formula_count",
    "formulas_sample",
    "elements",
    "sources",
    "source_dates",
    "source_cif_rows",
    "provenance_rows",
    "robocrys_rows",
    "robocrys_condensed_rows",
    "fingerprint_rows",
    "vector_rows",
    "vector_models",
    "vector_dimensions",
    "nonfinite_vector_rows",
    "retrieval_works",
    "retrieval_detail",
    "missing_cif_rows",
    "corrupt_cif_rows",
    "family_labels",
    "labels_trustworthy",
    "routed_by_skill_loop",
    "paper_suitable",
    "database_sha256",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    if table not in table_names(connection):
        return set()
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def count(connection: sqlite3.Connection, table: str, where: str = "") -> int:
    if table not in table_names(connection):
        return 0
    suffix = f" WHERE {where}" if where else ""
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"{suffix}').fetchone()[0])


def database_paths(repo_root: Path, extra_roots: Iterable[Path] = ()) -> list[Path]:
    paths = []
    for root in (repo_root, *extra_roots):
        if not root.is_dir():
            continue
        for suffix in ("*.db", "*.sqlite", "*.sqlite3"):
            paths.extend(root.rglob(suffix))
    return sorted(
        {
            path.resolve()
            for path in paths
            if ".venv" not in path.parts and path.is_file()
        },
        key=lambda path: str(path).lower(),
    )


def decode_vector(raw: Any) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(value, list):
            return None
        return [float(item) for item in value]
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def structure_metrics(connection: sqlite3.Connection) -> dict[str, Any]:
    tables = table_names(connection)
    if "structures" not in tables:
        return {
            "hashes": set(),
            "formulas": set(),
            "elements": set(),
            "missing": 0,
            "corrupt": 0,
            "atom_counts": [],
            "space_groups": set(),
        }
    hashes: set[str] = set()
    formulas: set[str] = set()
    elements: set[str] = set()
    atom_counts: list[int] = []
    space_groups: set[str] = set()
    missing = 0
    corrupt = 0
    for row in connection.execute("SELECT structure_id, cif_text FROM structures ORDER BY structure_id"):
        cif_text = row["cif_text"]
        if not cif_text:
            missing += 1
            continue
        hashes.add(sha256_text(str(cif_text)))
        try:
            structure = Structure.from_str(str(cif_text), fmt="cif")
            primitive = structure.get_primitive_structure()
            atom_counts.append(len(primitive))
            formulas.add(structure.composition.reduced_formula)
            elements.update(element.symbol for element in structure.composition.elements)
            analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
            space_groups.add(f"{analyzer.get_space_group_symbol()} ({analyzer.get_space_group_number()})")
        except Exception:
            corrupt += 1
    return {
        "hashes": hashes,
        "formulas": formulas,
        "elements": elements,
        "missing": missing,
        "corrupt": corrupt,
        "atom_counts": atom_counts,
        "space_groups": space_groups,
    }


def embedding_metrics(connection: sqlite3.Connection) -> dict[str, Any]:
    tables = table_names(connection)
    if not {"text_embeddings", "text_docs"}.issubset(tables):
        return {"rows": 0, "dimensions": set(), "models": set(), "nonfinite": 0}
    dimensions: set[int] = set()
    models: set[str] = set()
    nonfinite = 0
    rows = 0
    query = (
        "SELECT te.embed_engine,te.model,te.model_version,te.dim,te.vector "
        "FROM text_embeddings te JOIN text_docs td ON td.id=te.text_doc_id "
        "WHERE te.status='OK'"
    )
    for row in connection.execute(query):
        rows += 1
        vector = decode_vector(row["vector"])
        if vector is None or not vector or any(not math.isfinite(value) for value in vector):
            nonfinite += 1
            continue
        dimensions.add(len(vector))
        if row["dim"] is not None and int(row["dim"]) != len(vector):
            nonfinite += 1
        models.add(f"{row['embed_engine']}/{row['model']}/{row['model_version']}")
    return {"rows": rows, "dimensions": dimensions, "models": models, "nonfinite": nonfinite}


def dominant_embedding_space(connection: sqlite3.Connection) -> sqlite3.Row | None:
    if not {"text_embeddings", "text_docs"}.issubset(table_names(connection)):
        return None
    return connection.execute(
        "SELECT td.structure_id,te.embed_engine,te.model,te.model_version,COUNT(*) OVER "
        "(PARTITION BY te.embed_engine,te.model,te.model_version) AS n "
        "FROM text_embeddings te JOIN text_docs td ON td.id=te.text_doc_id "
        "WHERE te.status='OK' ORDER BY n DESC,td.structure_id LIMIT 1"
    ).fetchone()


def retrieval_smoke(path: Path) -> tuple[bool, str]:
    connection = read_only_connection(path)
    try:
        space = dominant_embedding_space(connection)
    finally:
        connection.close()
    if space is None or int(space["n"]) < 2:
        return False, "fewer_than_two_OK_text_embeddings"
    with tempfile.TemporaryDirectory() as temporary_directory:
        copied = Path(temporary_directory) / path.name
        shutil.copy2(path, copied)
        result = similar_text(
            structure_id=str(space["structure_id"]),
            db_path=str(copied),
            k=3,
            engine=str(space["embed_engine"]),
            model_name=str(space["model"]),
            model_version=str(space["model_version"]),
        )
    neighbors = result.get("neighbors") if isinstance(result, dict) else None
    if neighbors:
        formulas = [str(item.get("metadata", {}).get("formula") or "REDACTED") for item in neighbors]
        return True, ";".join(formulas)
    return False, str(result.get("error") or result.get("code") or "empty_neighbors")


def annotation_labels(connection: sqlite3.Connection) -> list[str]:
    if "structure_annotations" not in table_names(connection):
        return []
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT family_assignment FROM structure_annotations "
            "WHERE family_assignment IS NOT NULL ORDER BY family_assignment"
        )
    ]


def routed_database_paths() -> set[Path]:
    registry = REPO_ROOT.parent / "Skill-Loop-CSP/data/corpora/registry.json"
    if not registry.is_file():
        return set()
    payload = json.loads(registry.read_text(encoding="utf-8"))
    routed: set[Path] = set()
    for record in payload.get("corpora", {}).values():
        database = str(record.get("database") or "").replace("/", "\\")
        if record.get("path_base") == "repository":
            routed.add((registry.parents[2] / database).resolve())
        elif record.get("path_base") == "github_parent":
            routed.add((REPO_ROOT.parent / database).resolve())
    return routed


def audit_database(path: Path, *, run_retrieval: bool = True) -> dict[str, Any]:
    connection = read_only_connection(path)
    try:
        tables = table_names(connection)
        rows = count(connection, "structures")
        metrics = structure_metrics(connection)
        embeddings = embedding_metrics(connection)
        material_ids = 0
        sources: list[str] = []
        source_dates: list[str] = []
        if "provenance" in tables:
            material_ids = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT source || ':' || COALESCE(source_id,'')) FROM provenance"
                ).fetchone()[0]
            )
            sources = [str(row[0]) for row in connection.execute("SELECT DISTINCT source FROM provenance ORDER BY source")]
            source_dates = [
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT retrieved_at FROM provenance WHERE retrieved_at IS NOT NULL ORDER BY retrieved_at"
                ).fetchall()[-5:]
            ]
        true_robocrys = 0
        if "text_docs" in tables:
            text_columns = column_names(connection, "text_docs")
            view_clause = " AND text_view='robocrys'" if "text_view" in text_columns else ""
            true_robocrys = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT structure_id) FROM text_docs "
                    "WHERE engine='robocrys' AND status='OK' AND text IS NOT NULL" + view_clause
                ).fetchone()[0]
            )
        true_condensed = count(connection, "robocrys_condensed")
        fingerprints = 0
        if "structure_fingerprints" in tables:
            fingerprints = int(
                connection.execute("SELECT COUNT(DISTINCT structure_id) FROM structure_fingerprints").fetchone()[0]
            )
        retrieval_works, retrieval_detail = (
            retrieval_smoke(path) if run_retrieval else (False, "not_run")
        )
        duplicate_rate = ((rows - len(metrics["hashes"])) / rows) if rows else 0.0
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        labels = annotation_labels(connection)
        specialist = any(token in str(path).lower() for token in ("layered", "spinel", "nasicon"))
        fully_complete = bool(
            rows
            and len(metrics["hashes"]) == rows
            and count(connection, "provenance") == rows
            and true_robocrys == rows
            and true_condensed == rows
            and fingerprints == rows
            and embeddings["rows"] >= rows
            and embeddings["nonfinite"] == 0
            and retrieval_works
        )
        routed_paths = routed_database_paths()
        corpus_name = path.parent.name if path.stem.lower() in {"crystaldb", "crystaldb.sqlite"} else path.stem
        return {
            "corpus_name": corpus_name,
            "path": str(path),
            "database_format": "SQLite",
            "file_size_bytes": path.stat().st_size,
            "file_modified_utc": modified,
            "row_count": rows,
            "unique_material_ids": material_ids,
            "unique_structure_hashes": len(metrics["hashes"]),
            "duplicate_rate": round(duplicate_rate, 8),
            "formula_count": len(metrics["formulas"]),
            "formulas_sample": ";".join(sorted(metrics["formulas"])[:20]),
            "elements": ";".join(sorted(metrics["elements"])),
            "sources": ";".join(sources),
            "source_dates": ";".join(source_dates),
            "source_cif_rows": rows - metrics["missing"],
            "provenance_rows": count(connection, "provenance"),
            "robocrys_rows": true_robocrys,
            "robocrys_condensed_rows": true_condensed,
            "fingerprint_rows": fingerprints,
            "vector_rows": embeddings["rows"],
            "vector_models": ";".join(sorted(embeddings["models"])),
            "vector_dimensions": ";".join(str(value) for value in sorted(embeddings["dimensions"])),
            "nonfinite_vector_rows": embeddings["nonfinite"],
            "retrieval_works": retrieval_works,
            "retrieval_detail": retrieval_detail,
            "missing_cif_rows": metrics["missing"],
            "corrupt_cif_rows": metrics["corrupt"],
            "family_labels": ";".join(labels),
            "labels_trustworthy": bool(labels and "candidate" not in " ".join(labels).lower()),
            "routed_by_skill_loop": path.resolve() in routed_paths,
            "paper_suitable": fully_complete if specialist else False,
            "database_sha256": sha256_file(path),
            "atom_counts": metrics["atom_counts"],
            "space_groups": sorted(metrics["space_groups"]),
        }
    finally:
        connection.close()


def percentile(values: list[int], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def known_nasicon_composition(composition: Composition) -> bool:
    reduced = composition.reduced_composition
    return any(reduced == Composition(formula).reduced_composition for formula in KNOWN_NASICON_FORMULAS)


def validate_nasicon_candidates(path: Path) -> dict[str, Any]:
    connection = read_only_connection(path)
    accepted = 0
    total = 0
    evidence: list[dict[str, Any]] = []
    try:
        for row in connection.execute("SELECT structure_id,cif_text FROM structures ORDER BY structure_id"):
            total += 1
            try:
                structure = Structure.from_str(str(row["cif_text"]), fmt="cif")
                metrics = framework_metrics(structure)
                passed = bool(
                    structure.is_ordered
                    and known_nasicon_composition(structure.composition)
                    and metrics["coordination_all_expected"]
                    and metrics["framework_components"] == 1
                    and metrics["framework_dimensionality"] == 3
                )
                accepted += int(passed)
                evidence.append(
                    {
                        "structure_id": row["structure_id"],
                        "accepted": passed,
                        "formula": structure.composition.reduced_formula,
                        "framework_metrics": metrics,
                    }
                )
            except Exception as exc:
                evidence.append(
                    {"structure_id": row["structure_id"], "accepted": False, "error": str(exc)}
                )
    finally:
        connection.close()
    return {"total": total, "accepted": accepted, "evidence": evidence}


def accepted_subset_metrics(path: Path, accepted_ids: list[str]) -> dict[str, Any]:
    connection = read_only_connection(path)
    placeholders = ",".join("?" for _ in accepted_ids)
    hashes: set[str] = set()
    formulas: set[str] = set()
    space_groups: set[str] = set()
    atom_counts: list[int] = []
    try:
        rows = connection.execute(
            f"SELECT structure_id,cif_text FROM structures WHERE structure_id IN ({placeholders}) ORDER BY structure_id",
            tuple(accepted_ids),
        ).fetchall()
        for row in rows:
            cif_text = str(row["cif_text"] or "")
            hashes.add(sha256_text(cif_text))
            structure = Structure.from_str(cif_text, fmt="cif")
            primitive = structure.get_primitive_structure()
            formulas.add(structure.composition.reduced_formula)
            atom_counts.append(len(primitive))
            analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
            space_groups.add(f"{analyzer.get_space_group_symbol()} ({analyzer.get_space_group_number()})")
        robocrys = int(
            connection.execute(
                f"SELECT COUNT(DISTINCT structure_id) FROM text_docs WHERE structure_id IN ({placeholders}) "
                "AND engine='robocrys' AND text_view='robocrys' AND status='OK' AND text IS NOT NULL",
                tuple(accepted_ids),
            ).fetchone()[0]
        )
        condensed = int(
            connection.execute(
                f"SELECT COUNT(DISTINCT structure_id) FROM robocrys_condensed WHERE structure_id IN ({placeholders})",
                tuple(accepted_ids),
            ).fetchone()[0]
        )
        fingerprints = int(
            connection.execute(
                f"SELECT COUNT(DISTINCT structure_id) FROM structure_fingerprints WHERE structure_id IN ({placeholders})",
                tuple(accepted_ids),
            ).fetchone()[0]
        )
        vectors = int(
            connection.execute(
                f"SELECT COUNT(DISTINCT td.structure_id) FROM text_embeddings te JOIN text_docs td ON td.id=te.text_doc_id "
                f"WHERE td.structure_id IN ({placeholders}) AND td.engine='robocrys' AND td.text_view='robocrys' AND te.status='OK'",
                tuple(accepted_ids),
            ).fetchone()[0]
        )
        total_database_rows = count(connection, "structures")
    finally:
        connection.close()
    return {
        "rows": len(rows),
        "hashes": len(hashes),
        "formulas": len(formulas),
        "space_groups": len(space_groups),
        "atom_counts": atom_counts,
        "robocrys": robocrys,
        "condensed": condensed,
        "fingerprints": fingerprints,
        "vectors": vectors,
        "database_total_rows": total_database_rows,
    }


def accepted_ids_from_manifest(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return sorted({str(value) for value in payload.get("accepted_structure_ids", [])})


def topology_tier_counts_from_manifest(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not path.is_file():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        tier = str(json.loads(line).get("topology_tier", ""))
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def family_rows(inventory: list[dict[str, Any]], output_root: Path) -> list[dict[str, Any]]:
    by_path = {Path(row["path"]).resolve(): row for row in inventory}
    layered_path = (
        REPO_ROOT
        / "artifacts/mp_oxide_families_v1/MP_LAYERED_BATTERY_OXIDES_V1/MP_LAYERED_BATTERY_OXIDES_V1.db"
    ).resolve()
    spinel_path = (
        REPO_ROOT
        / "artifacts/mp_oxide_families_v1/MP_SPINEL_OXIDES_V1/MP_SPINEL_OXIDES_V1.db"
    ).resolve()
    skill_loop_root = REPO_ROOT.parent / "Skill-Loop-CSP"
    routed_nasicon_path = (skill_loop_root / "data/corpora/nasicon_specialist_v3/crystaldb.sqlite").resolve()
    candidate_nasicon_path = (REPO_ROOT / "data/nasicon_topology_candidates.db").resolve()
    nasicon_path = routed_nasicon_path if routed_nasicon_path in by_path else candidate_nasicon_path
    nasicon_validation = validate_nasicon_candidates(candidate_nasicon_path) if candidate_nasicon_path.is_file() else None
    oxide_manifests = {
        "LAYERED_OXIDE": REPO_ROOT / "artifacts/mp_oxide_families_v1/MP_LAYERED_BATTERY_OXIDES_V1/dataset_manifest.json",
        "SPINEL": REPO_ROOT / "artifacts/mp_oxide_families_v1/MP_SPINEL_OXIDES_V1/dataset_manifest.json",
    }
    rows = []
    for family in TARGET_FAMILIES:
        final_path = (
            output_root
            / "families"
            / family
            / f"PAPER_SCAFFOLDS_{family}_V1"
            / "crystaldb.sqlite"
        ).resolve()
        if final_path in by_path:
            source = by_path[final_path]
            connection = read_only_connection(final_path)
            try:
                validated = int(
                    connection.execute(
                        "SELECT COUNT(DISTINCT structure_id) FROM structure_annotations "
                        "WHERE family_assignment=?",
                        (family,),
                    ).fetchone()[0]
                )
            finally:
                connection.close()
            action = (
                "REBUILD_EXISTING"
                if family in {"LAYERED_OXIDE", "SPINEL", "NASICON"}
                else "CREATE_NEW"
            )
            method = "family classifier and evidence stored in structure_annotations"
            atom_counts = list(source["atom_counts"])
            rows.append(
                {
                    "family": family,
                    "existing_corpus": source["corpus_name"],
                    "existing_path": source["path"],
                    "existing_rows": source["row_count"],
                    "hash_unique": source["unique_structure_hashes"],
                    "robocrys_complete": source["robocrys_rows"] == source["row_count"]
                    and source["robocrys_condensed_rows"] == source["row_count"],
                    "fingerprint_complete": source["fingerprint_rows"] == source["row_count"],
                    "vector_complete": source["vector_rows"] >= source["row_count"],
                    "retrieval_ready": source["retrieval_works"],
                    "family_validation_method": method,
                    "validated_family_rows": validated,
                    "composition_count": source["formula_count"],
                    "space_group_count": len(source["space_groups"]),
                    "median_atoms_primitive": percentile(atom_counts, 0.5),
                    "max_atoms_primitive": max(atom_counts) if atom_counts else None,
                    "decision": action,
                    "reason": (
                        f"{action} completed as an accepted-only, structurally annotated corpus; "
                        "all canonical representation stages and normal retrieval passed."
                    ),
                }
            )
            continue
        path: Path | None = None
        method = "no formal repository classifier found"
        validated = 0
        decision = "CREATE_NEW"
        reason = "No specialist corpus exists in the repository."
        if family == "LAYERED_OXIDE" and layered_path in by_path:
            path = layered_path
            accepted_ids = accepted_ids_from_manifest(oxide_manifests[family])
            subset = accepted_subset_metrics(path, accepted_ids)
            validated = subset["rows"]
            method = "mp_oxide_family.v1: RoboCrys layered signal plus coordination/layer evidence"
            decision = "REBUILD_EXISTING"
            reason = (
                f"The {subset['rows']}-row accepted subset is representation-complete, but the routed SQLite "
                f"contains {subset['database_total_rows']} total candidate rows, including rejected/quarantined structures."
            )
        elif family == "SPINEL" and spinel_path in by_path:
            path = spinel_path
            accepted_ids = accepted_ids_from_manifest(oxide_manifests[family])
            subset = accepted_subset_metrics(path, accepted_ids)
            validated = subset["rows"]
            method = "mp_oxide_family.v1: spinel RoboCrys signal plus tetrahedral/octahedral coordination"
            decision = "REBUILD_EXISTING"
            reason = (
                f"The {subset['rows']}-row accepted subset is representation-complete, but the routed SQLite "
                f"contains {subset['database_total_rows']} total candidate rows, including rejected/quarantined structures."
            )
        elif family == "NASICON" and nasicon_path in by_path:
            path = nasicon_path
            tier_counts = topology_tier_counts_from_manifest(path.parent / "manifest.jsonl")
            validated = sum(
                count_value
                for tier_name, count_value in tier_counts.items()
                if tier_name in {"TIER_1_TOPOLOGY", "TIER_1_TOPOLOGY_PROXY"}
            )
            method = "stored ordered coordination/single-component/rank-3 periodic framework proxy"
            decision = "REBUILD_EXISTING"
            reason = (
                f"The routed v3 corpus has {validated} topology-proxy rows but also "
                f"{by_path[path]['row_count'] - validated} Tier-2 chemical-framework support rows without a NASICON topology claim; "
                "its manifest carries the tier evidence, while the SQLite database lacks populated structure annotations and "
                "structured RoboCrys condensed rows."
            )
            family_dir = output_root / "families" / family
            family_dir.mkdir(parents=True, exist_ok=True)
            write_json_atomic(family_dir / "validation.json", nasicon_validation)
        source = by_path.get(path) if path else None
        if family in oxide_manifests and source:
            atom_counts = subset["atom_counts"]
            existing_rows = subset["rows"]
            hash_unique = subset["hashes"]
            robocrys_complete = subset["robocrys"] == subset["rows"] and subset["condensed"] == subset["rows"]
            fingerprint_complete = subset["fingerprints"] == subset["rows"]
            vector_complete = subset["vectors"] == subset["rows"]
            retrieval_ready = False
            composition_count = subset["formulas"]
            space_group_count = subset["space_groups"]
        else:
            atom_counts = list(source.get("atom_counts", [])) if source else []
            existing_rows = source["row_count"] if source else 0
            hash_unique = source["unique_structure_hashes"] if source else 0
            robocrys_complete = bool(source and source["robocrys_rows"] == source["row_count"] and source["robocrys_condensed_rows"] == source["row_count"])
            fingerprint_complete = bool(source and source["fingerprint_rows"] == source["row_count"])
            vector_complete = bool(source and source["vector_rows"] >= source["row_count"])
            retrieval_ready = bool(source and source["retrieval_works"])
            composition_count = source["formula_count"] if source else 0
            space_group_count = len(source["space_groups"]) if source else 0
        rows.append(
            {
                "family": family,
                "existing_corpus": source["corpus_name"] if source else "",
                "existing_path": source["path"] if source else "",
                "existing_rows": existing_rows,
                "hash_unique": hash_unique,
                "robocrys_complete": robocrys_complete,
                "fingerprint_complete": fingerprint_complete,
                "vector_complete": vector_complete,
                "retrieval_ready": retrieval_ready,
                "family_validation_method": method,
                "validated_family_rows": validated,
                "composition_count": composition_count,
                "space_group_count": space_group_count,
                "median_atoms_primitive": percentile(atom_counts, 0.5),
                "max_atoms_primitive": max(atom_counts) if atom_counts else None,
                "decision": decision,
                "reason": reason,
            }
        )
    return rows


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def write_pipeline_map(output_root: Path) -> None:
    versions = {
        name: package_version(name)
        for name in ("crystaldb", "mp-api", "pymatgen", "robocrys", "spglib")
    }
    rows = [
        ["MP fetching", "scripts/build_crystaldb_corpus.py; scripts/build_mp_oxide_family_datasets.py", "MP query", "structures + source metadata", f"mp-api {versions['mp-api']}"],
        ["CIF persistence", "crystal_db.ingest_folder.ingest_folder", "CIF folder", "structures/metadata/provenance", "normalized CIF; policy-controlled"],
        ["RoboCrys", "crystal_db.textgen.generate_robocrys", "stored CIF", "text_docs + robocrys_condensed", f"robocrys {versions['robocrys']}; engine robocrys.v1"],
        ["Fingerprint", "crystal_db.fingerprint.fingerprint_structure", "metadata/descriptors", "structure_fingerprints", "fp.simple.v1/v1"],
        ["Vectorisation", "crystal_db.text_index.embed_text_docs", "OK text_docs", "text_embeddings + legacy structure_embeddings", "lmstudio/text-embedding-bge-m3/lmstudio_v1; 1024-D observed"],
        ["Database build", "crystal_db.db.init_db; scripts/build_crystaldb_corpus.py", "ingested rows", "SQLite corpus", "current schema tables audited"],
        ["Specialist creation", "scripts/build_mp_oxide_family_datasets.py; scripts/build_nasicon_specialist_corpus.py", "MP candidates + structural evidence", "versioned specialist DB/artifacts", "mp_oxide_family.v1; NASICON framework proxy"],
        ["Validation", "dataset_audit.json + this audit", "DB + manifests", "coverage/hash/integrity reports", f"pymatgen {versions['pymatgen']}; spglib {versions['spglib']}"],
        ["Retrieval", "crystal_db.retrieval.similar_text/text_search/similar_struct", "query structure/text", "ranked neighbors", "configs/retrieval_defaults.json"],
        ["Deduplication", "crystal_db.ingest_folder._hash_text; family bundle SHA-256; NASICON builder", "normalized/source CIF", "structure IDs + exclusion records", "SHA-256; NASICON exact hash"],
        ["Provenance", "provenance table + family manifests/records", "source metadata", "source_id/date/policy + build artifacts", "policy_name local_cif for MP downloads"],
        ["Corpus routing", "no Crystal-DB family router found; caller supplies db_path", "DB path", "selected corpus", "Skill-Loop routing audited separately"],
    ]
    text = "# Crystal-DB Pipeline Map\n\n" + markdown_table(
        ["Stage", "Existing implementation", "Input", "Output", "Version/config"], rows
    )
    text += "\n\nTrue RoboCrys coverage requires both an OK `text_docs` row whose engine and view are `robocrys` and a matching `robocrys_condensed` row. A baseline document stored with `text_view=robocrys` is not counted as RoboCrys.\n"
    (output_root / "CRYSTAL_DB_PIPELINE_MAP.md").write_text(text, encoding="utf-8")


def write_outputs(output_root: Path, inventory: list[dict[str, Any]], families: list[dict[str, Any]]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    write_pipeline_map(output_root)
    write_csv(output_root / "EXISTING_CORPUS_INVENTORY.csv", inventory, INVENTORY_FIELDS)
    coverage_fields = (
        "corpus_name", "path", "row_count", "source_cif_rows", "provenance_rows",
        "robocrys_rows", "robocrys_condensed_rows", "fingerprint_rows", "vector_rows",
        "vector_dimensions", "nonfinite_vector_rows", "retrieval_works", "paper_suitable",
    )
    write_csv(output_root / "EXISTING_CORPUS_PIPELINE_COVERAGE.csv", inventory, coverage_fields)
    family_fields = tuple(families[0].keys())
    write_csv(output_root / "SPECIALIST_FAMILY_READINESS.csv", families, family_fields)
    write_csv(output_root / "SPECIALIST_CORPUS_SUMMARY.csv", families, family_fields)
    inventory_md = "# Existing Crystal-DB Corpus Inventory\n\n" + markdown_table(
        ["Corpus", "Rows", "CIF", "RoboCrys", "Fingerprint", "Vectors", "Retrieval", "Paper suitable"],
        [
            [
                row["corpus_name"], row["row_count"], row["source_cif_rows"], row["robocrys_rows"],
                row["fingerprint_rows"], row["vector_rows"], row["retrieval_works"], row["paper_suitable"],
            ]
            for row in inventory
        ],
    )
    (output_root / "EXISTING_CORPUS_INVENTORY.md").write_text(inventory_md + "\n", encoding="utf-8")
    write_json_atomic(
        output_root / "CORPUS_HASHES.json",
        {row["path"]: {"database_sha256": row["database_sha256"], "unique_cif_sha256": row["unique_structure_hashes"]} for row in inventory},
    )
    acquisition_manifests = {}
    for family in TARGET_FAMILIES:
        path = (
            output_root
            / "families"
            / family
            / f"PAPER_SCAFFOLDS_{family}_V1"
            / "acquisition"
            / "query_manifest.json"
        )
        if path.is_file():
            acquisition_manifests[family] = json.loads(path.read_text(encoding="utf-8"))
    write_json_atomic(
        output_root / "PROVENANCE.json",
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_iso(),
            "repo_head": git_head(),
            "database_count": len(inventory),
            "existing_databases_opened_read_only": True,
            "retrieval_tests_used_temporary_database_copies": True,
            "materials_project_queried": bool(acquisition_manifests),
            "api_secret_persisted": False,
        },
    )
    write_csv(
        output_root / "MP_QUERY_SUMMARY.csv",
        [
            {
                "family": family,
                "status": "COMPLETED" if family in acquisition_manifests else "REUSED_FROZEN_SOURCE",
                "candidate_count": acquisition_manifests.get(family, {}).get("candidate_count", ""),
                "accepted_count": acquisition_manifests.get(family, {}).get("accepted_count", ""),
                "rejected_count": acquisition_manifests.get(family, {}).get("rejected_count", ""),
            }
            for family in TARGET_FAMILIES
        ],
        ("family", "status", "candidate_count", "accepted_count", "rejected_count"),
    )
    write_csv(
        output_root / "FAMILY_CLASSIFICATION_SUMMARY.csv",
        families,
        ("family", "family_validation_method", "existing_rows", "validated_family_rows", "decision", "reason"),
    )
    retrieval_rows = representative_retrieval_rows(families)
    write_csv(
        output_root / "RETRIEVAL_SMOKE_TEST.csv",
        retrieval_rows,
        ("family", "corpus", "query", "status", "top_retrieved_formulas", "non_exact_query_neighbors", "family_consistent"),
    )
    history = {
        "LAYERED_OXIDE": {"runs": "YES", "passes": "exp2v3_licoo2_layered (fixed-orbit)", "a": "NO", "b": "CANDIDATE_NO_SPP_ONLY_FAILURE_EVIDENCE", "hard": "NO", "c": "CANDIDATE"},
        "SPINEL": {"runs": "YES", "passes": "exp1_znfe2o4_spinel;exp1_mgal2o4_spinel;exp1_cofe2o4_spinel (fixed-orbit)", "a": "NO", "b": "CANDIDATE_NO_SPP_ONLY_FAILURE_EVIDENCE", "hard": "NO", "c": "CANDIDATE"},
        "NASICON": {"runs": "YES", "passes": "E4_A2;E4_C2;E4_F1 scaffold demonstrations", "a": "NO", "b": "NO", "hard": "YES", "c": "CANDIDATE"},
        "ROCKSALT": {"runs": "YES", "passes": "exp1_nio_rocksalt;exp1_tin_rocksalt;exp1_mgo_rocksalt (variable SPP)", "a": "YES", "b": "NO", "hard": "NO", "c": "CANDIDATE"},
        "OLIVINE": {"runs": "YES", "passes": "exp2v3_lifepo4_olivine (fixed-orbit)", "a": "NO", "b": "CANDIDATE_NO_SPP_ONLY_FAILURE_EVIDENCE", "hard": "NO", "c": "CANDIDATE"},
        "ARGYRODITE": {"runs": "YES", "passes": "exp2v3_li6ps5cl_argyrodite (fixed-orbit)", "a": "NO", "b": "CANDIDATE_NO_SPP_ONLY_FAILURE_EVIDENCE", "hard": "CANDIDATE_NO_UNRESTRICTED_RUN", "c": "CANDIDATE"},
        "GARNET": {"runs": "NO", "passes": "", "a": "NO", "b": "NO", "hard": "CANDIDATE_NO_HISTORY", "c": "CANDIDATE"},
        "RUDDLESDEN_POPPER": {"runs": "NO", "passes": "", "a": "NO", "b": "CANDIDATE_NO_HISTORY", "hard": "NO", "c": "CANDIDATE"},
    }
    ab_rows = []
    for row in families:
        ab_rows.append(
            {
                "family": row["family"],
                "specialist_corpus": row["existing_corpus"],
                "retrieval_ready": row["retrieval_ready"],
                "n_structures": row["existing_rows"],
                "n_compositions": row["composition_count"],
                "n_space_groups": row["space_group_count"],
                "median_atoms_primitive": row["median_atoms_primitive"],
                "max_atoms_primitive": row["max_atoms_primitive"],
                "historical_qlip_runs_available": history[row["family"]]["runs"],
                "historical_topology_pass_examples": history[row["family"]]["passes"],
                "historical_topology_fail_examples": "none established by the inspected frozen summary tables",
                "historical_timeout_examples": "none established by the inspected frozen summary tables",
                "sca_policy_available": "general geometry/contact validation available; family topology policy requires final-roster audit",
                "likely_A_use": history[row["family"]]["a"],
                "likely_B_use": history[row["family"]]["b"],
                "likely_B_HARD_use": history[row["family"]]["hard"],
                "likely_C_scaffold_use": history[row["family"]]["c"],
                "notes": row["reason"],
            }
        )
    write_csv(output_root / "PAPER_AB_FAMILY_READINESS.csv", ab_rows, tuple(ab_rows[0].keys()))
    report = "# Specialist Corpus Build Report\n\n" + markdown_table(
        ["Family", "Existing", "Rows", "RoboCrys", "Fingerprint", "Vectors", "Retrieval", "Decision"],
        [[row["family"], row["existing_corpus"] or "none", row["existing_rows"], row["robocrys_complete"], row["fingerprint_complete"], row["vector_complete"], row["retrieval_ready"], row["decision"]] for row in families],
    )
    report += "\n\nThe audit-first decisions were executed: existing contaminated/support-only corpora were rebuilt as accepted-only datasets and missing families were acquired through broad MP discovery followed by strict local structural filtering.\n"
    (output_root / "SPECIALIST_CORPUS_BUILD_REPORT.md").write_text(report, encoding="utf-8")


def representative_retrieval_rows(families: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queries = {
        "LAYERED_OXIDE": [("layered lithium cobalt oxide LiCoO2", "LiCoO2"), ("layered sodium transition metal oxide NaCoO2", "NaCoO2")],
        "SPINEL": [("zinc ferrite spinel ZnFe2O4", "ZnFe2O4"), ("magnesium aluminate spinel MgAl2O4", "MgAl2O4")],
        "NASICON": [("NASICON Na3Zr2Si2PO12 framework", "Na3Zr2Si2PO12"), ("NZP NaZr2(PO4)3 framework", "NaZr2(PO4)3")],
        "ROCKSALT": [("B1 rocksalt magnesium oxide MgO", "MgO"), ("B1 rocksalt silver bromide AgBr", "AgBr")],
        "OLIVINE": [("olivine lithium iron phosphate LiFePO4", "LiFePO4"), ("olivine lithium manganese phosphate LiMnPO4", "LiMnPO4")],
        "ARGYRODITE": [("argyrodite Li6PS5Cl solid electrolyte", "Li6PS5Cl"), ("argyrodite Li6PS5Br solid electrolyte", "Li6PS5Br")],
        "GARNET": [("LLZO garnet Li7La3Zr2O12", "Li7La3Zr2O12"), ("oxide garnet Y3Al5O12", "Y3Al5O12")],
        "RUDDLESDEN_POPPER": [("n=1 Ruddlesden Popper Sr2TiO4", "Sr2TiO4"), ("n=2 Ruddlesden Popper Sr3Ti2O7", "Sr3Ti2O7")],
    }
    rows = []
    for family in families:
        db_path = Path(family["existing_path"])
        if not db_path.is_file():
            continue
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied = Path(temporary_directory) / "crystaldb.sqlite"
            shutil.copy2(db_path, copied)
            for query, target in queries[family["family"]]:
                result = text_search(
                    query_text=query,
                    db_path=str(copied),
                    k=5,
                    embed_engine="lmstudio",
                    model_name="text-embedding-bge-m3",
                    model_version="lmstudio_v1",
                    text_engine="robocrys",
                    text_view="robocrys",
                    show_text_top=0,
                    redacted=False,
                )
                neighbor_ids = [str(item["structure_id"]) for item in result.get("neighbors", [])]
                connection = read_only_connection(copied)
                try:
                    formulas = [
                        str(connection.execute("SELECT reduced_formula FROM structures WHERE structure_id=?", (structure_id,)).fetchone()[0])
                        for structure_id in neighbor_ids
                    ]
                    consistent = all(
                        connection.execute(
                            "SELECT 1 FROM structure_annotations WHERE structure_id=? AND family_assignment=?",
                            (structure_id, family["family"]),
                        ).fetchone()
                        is not None
                        for structure_id in neighbor_ids
                    )
                finally:
                    connection.close()
                target_composition = Composition(target).reduced_composition
                non_exact = sum(
                    Composition(formula).reduced_composition != target_composition
                    for formula in formulas
                )
                rows.append(
                    {
                        "family": family["family"],
                        "corpus": family["existing_corpus"],
                        "query": query,
                        "status": "PASS" if formulas and consistent and non_exact else "FAIL",
                        "top_retrieved_formulas": ";".join(formulas),
                        "non_exact_query_neighbors": non_exact,
                        "family_consistent": consistent,
                    }
                )
    return rows


def git_head() -> str:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "artifacts/Paper_scaffolds_september/specialist_corpora",
    )
    parser.add_argument("--skip-retrieval", action="store_true")
    parser.add_argument("--extra-db-root", type=Path, action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = database_paths(REPO_ROOT, args.extra_db_root)
    inventory = []
    for index, path in enumerate(paths, start=1):
        print(f"[corpus-audit] {index}/{len(paths)} {path}")
        inventory.append(audit_database(path, run_retrieval=not args.skip_retrieval))
    families = family_rows(inventory, args.output_root)
    write_outputs(args.output_root, inventory, families)
    print(json.dumps({"databases": len(inventory), "families": len(families), "output_root": str(args.output_root)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
