"""Build small documented Materials Project result datasets.

The script keeps acquisition targeted and reproducible. It never prints or writes
the Materials Project API key.
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
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations_with_replacement
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
from crystal_db.retrieval import text_search  # noqa: E402
from crystal_db.sequence_index import embed_sequences, encode_sequences  # noqa: E402
from crystal_db.similarity import similar_structures  # noqa: E402
from crystal_db.text_index import embed_text_docs, generate_text_docs  # noqa: E402
from crystal_db.utils import now_iso_utc  # noqa: E402

SOURCE_LICENSE_NOTES = (
    "Materials Project derived CIF retrieved for local experimental indexing; "
    "check Materials Project terms before redistribution/export."
)

POT_ROOTS = [
    Path(r"C:\Users\brown\Downloads\SPP\SPP\SPP\SPP"),
    Path(r"C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP\QLIP_Outputs\SPP\runs"),
]

DATASET_DBS = {
    "common_families": "result_common_families.db",
    "hard_intent": "result_hard_intent.db",
    "halide_perovskite": "result_halide_perovskite.db",
    "kagome_optional": "result_kagome.db",
}

COMMON_TARGETS = [
    ("NiO", "rocksalt AX"),
    ("TiN", "rocksalt AX"),
    ("MgO", "rocksalt AX"),
    ("CeO2", "fluorite AX2"),
    ("ZrO2", "fluorite AX2"),
    ("ThO2", "fluorite AX2"),
    ("CsPbBr3", "halide perovskite ABX3"),
    ("CsSnBr3", "halide perovskite ABX3"),
    ("CsPbCl3", "halide perovskite ABX3"),
    ("ZnFe2O4", "spinel AB2O4"),
    ("MgAl2O4", "spinel AB2O4"),
    ("CoFe2O4", "spinel AB2O4"),
]

HARD_TARGETS = [
    ("CoAs2", "safflorite-like arsenide"),
    ("Li6PS5Cl", "argyrodite"),
    ("LiFePO4", "olivine phosphate"),
    ("LiCoO2", "layered oxide"),
]

HARD_OPTIONAL = [
    ("Cs2HgBr4", "low-symmetry inorganic halide candidate"),
]

HALIDE_CORE = [
    ("CsPbBr3", "halide perovskite core"),
    ("CsSnBr3", "halide perovskite core"),
    ("CsPbCl3", "halide perovskite core"),
]

HALIDE_OPTIONAL = [
    ("CsPbI3", "halide perovskite optional"),
    ("CsSnI3", "halide perovskite optional"),
    ("CsGeBr3", "halide perovskite optional"),
    ("RbPbBr3", "halide perovskite optional"),
    ("KPbBr3", "halide perovskite optional"),
]

SCAFFOLD_SUPPORTED = {
    "NiO": "fixed_orbit_supported",
    "TiN": "fixed_orbit_supported",
    "MgO": "fixed_orbit_supported",
    "CeO2": "fixed_orbit_supported",
    "ZrO2": "fixed_orbit_supported",
    "ThO2": "fixed_orbit_supported",
    "CsPbBr3": "fixed_orbit_supported",
    "CsSnBr3": "fixed_orbit_supported",
    "CsPbCl3": "fixed_orbit_supported",
    "ZnFe2O4": "fixed_orbit_supported",
    "MgAl2O4": "fixed_orbit_supported",
    "CoFe2O4": "fixed_orbit_supported",
    "Li6PS5Cl": "fixed_orbit_supported",
    "LiFePO4": "fixed_orbit_supported",
    "LiCoO2": "fixed_orbit_supported",
}

VARIABLE_SPP_SUPPORTED = {"BaTiO3", "CaTiO3", "SrTiO3"}


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    title: str
    description: str
    targets: list[tuple[str, str]]
    optional_targets: list[tuple[str, str]]
    db_name: str


DATASETS = {
    "common_families": DatasetSpec(
        dataset_id="common_families",
        title="Common Benchmark Families",
        description="Exact MP-derived targets for rocksalt, fluorite, halide perovskite, and spinel result cases.",
        targets=COMMON_TARGETS,
        optional_targets=[],
        db_name=DATASET_DBS["common_families"],
    ),
    "hard_intent": DatasetSpec(
        dataset_id="hard_intent",
        title="Hard Crystallographic-Intent Targets",
        description="Exact MP-derived hard targets for motif/space-group-intent paper demonstrations.",
        targets=HARD_TARGETS,
        optional_targets=HARD_OPTIONAL,
        db_name=DATASET_DBS["hard_intent"],
    ),
    "halide_perovskite": DatasetSpec(
        dataset_id="halide_perovskite",
        title="Specialist Halide Perovskite Corpus",
        description="Small specialist ABX3 halide-perovskite corpus for dataset-agnostic retrieval demonstrations.",
        targets=HALIDE_CORE,
        optional_targets=HALIDE_OPTIONAL,
        db_name=DATASET_DBS["halide_perovskite"],
    ),
    "kagome_optional": DatasetSpec(
        dataset_id="kagome_optional",
        title="Optional Kagome/Kagomite Corpus",
        description="Future-corpus plan unless a reliable MP motif seed list is provided.",
        targets=[],
        optional_targets=[],
        db_name=DATASET_DBS["kagome_optional"],
    ),
}


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        values[key] = value
    return values


def load_mp_api_key(repo_root: Path = REPO_ROOT) -> str | None:
    for name in ("MP_API_KEY", "MP-API-KEY", "MATERIALS_PROJECT_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value.strip()
    values = parse_env_file(repo_root / ".env")
    for name in ("MP_API_KEY", "MP-API-KEY", "MATERIALS_PROJECT_API_KEY"):
        value = values.get(name)
        if value:
            return value.strip()
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(value))


def canonical_element(symbol: str) -> str:
    text = str(symbol or "").strip()
    return text[:1].upper() + text[1:].lower() if text else text


def parse_formula(formula: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element, amount in re.findall(r"([A-Z][a-z]?)(\d*)", formula or ""):
        counts[canonical_element(element)] = counts.get(canonical_element(element), 0) + int(amount or "1")
    return counts


def required_pairs(formula: str) -> list[str]:
    elements = sorted(parse_formula(formula), key=str.lower)
    return [f"{left}-{right}" for left, right in combinations_with_replacement(elements, 2)]


def canonical_pair(pair: str) -> str:
    parts = [canonical_element(part) for part in str(pair).replace("_", "-").split("-") if part]
    return "-".join(sorted(parts, key=str.lower)) if len(parts) == 2 else str(pair)


def formula_to_chemsys(formula: str) -> str:
    return "-".join(sorted(parse_formula(formula), key=str.lower))


def structure_ids(db_path: Path) -> list[str]:
    conn = connect(str(db_path))
    init_db(conn)
    rows = conn.execute("SELECT structure_id FROM structures ORDER BY structure_id").fetchall()
    conn.close()
    return [row["structure_id"] for row in rows]


def count_table(db_path: Path, table: str, where: str = "") -> int:
    conn = sqlite3.connect(db_path)
    try:
        suffix = f" WHERE {where}" if where else ""
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}{suffix}").fetchone()[0])
    finally:
        conn.close()


def manifest_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def append_manifest(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = {key: json_safe(value) for key, value in row.items() if "key" not in key.lower()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(cleaned, sort_keys=True) + "\n")


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


def latest_manifest_by_target(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("target_formula") or ""), str(row.get("query_type") or ""))
        latest[key] = row
    return latest


def summary_value(doc: Any, name: str, default: Any = None) -> Any:
    if isinstance(doc, dict):
        return doc.get(name, default)
    return getattr(doc, name, default)


def symmetry_payload(doc: Any) -> dict[str, Any]:
    sym = summary_value(doc, "symmetry")
    if sym is None:
        return {}
    if isinstance(sym, dict):
        source = sym
    else:
        source = {
            name: getattr(sym, name, None)
            for name in ("crystal_system", "symbol", "number", "point_group", "symprec", "version")
        }
    return {key: value for key, value in source.items() if value is not None}


def row_from_doc(
    *,
    dataset_id: str,
    target_formula: str,
    requested_family: str,
    query_type: str,
    doc: Any,
    status: str,
    cif_path: Path | None = None,
    cif_sha256: str | None = None,
    error_text: str | None = None,
    source_query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    material_id = str(summary_value(doc, "material_id", "")) if doc is not None else None
    return {
        "dataset_id": dataset_id,
        "target_formula": target_formula,
        "requested_family": requested_family,
        "query_type": query_type,
        "material_id": material_id,
        "formula_pretty": summary_value(doc, "formula_pretty") if doc is not None else None,
        "formula_reduced": summary_value(doc, "formula_pretty") if doc is not None else None,
        "symmetry": symmetry_payload(doc) if doc is not None else {},
        "energy_above_hull": summary_value(doc, "energy_above_hull") if doc is not None else None,
        "is_stable": summary_value(doc, "is_stable") if doc is not None else None,
        "cif_path": str(cif_path) if cif_path else None,
        "cif_sha256": cif_sha256,
        "status": status,
        "error_text": error_text,
        "retrieved_at": now_iso(),
        "source": "materials_project",
        "source_query": source_query or {},
        "source_license_notes": SOURCE_LICENSE_NOTES,
    }


def sort_docs_for_target(docs: list[Any]) -> list[Any]:
    def key(doc: Any) -> tuple[int, float, str]:
        stable_rank = 0 if summary_value(doc, "is_stable") is True else 1
        e_hull = summary_value(doc, "energy_above_hull")
        try:
            e_value = float(e_hull)
        except (TypeError, ValueError):
            e_value = 999999.0
        return (stable_rank, e_value, str(summary_value(doc, "material_id", "")))

    return sorted(docs, key=key)


def mp_summary_search(mpr: Any, **kwargs: Any) -> list[Any]:
    fields = [
        "material_id",
        "formula_pretty",
        "symmetry",
        "energy_above_hull",
        "is_stable",
        "chemsys",
    ]
    try:
        return list(mpr.materials.summary.search(fields=fields, **kwargs))
    except TypeError:
        return list(mpr.materials.summary.search(**kwargs))


def find_exact_formula_docs(mpr: Any, formula: str, stable_only: bool) -> list[Any]:
    kwargs: dict[str, Any] = {"formula": formula}
    if stable_only:
        kwargs["is_stable"] = True
    docs = mp_summary_search(mpr, **kwargs)
    if docs or not stable_only:
        return sort_docs_for_target(docs)
    return sort_docs_for_target(mp_summary_search(mpr, formula=formula))


def write_cif_for_doc(mpr: Any, doc: Any, cif_dir: Path) -> tuple[Path, str]:
    from pymatgen.io.cif import CifWriter

    material_id = str(summary_value(doc, "material_id"))
    structure = mpr.get_structure_by_material_id(material_id)
    cif_text = str(CifWriter(structure))
    cif_dir.mkdir(parents=True, exist_ok=True)
    cif_path = cif_dir / f"{safe_filename(material_id)}.cif"
    cif_path.write_text(cif_text, encoding="utf-8")
    return cif_path, sha256_text(cif_text)


def acquire_target(
    *,
    mpr: Any,
    manifest_path: Path,
    cif_dir: Path,
    dataset_id: str,
    target_formula: str,
    requested_family: str,
    query_type: str,
    stable_only: bool,
    no_download: bool,
    force_refresh: bool,
) -> dict[str, Any]:
    source_query = {"formula": target_formula, "stable_only": bool(stable_only)}
    existing = latest_manifest_by_target(manifest_rows(manifest_path)).get((target_formula, query_type))
    if (
        existing
        and existing.get("status") == "OK"
        and existing.get("cif_sha256")
        and existing.get("cif_path")
        and Path(str(existing["cif_path"])).is_file()
        and not force_refresh
    ):
        return {**existing, "resume_status": "reused_existing_cif"}
    if no_download:
        row = row_from_doc(
            dataset_id=dataset_id,
            target_formula=target_formula,
            requested_family=requested_family,
            query_type=query_type,
            doc=None,
            status="BLOCKED",
            error_text="no_download_requested",
            source_query=source_query,
        )
        append_manifest(manifest_path, row)
        return row
    try:
        docs = find_exact_formula_docs(mpr, target_formula, stable_only=stable_only)
        if not docs:
            row = row_from_doc(
                dataset_id=dataset_id,
                target_formula=target_formula,
                requested_family=requested_family,
                query_type=query_type,
                doc=None,
                status="MISSING",
                error_text="no_materials_project_summary_match",
                source_query=source_query,
            )
            append_manifest(manifest_path, row)
            return row
        doc = docs[0]
        cif_path, cif_hash = write_cif_for_doc(mpr, doc, cif_dir)
        row = row_from_doc(
            dataset_id=dataset_id,
            target_formula=target_formula,
            requested_family=requested_family,
            query_type=query_type,
            doc=doc,
            status="OK",
            cif_path=cif_path,
            cif_sha256=cif_hash,
            source_query=source_query,
        )
        append_manifest(manifest_path, row)
        return row
    except Exception as exc:  # noqa: BLE001
        row = row_from_doc(
            dataset_id=dataset_id,
            target_formula=target_formula,
            requested_family=requested_family,
            query_type=query_type,
            doc=None,
            status="ERROR",
            error_text=f"{type(exc).__name__}: {exc}",
            source_query=source_query,
        )
        append_manifest(manifest_path, row)
        return row


def analogue_targets_for_dataset(spec: DatasetSpec, max_analogues_per_target: int) -> list[tuple[str, str]]:
    if max_analogues_per_target <= 0:
        return []
    if spec.dataset_id == "halide_perovskite":
        return HALIDE_OPTIONAL[: min(len(HALIDE_OPTIONAL), max_analogues_per_target * 3)]
    return []


def write_kagome_future_plan(dataset_dir: Path, db_path: Path) -> dict[str, Any]:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "cifs").mkdir(exist_ok=True)
    manifest_path = dataset_dir / "manifest.jsonl"
    if not manifest_path.exists():
        append_manifest(
            manifest_path,
            {
                "dataset_id": "kagome_optional",
                "target_formula": None,
                "requested_family": "kagome/kagomite",
                "query_type": "motif_search",
                "material_id": None,
                "status": "BLOCKED",
                "error_text": "future_dataset_plan: MP summary metadata does not expose a reliable kagome motif label and no audited seed list is present.",
                "retrieved_at": now_iso(),
                "source": "materials_project",
                "source_license_notes": SOURCE_LICENSE_NOTES,
            },
        )
    card = {
        "dataset_id": "kagome_optional",
        "title": DATASETS["kagome_optional"].title,
        "status": "future_dataset_plan",
        "db_path": str(db_path),
        "manifest_path": str(manifest_path),
        "counts": {"ok": 0, "blocked": 1, "missing": 0, "error": 0},
        "blocker": "Need a reliable MP-compatible kagome seed list or motif labels before downloading CIFs.",
        "created_at": now_iso(),
    }
    write_dataset_card(dataset_dir, card)
    return card


def target_coverage(rows: list[dict[str, Any]], targets: list[tuple[str, str]]) -> list[dict[str, Any]]:
    latest = latest_manifest_by_target(rows)
    table = []
    for formula, family in targets:
        row = latest.get((formula, "exact_formula")) or latest.get((formula, "analogue"))
        table.append(
            {
                "target_formula": formula,
                "requested_family": family,
                "status": row.get("status") if row else "NOT_ATTEMPTED",
                "material_id": row.get("material_id") if row else None,
                "cif_path": row.get("cif_path") if row else None,
                "error_text": row.get("error_text") if row else None,
                "symmetry": row.get("symmetry") if row else {},
            }
        )
    return table


def hard_intent_status(row: dict[str, Any]) -> str:
    if row.get("status") == "OK":
        formula = str(row.get("target_formula") or "")
        return "hard_success_candidate" if formula == "CoAs2" else "hard_partial_candidate"
    if row.get("status") == "MISSING":
        return "blocked_missing_mp"
    return "future_candidate"


def write_dataset_card(dataset_dir: Path, card: dict[str, Any]) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "dataset_card.json").write_text(json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = card.get("target_coverage", [])
    table = markdown_table(
        ["target", "family", "status", "material_id", "symmetry", "error"],
        [
            [
                row.get("target_formula"),
                row.get("requested_family"),
                row.get("status"),
                row.get("material_id") or "",
                json.dumps(row.get("symmetry") or {}, sort_keys=True),
                row.get("error_text") or "",
            ]
            for row in rows
        ],
    )
    md = "\n\n".join(
        [
            f"# {card.get('title', card.get('dataset_id'))}",
            card.get("description", ""),
            f"Status: `{card.get('status')}`",
            f"DB path: `{card.get('db_path')}`",
            f"Manifest: `{card.get('manifest_path')}`",
            "## Counts",
            "```json\n" + json.dumps(card.get("counts", {}), indent=2, sort_keys=True) + "\n```",
            "## Target Coverage",
            table,
        ]
    )
    (dataset_dir / "dataset_card.md").write_text(md + "\n", encoding="utf-8")


def create_dataset_card(spec: DatasetSpec, dataset_dir: Path, db_path: Path) -> dict[str, Any]:
    rows = manifest_rows(dataset_dir / "manifest.jsonl")
    counts = {
        "ok": sum(1 for row in rows if row.get("status") == "OK"),
        "missing": sum(1 for row in rows if row.get("status") == "MISSING"),
        "error": sum(1 for row in rows if row.get("status") == "ERROR"),
        "blocked": sum(1 for row in rows if row.get("status") == "BLOCKED"),
        "total_manifest_rows": len(rows),
    }
    status = "ready" if counts["ok"] else "blocked_or_empty"
    card = {
        "dataset_id": spec.dataset_id,
        "title": spec.title,
        "description": spec.description,
        "status": status,
        "created_at": now_iso(),
        "db_path": str(db_path),
        "manifest_path": str(dataset_dir / "manifest.jsonl"),
        "cif_dir": str(dataset_dir / "cifs"),
        "policy": "local_cif",
        "source": "materials_project",
        "source_license_notes": SOURCE_LICENSE_NOTES,
        "counts": counts,
        "target_coverage": target_coverage(rows, spec.targets + spec.optional_targets),
    }
    if spec.dataset_id == "hard_intent":
        for row in card["target_coverage"]:
            row["hard_intent_candidate_status"] = hard_intent_status(row)
    write_dataset_card(dataset_dir, card)
    return card


def remove_db_if_exists(db_path: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = Path(str(db_path) + suffix)
        if path.exists():
            path.unlink()


def ingest_and_index_dataset(
    *,
    spec: DatasetSpec,
    dataset_dir: Path,
    db_path: Path,
    skip_ingest: bool,
    skip_embeddings: bool,
    skip_seq: bool,
    skip_retrieval_smoke: bool,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "dataset_id": spec.dataset_id,
        "db_path": str(db_path),
        "ingest": {"status": "skipped" if skip_ingest else "not_started"},
        "fingerprints": {"status": "not_started"},
        "crystalcards": {"status": "not_started"},
        "text_docs": {"status": "not_started"},
        "text_embeddings": {"status": "skipped" if skip_embeddings else "not_started"},
        "sequences": {"status": "skipped" if skip_seq else "not_started"},
        "retrieval_smoke": {"status": "skipped" if skip_retrieval_smoke else "not_started"},
    }
    ok_rows = [row for row in manifest_rows(dataset_dir / "manifest.jsonl") if row.get("status") == "OK"]
    if not ok_rows:
        summary["ingest"] = {"status": "skipped_empty_dataset"}
        return summary
    if not skip_ingest:
        remove_db_if_exists(db_path)
        result = ingest_folder(
            db_path=str(db_path),
            folder_path=str(dataset_dir / "cifs"),
            source="materials_project_subset",
            policy_name="local_cif",
        )
        summary["ingest"] = {"status": "ok", **result}
    if not db_path.exists():
        return summary
    ids = structure_ids(db_path)
    fp_ok = 0
    card_ok = 0
    for sid in ids:
        fp = fingerprint_structure(structure_id=sid, db_path=str(db_path), store=True)
        if "error" not in fp:
            fp_ok += 1
        card = build_crystalcard(structure_id=sid, db_path=str(db_path), engine="baseline", store=True)
        if "error" not in card:
            card_ok += 1
    summary["fingerprints"] = {"status": "ok", "ok": fp_ok, "total": len(ids)}
    summary["crystalcards"] = {"status": "ok", "ok": card_ok, "total": len(ids)}
    try:
        text_result = generate_text_docs(
            db_path=str(db_path),
            engine="baseline",
            text_view="robocrys",
            batch=16,
            progress_every=1000,
        )
        summary["text_docs"] = {"status": "ok", **text_result}
    except Exception as exc:  # noqa: BLE001
        summary["text_docs"] = {"status": "error", "error_text": f"{type(exc).__name__}: {exc}"}
    if not skip_embeddings:
        if lmstudio_available():
            try:
                embed_result = embed_text_docs(
                    db_path=str(db_path),
                    text_engine="baseline",
                    text_view="robocrys",
                    embed_engine="lmstudio",
                    model_name=LMSTUDIO_MODEL_NAME,
                    model_version=LMSTUDIO_MODEL_VERSION,
                    batch=8,
                    progress_every=1000,
                )
                summary["text_embeddings"] = {"status": "ok", **embed_result}
            except Exception as exc:  # noqa: BLE001
                summary["text_embeddings"] = {"status": "error", "error_text": f"{type(exc).__name__}: {exc}"}
        else:
            summary["text_embeddings"] = {"status": "unavailable", "error_text": "LM Studio embeddings endpoint unavailable"}
    if not skip_seq:
        try:
            enc = encode_sequences(db_path=str(db_path), format="cif_canon")
            emb = embed_sequences(db_path=str(db_path), format="cif_canon")
            summary["sequences"] = {"status": "ok", "encoded": enc.get("processed"), "embedded": emb.get("processed")}
        except Exception as exc:  # noqa: BLE001
            summary["sequences"] = {"status": "error", "error_text": f"{type(exc).__name__}: {exc}"}
    if not skip_retrieval_smoke:
        summary["retrieval_smoke"] = run_retrieval_smoke(db_path, ids)
    if db_path.exists():
        summary["db_counts"] = {
            "structures": count_table(db_path, "structures"),
            "fingerprints": count_table(db_path, "structure_fingerprints"),
            "crystalcards": count_table(db_path, "structure_crystalcards"),
            "text_docs": count_table(db_path, "text_docs"),
            "text_embeddings_ok": count_table(db_path, "text_embeddings", "status = 'OK'"),
            "sequences": count_table(db_path, "structure_sequences"),
        }
    return summary


def lmstudio_available() -> bool:
    base_url = os.getenv("CRYSTALDB_EMBED_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
    try:
        with urllib.request.urlopen(base_url + "/models", timeout=2) as response:
            return 200 <= int(response.status) < 500
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return False


def run_retrieval_smoke(db_path: Path, ids: list[str]) -> dict[str, Any]:
    if not ids:
        return {"status": "skipped_empty"}
    result: dict[str, Any] = {}
    try:
        result["similar_struct"] = similar_structures(structure_id=ids[0], db_path=str(db_path), k=3)
    except Exception as exc:  # noqa: BLE001
        result["similar_struct"] = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        text_count = count_table(db_path, "text_embeddings", "status = 'OK'")
        if text_count:
            result["text_search"] = text_search(
                query_text=" ".join(ids[:1]),
                db_path=str(db_path),
                k=3,
                embed_engine="lmstudio",
                model_name=LMSTUDIO_MODEL_NAME,
                model_version=LMSTUDIO_MODEL_VERSION,
                text_engine="baseline",
                text_view="robocrys",
                show_text_top=0,
            )
        else:
            result["text_search"] = {"status": "skipped_no_embeddings"}
    except Exception as exc:  # noqa: BLE001
        result["text_search"] = {"error": f"{type(exc).__name__}: {exc}"}
    result["status"] = "ok"
    return result


def pot_pair_inventory(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {canonical_pair(path.stem) for path in root.rglob("*.POT")}


def pot_coverage_for_formula(formula: str) -> dict[str, Any]:
    pairs = [canonical_pair(pair) for pair in required_pairs(formula)]
    roots = []
    compatible = None
    best_missing: list[str] | None = None
    for root in POT_ROOTS:
        available = pot_pair_inventory(root)
        missing = sorted(set(pairs) - available)
        if best_missing is None or len(missing) < len(best_missing):
            best_missing = missing
        if root.is_dir() and not missing and compatible is None:
            compatible = str(root)
        roots.append({"root": str(root), "exists": root.is_dir(), "missing_pairs": missing})
    return {
        "formula": formula,
        "required_pairs": sorted(pairs),
        "compatible_pot_root": compatible,
        "missing_pairs": best_missing or [],
        "pot_coverage_status": "complete" if compatible else ("partial" if best_missing and len(best_missing) < len(pairs) else "missing"),
        "roots": roots,
    }


def solver_support_for_formula(formula: str) -> dict[str, Any]:
    if formula in VARIABLE_SPP_SUPPORTED:
        status = "variable_spp_supported"
    elif formula in SCAFFOLD_SUPPORTED:
        status = SCAFFOLD_SUPPORTED[formula]
    else:
        status = "retrieval_only"
    return {
        "formula": formula,
        "support_status": status,
        "variable_spp_supported": formula in VARIABLE_SPP_SUPPORTED,
        "scaffold_supported": formula in SCAFFOLD_SUPPORTED or formula in VARIABLE_SPP_SUPPORTED,
        "note": "No generation claim is made without a cheap smoke run or explicit scaffold support.",
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("\n", " ") for value in row) + " |")
    return "\n".join(lines)


def write_json_and_md_artifact(path_base: Path, payload: Any, title: str, table_headers: list[str], table_rows: list[list[Any]]) -> None:
    path_base.with_suffix(".json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = "\n\n".join([f"# {title}", markdown_table(table_headers, table_rows)])
    path_base.with_suffix(".md").write_text(md + "\n", encoding="utf-8")


def load_dataset_cards(out_root: Path) -> list[dict[str, Any]]:
    cards = []
    for path in sorted(out_root.glob("*/dataset_card.json")):
        cards.append(json.loads(path.read_text(encoding="utf-8")))
    return cards


def write_global_artifacts(out_root: Path, indexing_summaries: list[dict[str, Any]]) -> None:
    artifacts = REPO_ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    cards = load_dataset_cards(out_root)
    all_formulas = sorted(
        {
            row.get("target_formula")
            for card in cards
            for row in card.get("target_coverage", [])
            if row.get("target_formula")
        }
    )
    pot = [pot_coverage_for_formula(formula) for formula in all_formulas]
    solver = [solver_support_for_formula(formula) for formula in all_formulas]

    write_json_and_md_artifact(
        artifacts / "result_dataset_indexing_summary",
        {"schema_version": "result_dataset_indexing_summary.v1", "datasets": indexing_summaries},
        "Result Dataset Indexing Summary",
        ["dataset", "db", "ingest", "fingerprints", "text_docs", "embeddings", "seq", "smoke"],
        [
            [
                item.get("dataset_id"),
                item.get("db_path"),
                (item.get("ingest") or {}).get("status"),
                (item.get("fingerprints") or {}).get("status"),
                (item.get("text_docs") or {}).get("status"),
                (item.get("text_embeddings") or {}).get("status"),
                (item.get("sequences") or {}).get("status"),
                (item.get("retrieval_smoke") or {}).get("status"),
            ]
            for item in indexing_summaries
        ],
    )
    write_json_and_md_artifact(
        artifacts / "result_dataset_pot_coverage",
        {"schema_version": "result_dataset_pot_coverage.v1", "targets": pot},
        "Result Dataset POT Coverage",
        ["formula", "status", "compatible root", "missing pairs"],
        [[item["formula"], item["pot_coverage_status"], item["compatible_pot_root"] or "", ", ".join(item["missing_pairs"])] for item in pot],
    )
    write_json_and_md_artifact(
        artifacts / "result_dataset_solver_support",
        {"schema_version": "result_dataset_solver_support.v1", "targets": solver},
        "Result Dataset Solver Support",
        ["formula", "support", "scaffold"],
        [[item["formula"], item["support_status"], item["scaffold_supported"]] for item in solver],
    )
    final = {
        "schema_version": "paper_result_datasets_built.v1",
        "created_at": now_iso(),
        "dataset_cards": cards,
        "indexing_summaries": indexing_summaries,
        "pot_coverage": pot,
        "solver_support": solver,
        "recommended_result_1_targets": [
            row
            for card in cards
            if card.get("dataset_id") == "common_families"
            for row in card.get("target_coverage", [])
            if row.get("status") == "OK"
        ],
        "recommended_result_2_targets": [
            row
            for card in cards
            if card.get("dataset_id") == "hard_intent"
            for row in card.get("target_coverage", [])
            if row.get("status") == "OK"
        ],
        "recommended_result_3_corpus": "halide_perovskite" if any(card.get("dataset_id") == "halide_perovskite" and card.get("counts", {}).get("ok", 0) for card in cards) else None,
        "exact_next_commands": [
            r"python C:\Users\brown\Documents\GitHub\Skill-Loop-CSP\scripts\run_prototype_orbit_variable_spp_qlip_smoke.py --pot-dir C:\Users\brown\Downloads\SPP\SPP\SPP\SPP --out-root C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs\paper_result_smoke --allow-spp-unavailable",
            r"python -m sca.cli run-symmetry-intent-benchmark --manifest <manifest.csv> --out-dir <sca_out_dir> --symprec 0.01 --angle-tolerance 5",
            r"python -m crystal_db text-search --db data\result_halide_perovskite.db --query ""lead bromide halide perovskite"" --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine baseline --text-view robocrys --k 5",
        ],
    }
    (artifacts / "paper_result_datasets_built.json").write_text(json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = []
    for card in cards:
        rows.append([card.get("dataset_id"), card.get("status"), card.get("db_path"), (card.get("counts") or {}).get("ok"), (card.get("counts") or {}).get("missing"), (card.get("counts") or {}).get("blocked")])
    md = "\n\n".join(
        [
            "# Paper Result Datasets Built",
            "## Dataset Cards Summary",
            markdown_table(["dataset", "status", "db", "OK", "missing", "blocked"], rows),
            "## Acquisition Success/Failure Table",
            markdown_table(
                ["dataset", "formula", "status", "material_id", "error"],
                [
                    [
                        card.get("dataset_id"),
                        row.get("target_formula"),
                        row.get("status"),
                        row.get("material_id") or "",
                        row.get("error_text") or "",
                    ]
                    for card in cards
                    for row in card.get("target_coverage", [])
                ],
            ),
            "## Embedding And Indexing Status",
            markdown_table(
                ["dataset", "structures", "fingerprints", "text docs", "text embeddings", "sequences", "smoke"],
                [
                    [
                        item.get("dataset_id"),
                        (item.get("db_counts") or {}).get("structures", ""),
                        (item.get("db_counts") or {}).get("fingerprints", ""),
                        (item.get("db_counts") or {}).get("text_docs", ""),
                        (item.get("db_counts") or {}).get("text_embeddings_ok", ""),
                        (item.get("db_counts") or {}).get("sequences", ""),
                        (item.get("retrieval_smoke") or {}).get("status", (item.get("ingest") or {}).get("status")),
                    ]
                    for item in indexing_summaries
                ],
            ),
            "## POT Coverage Table",
            markdown_table(
                ["formula", "status", "compatible root", "missing pairs"],
                [[item["formula"], item["pot_coverage_status"], item["compatible_pot_root"] or "", ", ".join(item["missing_pairs"])] for item in pot],
            ),
            "## Solver Support Table",
            markdown_table(
                ["formula", "support", "scaffold"],
                [[item["formula"], item["support_status"], item["scaffold_supported"]] for item in solver],
            ),
            "## Recommended Result 1 Targets",
            markdown_table(["formula", "status", "material_id"], [[r.get("target_formula"), r.get("status"), r.get("material_id")] for r in final["recommended_result_1_targets"]]),
            "## Recommended Result 2 Targets",
            markdown_table(["formula", "status", "material_id"], [[r.get("target_formula"), r.get("status"), r.get("material_id")] for r in final["recommended_result_2_targets"]]),
            "## Result 3 Corpus",
            str(final["recommended_result_3_corpus"]),
            "## Exact Next Commands",
            "\n".join(f"- `{cmd}`" for cmd in final["exact_next_commands"]),
        ]
    )
    (artifacts / "paper_result_datasets_built.md").write_text(md + "\n", encoding="utf-8")


def build_dataset(spec: DatasetSpec, args: argparse.Namespace, mpr: Any | None) -> dict[str, Any]:
    out_root = Path(args.out_root)
    db_out = Path(args.db_out)
    dataset_dir = out_root / spec.dataset_id
    cif_dir = dataset_dir / "cifs"
    db_path = db_out / spec.db_name
    dataset_dir.mkdir(parents=True, exist_ok=True)
    cif_dir.mkdir(exist_ok=True)
    manifest_path = dataset_dir / "manifest.jsonl"
    if args.force_refresh and manifest_path.exists():
        manifest_path.unlink()
    if spec.dataset_id == "kagome_optional":
        card = write_kagome_future_plan(dataset_dir, db_path)
        return {"dataset_card": card, "indexing_summary": {"dataset_id": spec.dataset_id, "db_path": str(db_path), "ingest": {"status": "future_dataset_plan"}}}
    targets = [(formula, family, "exact_formula") for formula, family in spec.targets]
    if spec.dataset_id == "hard_intent":
        targets.extend((formula, family, "exact_formula") for formula, family in spec.optional_targets)
    targets.extend((formula, family, "analogue") for formula, family in analogue_targets_for_dataset(spec, args.max_analogues_per_target))
    for formula, family, query_type in targets:
        acquire_target(
            mpr=mpr,
            manifest_path=manifest_path,
            cif_dir=cif_dir,
            dataset_id=spec.dataset_id,
            target_formula=formula,
            requested_family=family,
            query_type=query_type,
            stable_only=args.stable_only,
            no_download=args.no_download,
            force_refresh=args.force_refresh,
        )
        if not args.no_download:
            time.sleep(0.1)
    card = create_dataset_card(spec, dataset_dir, db_path)
    indexing = ingest_and_index_dataset(
        spec=spec,
        dataset_dir=dataset_dir,
        db_path=db_path,
        skip_ingest=args.skip_ingest,
        skip_embeddings=args.skip_embeddings,
        skip_seq=args.skip_seq,
        skip_retrieval_smoke=args.skip_retrieval_smoke,
    )
    return {"dataset_card": card, "indexing_summary": indexing}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["common_families", "hard_intent", "halide_perovskite", "kagome_optional", "all"], required=True)
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "result_datasets"))
    parser.add_argument("--db-out", default=str(REPO_ROOT / "data"))
    parser.add_argument("--max-analogues-per-target", type=int, default=5)
    parser.add_argument("--stable-only", action="store_true")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--skip-embeddings", action="store_true")
    parser.add_argument("--skip-seq", action="store_true")
    parser.add_argument("--skip-retrieval-smoke", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dataset_ids = ["common_families", "hard_intent", "halide_perovskite", "kagome_optional"] if args.dataset == "all" else [args.dataset]
    api_key = load_mp_api_key()
    if not api_key and not args.no_download:
        print(json.dumps({"error": "missing_mp_api_key", "message": "Set MP_API_KEY, MP-API-KEY, or MATERIALS_PROJECT_API_KEY in environment or .env."}, indent=2), file=sys.stderr)
        return 2
    mpr = None
    if not args.no_download:
        from mp_api.client import MPRester

        mpr = MPRester(api_key)
    indexing_summaries = []
    try:
        for dataset_id in dataset_ids:
            result = build_dataset(DATASETS[dataset_id], args, mpr)
            indexing_summaries.append(result["indexing_summary"])
    finally:
        close = getattr(mpr, "close", None)
        if callable(close):
            close()
    write_global_artifacts(Path(args.out_root), indexing_summaries)
    print(json.dumps({"datasets": dataset_ids, "artifacts": "artifacts/paper_result_datasets_built.json"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
