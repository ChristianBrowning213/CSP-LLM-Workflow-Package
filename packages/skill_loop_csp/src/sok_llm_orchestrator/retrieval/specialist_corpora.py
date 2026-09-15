"""Portable corpus registry and Crystal-DB-supported retrieval adapter."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from crystal_db.retrieval import text_search
from pymatgen.core import Composition, Structure


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = Path(__file__).with_name("corpus_registry.json")


def _crystal_data_root(configured: Path | None = None) -> Path:
    if configured is not None:
        return Path(configured).resolve()
    environment_root = os.getenv("CRYSTAL_DB_DATA_ROOT")
    if environment_root:
        return Path(environment_root).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "docs" / "fidelity" / "SOURCE_SYSTEMS.json").is_file():
            return (parent / "data" / "crystal_db" / "runtime").resolve()
    return (REPO_ROOT / "data" / "crystal_db" / "runtime").resolve()


def load_corpus_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "specialist_corpus_registry.v1":
        raise ValueError(f"Unsupported corpus registry: {path}")
    return payload


def resolve_corpus(
    corpus_id: str,
    path: Path | None = None,
    *,
    crystal_db_root: Path | None = None,
) -> dict[str, Any]:
    registry_path = DEFAULT_REGISTRY if path is None else Path(path)
    registry = load_corpus_registry(registry_path)
    try:
        record = dict(registry["corpora"][corpus_id])
    except KeyError as exc:
        raise KeyError(f"Unknown corpus_id '{corpus_id}'") from exc
    path_base = record.get("path_base")
    if path_base == "repository":
        base = REPO_ROOT
    elif path_base == "crystal_data_root":
        base = _crystal_data_root(crystal_db_root)
    else:
        raise ValueError(f"Unsupported path_base '{path_base}' for corpus '{corpus_id}'")
    database = (base / str(record["database"])).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Corpus database does not exist: {database}")
    return {"corpus_id": corpus_id, **record, "database": str(database)}


def _formula_from_cif(cif_text: str) -> str | None:
    try:
        return Structure.from_str(cif_text, fmt="cif").composition.reduced_formula
    except Exception:  # noqa: BLE001 - retrieval record carries parse status instead
        return None


def retrieve_corpus_evidence(
    corpus_id: str,
    *,
    query_text: str,
    target_formula: str = "Na3Zr2Si2PO12",
    depth: int = 40,
    registry_path: Path = DEFAULT_REGISTRY,
    embedding_endpoint: str = "http://127.0.0.1:1234/v1",
    embedding_model: str = "text-embedding-bge-m3",
) -> dict[str, Any]:
    """Retrieve through Crystal-DB's supported API and return an auditable bundle.

    ``embedding_endpoint`` remains in the compatibility signature. Crystal-DB
    owns endpoint configuration; this adapter does not issue its own HTTP or
    SQLite calls.
    """
    del embedding_endpoint
    corpus = resolve_corpus(corpus_id, registry_path)
    target_reduced = Composition(target_formula).reduced_composition
    with tempfile.TemporaryDirectory(prefix="skill_loop_crystaldb_") as export_dir:
        result = text_search(
            query_text=query_text,
            db_path=corpus["database"],
            k=max(1, int(depth)),
            embed_engine="lmstudio",
            model_name=embedding_model,
            model_version="lmstudio_v1",
            text_engine="robocrys",
            text_view="robocrys",
            show_text_top=max(1, int(depth)),
            export_dir=export_dir,
            export_top=max(1, int(depth)),
            redacted=False,
            demo_export=False,
        )
        if result.get("status") != "ok":
            error = result.get("errors") or {"code": "crystaldb_retrieval_failed"}
            raise RuntimeError(f"Crystal-DB text_search failed for '{corpus_id}': {error}")
        selected: list[dict[str, Any]] = []
        for neighbor in result.get("neighbors", []):
            export = neighbor.get("cif_export") if isinstance(neighbor, dict) else None
            export_path = Path(str(export.get("path"))) if isinstance(export, dict) and export.get("status") == "exported" else None
            cif_text = export_path.read_text(encoding="utf-8") if export_path is not None and export_path.is_file() else None
            reduced_formula = _formula_from_cif(cif_text) if cif_text else None
            try:
                exact = Composition(reduced_formula).reduced_composition == target_reduced if reduced_formula else False
            except Exception:
                exact = False
            selected.append(
                {
                    **neighbor,
                    "retrieval_score": float(neighbor.get("score", 0.0)),
                    "reduced_formula": reduced_formula,
                    "cif_text": cif_text,
                    "eligible_for_internal_spp": bool(cif_text),
                    "external_export_allowed": bool(cif_text),
                    "exact_target_formula": exact,
                }
            )
    backend = result.get("backend_status", {})
    query = result.get("query", {})
    return {
        "schema_version": "specialist_corpus_retrieval.v2",
        "corpus": corpus,
        "query_text": query_text,
        "target_formula": target_formula,
        "retrieval_depth": int(depth),
        "retrieval_method": "crystal_db.retrieval.text_search",
        "embedding_backend": {
            "embed_engine": query.get("embed_engine"),
            "model": query.get("model_name"),
            "model_version": query.get("model_version"),
            "backend_state": backend.get("state"),
        },
        "corpus_row_count": corpus.get("record_count"),
        "selected_count": len(selected),
        "eligible_internal_spp_count": sum(bool(item["eligible_for_internal_spp"]) for item in selected),
        "exact_target_leakage_count": sum(bool(item["exact_target_formula"]) for item in selected),
        "selected": selected,
    }


__all__ = ["DEFAULT_REGISTRY", "load_corpus_registry", "resolve_corpus", "retrieve_corpus_evidence"]
