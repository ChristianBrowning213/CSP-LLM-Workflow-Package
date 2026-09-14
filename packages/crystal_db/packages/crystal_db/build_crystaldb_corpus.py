"""Build documented Crystal-DB retrieval corpora.

This is the reusable corpus-builder for paper-scale retrieval datasets. It
orchestrates acquisition, manifest/dataset-card generation, optional indexing
steps, and combined provenance-preserving views without printing API keys or
falling back to hash embeddings when LM Studio embeddings are requested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crystal_db.crystalcard import build_crystalcard  # noqa: E402
from crystal_db.db import connect, init_db  # noqa: E402
from crystal_db.embeddings import LMSTUDIO_MODEL_NAME, LMSTUDIO_MODEL_VERSION  # noqa: E402
from crystal_db.fingerprint import fingerprint_structure  # noqa: E402
from crystal_db.ingest_folder import ingest_folder  # noqa: E402
from crystal_db.retrieval import similar_hybrid, similar_struct, text_search  # noqa: E402
from crystal_db.sequence_index import embed_sequences, encode_sequences  # noqa: E402
from crystal_db.text_index import embed_text_docs, generate_text_docs  # noqa: E402
from crystal_db.utils import parse_cif_text, parse_formula  # noqa: E402

STATUS_OK = "OK"
STATUS_MISSING = "MISSING"
STATUS_ERROR = "ERROR"
STATUS_BLOCKED = "BLOCKED"
MANIFEST_FIELDS = [
    "dataset_id",
    "source_corpus_id",
    "formula",
    "reduced_formula",
    "source",
    "material_id",
    "source_query",
    "source_query_name",
    "family_label",
    "label_source",
    "status",
    "cif_path",
    "cif_sha256",
    "formula_pretty",
    "chemical_system",
    "anonymous_formula",
    "space_group",
    "energy_above_hull",
    "formation_energy_per_atom",
    "is_stable",
    "retrieved_at",
    "error_text",
]
DATASET_CARD_REQUIRED_FIELDS = [
    "dataset_id",
    "purpose",
    "source",
    "acquisition_date",
    "source_queries",
    "formula_anchors",
    "chemical_systems",
    "family_labels",
    "label_sources",
    "structure_count",
    "cif_count",
    "crystalcard_count",
    "fingerprint_count",
    "text_doc_count",
    "embedding_count",
    "embedding_model",
    "sequence_count",
    "policy_export_status",
    "limitations",
    "known_bias_introduced_by_query_design",
    "corpus_role",
]


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_mp_api_key(repo_root: Path = REPO_ROOT) -> str | None:
    for name in ("MP_API_KEY", "MP-API-KEY", "MATERIALS_PROJECT_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value.strip()
    env_values = parse_env_file(repo_root / ".env")
    for name in ("MP_API_KEY", "MP-API-KEY", "MATERIALS_PROJECT_API_KEY"):
        value = env_values.get(name)
        if value:
            return value.strip()
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._") or "structure"


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(value if value is not None else "").replace("\n", " ") for value in row) + " |")
    return "\n".join(lines)


def formula_to_chemsys(formula: str | None) -> str | None:
    counts = parse_formula(formula)
    if not counts:
        return None
    return "-".join(sorted(counts))


def anonymous_formula(formula: str | None) -> str | None:
    counts = parse_formula(formula)
    if not counts:
        return None
    amounts = sorted(counts.values())
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(f"{letters[idx]}{amount if amount != 1 else ''}" for idx, amount in enumerate(amounts))


def normalize_manifest_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field: json_safe(row.get(field)) for field in MANIFEST_FIELDS}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(normalize_manifest_row(row), sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_dirs(dataset_dir: Path) -> Path:
    cif_dir = dataset_dir / "cifs"
    cif_dir.mkdir(parents=True, exist_ok=True)
    return cif_dir


def row_for_cif(
    *,
    dataset_id: str,
    cif_path: Path,
    source: str,
    source_query: dict[str, Any],
    source_query_name: str | None,
    family_label: str | None,
    label_source: str | None,
    source_corpus_id: str | None = None,
) -> dict[str, Any]:
    text = cif_path.read_text(encoding="utf-8")
    parsed = parse_cif_text(text)
    formula = parsed.get("formula")
    return {
        "dataset_id": dataset_id,
        "source_corpus_id": source_corpus_id,
        "formula": formula,
        "reduced_formula": formula,
        "source": source,
        "material_id": None,
        "source_query": source_query,
        "source_query_name": source_query_name,
        "family_label": family_label,
        "label_source": label_source,
        "status": STATUS_OK,
        "cif_path": str(cif_path),
        "cif_sha256": sha256_file(cif_path),
        "formula_pretty": formula,
        "chemical_system": formula_to_chemsys(formula),
        "anonymous_formula": anonymous_formula(formula),
        "space_group": parsed.get("space_group"),
        "energy_above_hull": None,
        "formation_energy_per_atom": None,
        "is_stable": None,
        "retrieved_at": now_iso(),
        "error_text": None,
    }


def doc_value(doc: Any, name: str, default: Any = None) -> Any:
    if doc is None:
        return default
    if isinstance(doc, dict):
        return doc.get(name, default)
    return getattr(doc, name, default)


def symmetry_value(doc: Any) -> str | None:
    sym = doc_value(doc, "symmetry")
    if isinstance(sym, dict):
        return sym.get("symbol") or sym.get("crystal_system")
    if sym is not None:
        return getattr(sym, "symbol", None) or getattr(sym, "crystal_system", None)
    return None


def row_for_mp_doc(
    *,
    dataset_id: str,
    doc: Any | None,
    source_query: dict[str, Any],
    source_query_name: str | None,
    family_label: str | None,
    label_source: str | None,
    status: str,
    cif_path: Path | None = None,
    cif_sha256: str | None = None,
    error_text: str | None = None,
) -> dict[str, Any]:
    formula = doc_value(doc, "formula_pretty")
    chemsys = doc_value(doc, "chemsys") or formula_to_chemsys(formula)
    return {
        "dataset_id": dataset_id,
        "source_corpus_id": None,
        "formula": formula,
        "reduced_formula": formula,
        "source": "materials_project",
        "material_id": str(doc_value(doc, "material_id")) if doc_value(doc, "material_id") is not None else None,
        "source_query": source_query,
        "source_query_name": source_query_name,
        "family_label": family_label,
        "label_source": label_source,
        "status": status,
        "cif_path": str(cif_path) if cif_path else None,
        "cif_sha256": cif_sha256,
        "formula_pretty": formula,
        "chemical_system": chemsys,
        "anonymous_formula": doc_value(doc, "anonymous_formula") or anonymous_formula(formula),
        "space_group": symmetry_value(doc),
        "energy_above_hull": doc_value(doc, "energy_above_hull"),
        "formation_energy_per_atom": doc_value(doc, "formation_energy_per_atom"),
        "is_stable": doc_value(doc, "is_stable"),
        "retrieved_at": now_iso(),
        "error_text": error_text,
    }


def mp_summary_search(mpr: Any, **kwargs: Any) -> list[Any]:
    fields = [
        "material_id",
        "formula_pretty",
        "chemsys",
        "symmetry",
        "energy_above_hull",
        "formation_energy_per_atom",
        "is_stable",
    ]
    try:
        return list(mpr.materials.summary.search(fields=fields, **kwargs))
    except TypeError:
        return list(mpr.materials.summary.search(**kwargs))


def sort_mp_docs(docs: list[Any]) -> list[Any]:
    def key(doc: Any) -> tuple[int, float, str]:
        stable_rank = 0 if doc_value(doc, "is_stable") is True else 1
        try:
            hull = float(doc_value(doc, "energy_above_hull", 999999.0))
        except (TypeError, ValueError):
            hull = 999999.0
        return stable_rank, hull, str(doc_value(doc, "material_id", ""))

    return sorted(docs, key=key)


def write_mp_cif(mpr: Any, doc: Any, cif_dir: Path) -> tuple[Path, str]:
    from pymatgen.io.cif import CifWriter

    material_id = str(doc_value(doc, "material_id"))
    structure = mpr.get_structure_by_material_id(material_id)
    cif_text = str(CifWriter(structure))
    cif_path = cif_dir / f"{safe_filename(material_id)}.cif"
    cif_path.write_text(cif_text, encoding="utf-8")
    return cif_path, sha256_text(cif_text)


def query_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if args.stable_only and not args.include_unstable:
        kwargs["is_stable"] = True
    if args.energy_above_hull_max is not None and not args.include_unstable:
        kwargs["energy_above_hull"] = (0, args.energy_above_hull_max)
    return kwargs


def acquire_materials_project(args: argparse.Namespace, dataset_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_queries: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    cif_dir = make_dirs(dataset_dir)
    base_kwargs = query_kwargs_from_args(args)

    def record_blocked(query: dict[str, Any], error: str) -> None:
        source_queries.append(query)
        rows.append(
            row_for_mp_doc(
                dataset_id=args.dataset_id,
                doc=None,
                source_query=query,
                source_query_name=args.source_query_name,
                family_label=args.family_label,
                label_source="user_cli" if args.family_label else None,
                status=STATUS_BLOCKED,
                error_text=error,
            )
        )

    if args.formulas and not args.target_only and not args.expand_around_formulas and not args.chemical_systems and not args.anonymous_formulas and not args.material_ids:
        record_blocked(
            {"formulas": args.formulas, "mode": "formula_anchors_without_expansion"},
            "Formula anchors are targets, not a retrieval-scale corpus. Use --expand-around-formulas, add retrieval queries, or pass --target-only explicitly.",
        )
        return rows, source_queries

    planned_queries = build_mp_queries(args, base_kwargs)
    source_queries.extend(planned_queries)
    if args.dry_run:
        return rows, source_queries

    api_key = load_mp_api_key()
    if not api_key:
        for query in planned_queries or [{"source": "materials_project"}]:
            rows.append(
                row_for_mp_doc(
                    dataset_id=args.dataset_id,
                    doc=None,
                    source_query=query,
                    source_query_name=args.source_query_name,
                    family_label=args.family_label,
                    label_source="user_cli" if args.family_label else None,
                    status=STATUS_BLOCKED,
                    error_text="missing_mp_api_key",
                )
            )
        return rows, source_queries

    from mp_api.client import MPRester

    with MPRester(api_key) as mpr:
        seen: set[str] = set()
        for query in planned_queries:
            try:
                docs = sort_mp_docs(mp_summary_search(mpr, **query["mp_kwargs"]))
                if not docs:
                    rows.append(
                        row_for_mp_doc(
                            dataset_id=args.dataset_id,
                            doc=None,
                            source_query=query,
                            source_query_name=args.source_query_name,
                            family_label=args.family_label,
                            label_source="user_cli" if args.family_label else None,
                            status=STATUS_MISSING,
                            error_text="no_materials_project_summary_match",
                        )
                    )
                    continue
                for doc in docs[: query["limit"]]:
                    material_id = str(doc_value(doc, "material_id"))
                    if material_id in seen:
                        continue
                    seen.add(material_id)
                    try:
                        cif_path, cif_hash = write_mp_cif(mpr, doc, cif_dir)
                        rows.append(
                            row_for_mp_doc(
                                dataset_id=args.dataset_id,
                                doc=doc,
                                source_query=query,
                                source_query_name=args.source_query_name,
                                family_label=args.family_label,
                                label_source="user_cli" if args.family_label else None,
                                status=STATUS_OK,
                                cif_path=cif_path,
                                cif_sha256=cif_hash,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        rows.append(
                            row_for_mp_doc(
                                dataset_id=args.dataset_id,
                                doc=doc,
                                source_query=query,
                                source_query_name=args.source_query_name,
                                family_label=args.family_label,
                                label_source="user_cli" if args.family_label else None,
                                status=STATUS_ERROR,
                                error_text=f"{type(exc).__name__}: {exc}",
                            )
                        )
                    if args.max_structures and len([row for row in rows if row["status"] == STATUS_OK]) >= args.max_structures:
                        return rows, source_queries
                    time.sleep(0.05)
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    row_for_mp_doc(
                        dataset_id=args.dataset_id,
                        doc=None,
                        source_query=query,
                        source_query_name=args.source_query_name,
                        family_label=args.family_label,
                        label_source="user_cli" if args.family_label else None,
                        status=STATUS_ERROR,
                        error_text=f"{type(exc).__name__}: {exc}",
                    )
                )
    return rows, source_queries


def build_mp_queries(args: argparse.Namespace, base_kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    overall_remaining = args.max_structures or 0

    def limit(default: int) -> int:
        nonlocal overall_remaining
        value = default
        if overall_remaining:
            value = min(value, overall_remaining)
            overall_remaining = max(0, overall_remaining - value)
        return max(1, value)

    if args.material_ids:
        queries.append(
            {
                "query_type": "material_ids",
                "mp_kwargs": {"material_ids": args.material_ids, **base_kwargs},
                "limit": limit(len(args.material_ids)),
            }
        )
    if args.target_only and args.formulas:
        for formula in args.formulas:
            queries.append(
                {
                    "query_type": "exact_formula_target_only",
                    "formula_anchor": formula,
                    "mp_kwargs": {"formula": formula, **base_kwargs},
                    "limit": limit(args.max_structures_per_formula or 1),
                }
            )
    elif args.expand_around_formulas and args.formulas:
        for formula in args.formulas:
            if args.expansion_mode == "same_chemsys":
                kwargs = {"chemsys": formula_to_chemsys(formula), **base_kwargs}
            elif args.expansion_mode == "same_anonymous_formula":
                kwargs = {"anonymous_formula": anonymous_formula(formula), **base_kwargs}
            elif args.expansion_mode == "similar_formula":
                kwargs = {"formula": formula, **base_kwargs}
            else:
                kwargs = {"chemsys": formula_to_chemsys(formula), **base_kwargs}
            queries.append(
                {
                    "query_type": f"formula_expansion:{args.expansion_mode}",
                    "formula_anchor": formula,
                    "mp_kwargs": {key: value for key, value in kwargs.items() if value is not None},
                    "limit": limit(args.max_structures_per_formula or 100),
                }
            )
    for system in args.chemical_systems or []:
        queries.append(
            {
                "query_type": "chemical_system",
                "chemical_system": system,
                "mp_kwargs": {"chemsys": system, **base_kwargs},
                "limit": limit(args.max_structures_per_system or 250),
            }
        )
    for anon in args.anonymous_formulas or []:
        queries.append(
            {
                "query_type": "anonymous_formula",
                "anonymous_formula": anon,
                "mp_kwargs": {"anonymous_formula": anon, **base_kwargs},
                "limit": limit(args.max_structures_per_system or 250),
            }
        )
    return queries


def acquire_local_cifs(args: argparse.Namespace, dataset_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not args.cif_dir:
        raise ValueError("--cif-dir is required for --source local_cif")
    source_dir = Path(args.cif_dir)
    source_query = {"cif_dir": str(source_dir), "mode": "local_cif_folder"}
    if not source_dir.is_dir():
        row = {
            "dataset_id": args.dataset_id,
            "source": "local_cif",
            "source_query": source_query,
            "source_query_name": args.source_query_name,
            "family_label": args.family_label,
            "label_source": "user_cli" if args.family_label else None,
            "status": STATUS_MISSING,
            "retrieved_at": now_iso(),
            "error_text": "cif_dir_not_found",
        }
        return [row], [source_query]
    rows: list[dict[str, Any]] = []
    cif_dir = make_dirs(dataset_dir)
    cif_paths = sorted(source_dir.rglob("*.cif"))
    if args.max_structures:
        cif_paths = cif_paths[: args.max_structures]
    for source_path in cif_paths:
        dest = cif_dir / source_path.name
        if not args.dry_run:
            if dest.exists() and not args.force:
                raise FileExistsError(f"{dest} exists; use --force to overwrite")
            shutil.copy2(source_path, dest)
        row_path = dest if not args.dry_run else source_path
        rows.append(
            row_for_cif(
                dataset_id=args.dataset_id,
                cif_path=row_path,
                source="local_cif",
                source_query=source_query,
                source_query_name=args.source_query_name,
                family_label=args.family_label,
                label_source="user_cli" if args.family_label else None,
            )
        )
    if not rows:
        rows.append(
            {
                "dataset_id": args.dataset_id,
                "source": "local_cif",
                "source_query": source_query,
                "source_query_name": args.source_query_name,
                "family_label": args.family_label,
                "label_source": "user_cli" if args.family_label else None,
                "status": STATUS_MISSING,
                "retrieved_at": now_iso(),
                "error_text": "no_cif_files_found",
            }
        )
    return rows, [source_query]


def acquire_combined_view(args: argparse.Namespace, dataset_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifests = [Path(item) for item in (args.source_manifests or [])]
    source_query = {"manifests": [str(path) for path in manifests], "mode": "combined_view"}
    rows: list[dict[str, Any]] = []
    for manifest in manifests:
        source_rows = read_jsonl(manifest)
        source_corpus_id = None
        for source_row in source_rows:
            source_corpus_id = source_corpus_id or source_row.get("dataset_id")
            combined = dict(source_row)
            combined["dataset_id"] = args.dataset_id
            combined["source_corpus_id"] = source_row.get("dataset_id") or source_corpus_id
            combined["source_query"] = source_row.get("source_query") or {}
            combined["source_query_name"] = source_row.get("source_query_name") or args.source_query_name
            rows.append(combined)
    if not rows:
        rows.append(
            {
                "dataset_id": args.dataset_id,
                "source_corpus_id": None,
                "source": "combined_view",
                "source_query": source_query,
                "source_query_name": args.source_query_name,
                "status": STATUS_BLOCKED,
                "retrieved_at": now_iso(),
                "error_text": "No source manifests were provided or manifests had no rows.",
            }
        )
    if not args.dry_run and args.source_dbs:
        build_combined_db(args.out_db, [Path(item) for item in args.source_dbs])
    return rows, [source_query]


def build_combined_db(out_db: str, source_dbs: list[Path]) -> None:
    out_path = Path(out_db)
    if out_path.exists():
        out_path.unlink()
    conn = connect(str(out_path))
    init_db(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS corpus_membership ("
        "structure_id TEXT, source_corpus_id TEXT, source_db TEXT, original_structure_id TEXT, "
        "PRIMARY KEY (structure_id, source_corpus_id, original_structure_id))"
    )
    for source_db in source_dbs:
        source_conn = sqlite3.connect(source_db)
        source_conn.row_factory = sqlite3.Row
        source_corpus_id = source_db.stem
        ids = [row["structure_id"] for row in source_conn.execute("SELECT structure_id FROM structures ORDER BY structure_id")]
        for sid in ids:
            new_sid = f"{safe_filename(source_corpus_id)}::{sid}"
            copy_structure_rows(source_conn, conn, sid, new_sid)
            conn.execute(
                "INSERT OR REPLACE INTO corpus_membership (structure_id, source_corpus_id, source_db, original_structure_id) VALUES (?, ?, ?, ?)",
                (new_sid, source_corpus_id, str(source_db), sid),
            )
        source_conn.close()
    conn.commit()
    conn.close()


def copy_structure_rows(source_conn: sqlite3.Connection, dest_conn: sqlite3.Connection, sid: str, new_sid: str) -> None:
    tables = {
        "structures": "structure_id,cif_text,reduced_formula,nsites,volume,license_restricted",
        "metadata": "structure_id,formula,elements_csv,space_group,band_gap_eV",
        "provenance": "structure_id,source,source_id,retrieved_at,license_notes,policy_id,allow_cif_store,allow_cif_return,allow_derivatives,allow_export",
        "structure_fingerprints": "structure_id,fingerprint_method,fingerprint_version,vector_json,feature_names_json,input_hash,generated_at",
        "structure_crystalcards": "structure_id,engine,version,card_json,input_hash,generated_at",
        "structure_sequences": "structure_id,format,seq_text,input_hash,generated_at",
        "structure_embeddings": "structure_id,modality,model_name,model_version,vector_json,dim,input_hash,generated_at",
    }
    for table, columns_csv in tables.items():
        columns = columns_csv.split(",")
        try:
            rows = source_conn.execute(f"SELECT {columns_csv} FROM {table} WHERE structure_id = ?", (sid,)).fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            values = [row[column] for column in columns]
            values[0] = new_sid
            placeholders = ",".join(["?"] * len(values))
            dest_conn.execute(f"INSERT OR REPLACE INTO {table} ({columns_csv}) VALUES ({placeholders})", values)
    try:
        text_docs = source_conn.execute(
            "SELECT id, structure_id, engine, text_view, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at "
            "FROM text_docs WHERE structure_id = ?",
            (sid,),
        ).fetchall()
    except sqlite3.Error:
        text_docs = []
    doc_id_map: dict[int, int] = {}
    for row in text_docs:
        cursor = dest_conn.execute(
            "INSERT INTO text_docs (structure_id, engine, text_view, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_sid, row["engine"], row["text_view"], row["engine_version"], row["text"], row["text_sha256"], row["status"], row["error_type"], row["error_message"], row["created_at"], row["updated_at"]),
        )
        doc_id_map[int(row["id"])] = int(cursor.lastrowid)
    for old_id, new_id in doc_id_map.items():
        try:
            emb_rows = source_conn.execute(
                "SELECT embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at FROM text_embeddings WHERE text_doc_id = ?",
                (old_id,),
            ).fetchall()
        except sqlite3.Error:
            continue
        for row in emb_rows:
            dest_conn.execute(
                "INSERT INTO text_embeddings (text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id, row["embed_engine"], row["model"], row["model_version"], row["dim"], row["vector"], row["status"], row["error_type"], row["error_message"], row["created_at"], row["updated_at"]),
            )


def structure_ids(db_path: Path) -> list[str]:
    conn = connect(str(db_path))
    init_db(conn)
    rows = conn.execute("SELECT structure_id FROM structures ORDER BY structure_id").fetchall()
    conn.close()
    return [row["structure_id"] for row in rows]


def count_table(db_path: Path, table: str, where: str = "") -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        suffix = f" WHERE {where}" if where else ""
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}{suffix}").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def lmstudio_available() -> bool:
    base_url = os.getenv("CRYSTALDB_EMBED_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
    try:
        with urllib.request.urlopen(base_url + "/models", timeout=2) as response:
            return 200 <= int(response.status) < 500
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return False


def ingest_and_index(args: argparse.Namespace, dataset_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "dataset_id": args.dataset_id,
        "db_path": str(Path(args.out_db)),
        "dry_run": bool(args.dry_run),
        "ingest": {"status": "skipped_dry_run" if args.dry_run else "not_started"},
        "fingerprints": {"status": "skipped"},
        "crystalcards": {"status": "skipped"},
        "text_docs": {"status": "skipped"},
        "text_embeddings": {"status": "skipped"},
        "sequences": {"status": "skipped"},
        "retrieval_smoke": {"status": "skipped"},
    }
    if args.dry_run or args.source == "combined_view":
        return summary
    ok_rows = [row for row in rows if row.get("status") == STATUS_OK]
    if not ok_rows:
        summary["ingest"] = {"status": "skipped_empty_dataset"}
        return summary
    out_db = Path(args.out_db)
    if out_db.exists():
        if not args.force:
            raise FileExistsError(f"{out_db} exists; use --force to rebuild")
        out_db.unlink()
    result = ingest_folder(
        db_path=str(out_db),
        folder_path=str(dataset_dir / "cifs"),
        source=args.source,
        policy_name="local_cif",
    )
    summary["ingest"] = {"status": "ok", **result}
    ids = structure_ids(out_db)
    if args.make_fingerprints:
        ok = 0
        for sid in ids:
            fp = fingerprint_structure(structure_id=sid, db_path=str(out_db), store=True)
            ok += 0 if "error" in fp else 1
        summary["fingerprints"] = {"status": "ok", "ok": ok, "total": len(ids)}
    if args.make_crystalcards:
        ok = 0
        for sid in ids:
            card = build_crystalcard(structure_id=sid, db_path=str(out_db), engine="baseline", store=True)
            ok += 0 if "error" in card else 1
        summary["crystalcards"] = {"status": "ok", "ok": ok, "total": len(ids)}
    if args.make_crystalcards or args.make_text_embeddings:
        try:
            summary["text_docs"] = {
                "status": "ok",
                **generate_text_docs(db_path=str(out_db), engine="baseline", text_view="robocrys", batch=32, progress_every=1000),
            }
        except Exception as exc:  # noqa: BLE001
            summary["text_docs"] = {"status": "error", "error_text": f"{type(exc).__name__}: {exc}"}
    if args.make_text_embeddings:
        if not lmstudio_available():
            summary["text_embeddings"] = {"status": "unavailable", "error_text": "LM Studio embeddings endpoint unavailable"}
            if args.require_embeddings:
                raise RuntimeError("LM Studio embeddings endpoint unavailable and --require-embeddings was set")
        else:
            summary["text_embeddings"] = {
                "status": "ok",
                **embed_text_docs(
                    db_path=str(out_db),
                    text_engine="baseline",
                    text_view="robocrys",
                    embed_engine="lmstudio",
                    model_name=LMSTUDIO_MODEL_NAME,
                    model_version=LMSTUDIO_MODEL_VERSION,
                    batch=8,
                    progress_every=1000,
                ),
            }
    if args.make_sequences:
        try:
            enc = encode_sequences(db_path=str(out_db), format="cif_canon")
            emb = {"processed": 0}
            if args.make_text_embeddings and lmstudio_available():
                emb = embed_sequences(db_path=str(out_db), format="cif_canon", model_name=LMSTUDIO_MODEL_NAME, model_version=LMSTUDIO_MODEL_VERSION)
            summary["sequences"] = {"status": "ok", "encoded": enc.get("processed"), "embedded": emb.get("processed")}
        except Exception as exc:  # noqa: BLE001
            summary["sequences"] = {"status": "error", "error_text": f"{type(exc).__name__}: {exc}"}
    if args.retrieval_smoke:
        summary["retrieval_smoke"] = run_retrieval_smoke(out_db, rows)
    summary["db_counts"] = db_counts(out_db)
    return summary


def db_counts(db_path: Path) -> dict[str, int]:
    return {
        "structures": count_table(db_path, "structures"),
        "fingerprints": count_table(db_path, "structure_fingerprints"),
        "crystalcards": count_table(db_path, "structure_crystalcards"),
        "text_docs": count_table(db_path, "text_docs", "status = 'OK'"),
        "text_embeddings": count_table(db_path, "text_embeddings", "status = 'OK'"),
        "sequences": count_table(db_path, "structure_sequences"),
    }


def run_retrieval_smoke(db_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ids = structure_ids(db_path)
    result: dict[str, Any] = {
        "status": "ok",
        "queries": [],
        "modes_available": {"exact_formula": bool(ids), "text": False, "structural": False, "hybrid": False},
    }
    formulas = [row.get("formula") or row.get("formula_pretty") for row in rows if row.get("status") == STATUS_OK]
    natural_queries = [
        "rocksalt oxide",
        "halide perovskite",
        "layered lithium transition metal oxide",
    ]
    if formulas:
        natural_queries = list(dict.fromkeys([str(item) for item in formulas[:3]] + natural_queries + ["organic molecular crystal"]))
    conn = connect(str(db_path))
    init_db(conn)
    text_count = int(conn.execute("SELECT COUNT(*) FROM text_embeddings WHERE status = 'OK'").fetchone()[0])
    fp_count = int(conn.execute("SELECT COUNT(*) FROM structure_fingerprints").fetchone()[0])
    conn.close()
    if ids and fp_count:
        result["modes_available"]["structural"] = True
        result["queries"].append({"mode": "structural", "query": ids[0], "result": similar_struct(structure_id=ids[0], db_path=str(db_path), k=3)})
    if ids and text_count:
        result["modes_available"]["text"] = True
        result["modes_available"]["hybrid"] = bool(fp_count)
        for query in natural_queries[:7]:
            result["queries"].append(
                {
                    "mode": "text",
                    "query": query,
                    "result": text_search(
                        query_text=query,
                        db_path=str(db_path),
                        k=3,
                        embed_engine="lmstudio",
                        model_name=LMSTUDIO_MODEL_NAME,
                        model_version=LMSTUDIO_MODEL_VERSION,
                        text_engine="baseline",
                        text_view="robocrys",
                        show_text_top=0,
                    ),
                }
            )
        if fp_count:
            result["queries"].append({"mode": "hybrid", "query": ids[0], "result": similar_hybrid(structure_id=ids[0], db_path=str(db_path), k=3, sources=["text", "struct", "seq"])})
    else:
        result["queries"].append({"mode": "text", "query": natural_queries[0], "status": "skipped_no_embeddings"})
    return result


def create_dataset_card(args: argparse.Namespace, rows: list[dict[str, Any]], source_queries: list[dict[str, Any]], indexing: dict[str, Any]) -> dict[str, Any]:
    counts = indexing.get("db_counts") or {}
    ok_rows = [row for row in rows if row.get("status") == STATUS_OK]
    family_labels = sorted({row.get("family_label") for row in rows if row.get("family_label")})
    label_sources = sorted({row.get("label_source") for row in rows if row.get("label_source")})
    corpus_role = "target-only" if args.target_only else ("combined-view" if args.source == "combined_view" else "retrieval-scale")
    card = {
        "dataset_id": args.dataset_id,
        "purpose": args.purpose or "Crystal-DB retrieval corpus",
        "source": args.source,
        "acquisition_date": now_iso(),
        "source_queries": source_queries,
        "formula_anchors": args.formulas or [],
        "chemical_systems": args.chemical_systems or [],
        "family_labels": family_labels,
        "label_sources": label_sources,
        "structure_count": counts.get("structures", len(ok_rows)),
        "cif_count": len([row for row in ok_rows if row.get("cif_path")]),
        "crystalcard_count": counts.get("crystalcards", 0),
        "fingerprint_count": counts.get("fingerprints", 0),
        "text_doc_count": counts.get("text_docs", 0),
        "embedding_count": counts.get("text_embeddings", 0),
        "embedding_model": LMSTUDIO_MODEL_NAME if args.make_text_embeddings else None,
        "sequence_count": counts.get("sequences", 0),
        "policy_export_status": "local_cif_policy_blocks_export_by_default",
        "limitations": [
            "Query design controls corpus coverage and can bias retrieval results.",
            "MP prototype and anonymous-formula support depends on mp-api search capabilities.",
            "CrystalCard text uses baseline generation unless robocrys text generation is run separately.",
        ],
        "known_bias_introduced_by_query_design": "Anchor and chemical-system expansions over-represent chosen families relative to all MP structures.",
        "corpus_role": corpus_role,
        "status_counts": {status: len([row for row in rows if row.get("status") == status]) for status in (STATUS_OK, STATUS_MISSING, STATUS_ERROR, STATUS_BLOCKED)},
        "out_db": str(Path(args.out_db)),
        "out_root": str(Path(args.out_root)),
    }
    for field in DATASET_CARD_REQUIRED_FIELDS:
        card.setdefault(field, None)
    return card


def write_markdown_artifacts(dataset_dir: Path, card: dict[str, Any], indexing: dict[str, Any], smoke: dict[str, Any], source_queries: list[dict[str, Any]]) -> None:
    card_md = "\n\n".join(
        [
            f"# {card['dataset_id']}",
            f"Purpose: {card.get('purpose')}",
            f"Role: `{card.get('corpus_role')}`",
            "## Counts",
            markdown_table(
                ["structures", "CIFs", "CrystalCards", "fingerprints", "text docs", "embeddings", "sequences"],
                [[card.get("structure_count"), card.get("cif_count"), card.get("crystalcard_count"), card.get("fingerprint_count"), card.get("text_doc_count"), card.get("embedding_count"), card.get("sequence_count")]],
            ),
            "## Limitations",
            "\n".join(f"- {item}" for item in card.get("limitations", [])),
        ]
    )
    (dataset_dir / "dataset_card.md").write_text(card_md + "\n", encoding="utf-8")
    (dataset_dir / "indexing_summary.md").write_text("# Indexing Summary\n\n```json\n" + json.dumps(indexing, indent=2, sort_keys=True) + "\n```\n", encoding="utf-8")
    (dataset_dir / "retrieval_smoke.md").write_text("# Retrieval Smoke\n\n```json\n" + json.dumps(smoke, indent=2, sort_keys=True) + "\n```\n", encoding="utf-8")
    (dataset_dir / "source_queries.md").write_text("# Source Queries\n\n```json\n" + json.dumps(source_queries, indent=2, sort_keys=True) + "\n```\n", encoding="utf-8")


def build_corpus(args: argparse.Namespace) -> dict[str, Any]:
    dataset_dir = Path(args.out_root) / args.dataset_id
    if dataset_dir.exists() and args.force and not args.dry_run:
        shutil.rmtree(dataset_dir)
    make_dirs(dataset_dir)
    if args.source == "local_cif":
        rows, source_queries = acquire_local_cifs(args, dataset_dir)
    elif args.source == "materials_project":
        rows, source_queries = acquire_materials_project(args, dataset_dir)
    elif args.source == "combined_view":
        rows, source_queries = acquire_combined_view(args, dataset_dir)
    else:
        raise ValueError(f"unsupported source: {args.source}")
    write_jsonl(dataset_dir / "manifest.jsonl", rows)
    write_json(dataset_dir / "source_queries.json", {"dataset_id": args.dataset_id, "source_queries": source_queries})
    indexing = ingest_and_index(args, dataset_dir, rows)
    smoke = indexing.get("retrieval_smoke") or {"status": "skipped"}
    write_json(dataset_dir / "indexing_summary.json", indexing)
    write_json(dataset_dir / "retrieval_smoke.json", smoke)
    card = create_dataset_card(args, rows, source_queries, indexing)
    write_json(dataset_dir / "dataset_card.json", card)
    write_markdown_artifacts(dataset_dir, card, indexing, smoke, source_queries)
    return {"dataset_id": args.dataset_id, "dataset_dir": str(dataset_dir), "out_db": str(Path(args.out_db)), "status_counts": card["status_counts"]}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--out-db", required=True)
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "result_datasets"))
    parser.add_argument("--source", choices=["local_cif", "materials_project", "combined_view"], required=True)
    parser.add_argument("--cif-dir")
    parser.add_argument("--formulas", nargs="+")
    parser.add_argument("--material-ids", nargs="+")
    parser.add_argument("--chemical-systems", nargs="+")
    parser.add_argument("--anonymous-formulas", nargs="+")
    parser.add_argument("--family-label")
    parser.add_argument("--source-query-name")
    parser.add_argument("--purpose")
    parser.add_argument("--max-structures", type=int)
    parser.add_argument("--max-structures-per-formula", type=int)
    parser.add_argument("--max-structures-per-system", type=int)
    parser.add_argument("--stable-only", action="store_true")
    parser.add_argument("--energy-above-hull-max", type=float)
    parser.add_argument("--include-unstable", action="store_true")
    parser.add_argument("--expand-around-formulas", action="store_true")
    parser.add_argument("--expansion-mode", choices=["same_chemsys", "same_anonymous_formula", "same_family", "similar_formula"], default="same_chemsys")
    parser.add_argument("--make-crystalcards", action="store_true")
    parser.add_argument("--make-fingerprints", action="store_true")
    parser.add_argument("--make-text-embeddings", action="store_true")
    parser.add_argument("--make-sequences", action="store_true")
    parser.add_argument("--retrieval-smoke", action="store_true")
    parser.add_argument("--require-embeddings", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--target-only", action="store_true")
    parser.add_argument("--source-manifests", nargs="+")
    parser.add_argument("--source-dbs", nargs="+")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_corpus(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
