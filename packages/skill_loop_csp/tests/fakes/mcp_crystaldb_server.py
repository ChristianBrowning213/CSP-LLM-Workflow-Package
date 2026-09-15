from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp_fake_lib import serve

TOOLS = [
    "crystal.status",
    "crystal.text_search",
    "crystal.agent",
    "crystal.novelty_check",
    "crystal.csp_pack",
    "crystal.bench_retrieval",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _backend_status() -> tuple[dict[str, Any], dict[str, Any] | None]:
    db_path = os.environ.get("FAKE_CRYSTALDB_DB_PATH", "stub://crystal.db")
    index_path = os.environ.get("FAKE_CRYSTALDB_INDEX_PATH", "stub://embeddings.index")
    missing_db = os.environ.get("FAKE_CRYSTALDB_MISSING_DB") == "1"
    missing_index = os.environ.get("FAKE_CRYSTALDB_MISSING_INDEX") == "1"
    missing_embedding = os.environ.get("FAKE_CRYSTALDB_MISSING_EMBEDDING") == "1"
    candidate_empty = os.environ.get("FAKE_CRYSTALDB_CANDIDATE_SET_EMPTY") == "1"
    if missing_db:
        status = {
            "state": "not_ready",
            "code": "missing_db",
            "db_path": db_path,
            "index_path": index_path,
            "candidate_count": 0,
            "embedding_space_count": 0,
            "fingerprint_count": 0,
        }
        return status, {"code": "missing_db", "message": "stub missing db"}
    if missing_index:
        status = {
            "state": "not_ready",
            "code": "missing_index",
            "db_path": db_path,
            "index_path": index_path,
            "candidate_count": 42,
            "embedding_space_count": 0,
            "fingerprint_count": 0,
        }
        return status, {"code": "missing_index", "message": "stub missing index"}
    if missing_embedding:
        status = {
            "state": "not_ready",
            "code": "missing_embedding_space",
            "db_path": db_path,
            "index_path": index_path,
            "candidate_count": 42,
            "embedding_space_count": 0,
            "fingerprint_count": 42,
        }
        return status, {"code": "missing_embedding_space", "message": "stub missing embedding space"}
    if candidate_empty:
        status = {
            "state": "not_ready",
            "code": "candidate_set_empty",
            "db_path": db_path,
            "index_path": index_path,
            "candidate_count": 0,
            "embedding_space_count": 0,
            "fingerprint_count": 0,
        }
        return status, {"code": "candidate_set_empty", "message": "stub candidate set empty"}
    status = {
        "state": "ready",
        "code": "ok",
        "db_path": db_path,
        "index_path": index_path,
        "candidate_count": int(os.environ.get("FAKE_CRYSTALDB_CANDIDATE_COUNT", "256")),
        "embedding_space_count": int(os.environ.get("FAKE_CRYSTALDB_EMBEDDING_COUNT", "256")),
        "fingerprint_count": int(os.environ.get("FAKE_CRYSTALDB_FINGERPRINT_COUNT", "256")),
    }
    return status, None


def _query_to_structure_id(query: Any, *, collapsed: bool = False) -> str:
    query_text = str(query).strip().lower()
    if query_text.startswith("tio2") or "tio2" in query_text:
        structure_id = "mp-tio2-probe"
    elif query_text.startswith("batio3") or "batio3" in query_text:
        structure_id = "mp-batio3-probe"
    else:
        query_token = abs(hash(str(query_text))) % 997
        structure_id = f"mp-{query_token}"
    if collapsed:
        structure_id = "mp-1"
    return structure_id


def on_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    backend_status, backend_error = _backend_status()
    backend_ready = backend_status.get("state") == "ready"
    empty_retrieval = os.environ.get("FAKE_CRYSTALDB_EMPTY_RETRIEVAL") == "1"
    if name == "crystal.status":
        return {
            "schema_version": "crystal_status.v1",
            "status": "ok" if backend_ready else "backend_not_ready",
            "backend_status": backend_status,
            "errors": backend_error,
        }
    if name == "crystal.text_search":
        if not backend_ready:
            return {
                "schema_version": "text_search.v1",
                "query": {"text": args.get("query") or args.get("text") or "", "k": int(args.get("k", 10))},
                "status": "backend_not_ready",
                "backend_status": backend_status,
                "neighbors": [],
                "errors": backend_error,
            }
        query = args.get("query") or args.get("text") or ""
        collapsed = os.environ.get("FAKE_CRYSTALDB_COLLAPSED") == "1"
        structure_id = _query_to_structure_id(query, collapsed=collapsed)
        neighbors = []
        if not empty_retrieval:
            neighbors = [
                {
                    "rank": 1,
                    "structure_id": structure_id,
                    "score": 0.99,
                    "property_metadata": {"property_x": 0.71, "band_gap_ev": 2.95},
                    "provenance": {"allow_export": 0},
                    "redacted": bool(args.get("redacted", True)),
                }
            ]
        return {
            "schema_version": "text_search.v1",
            "query": {"text": query, "k": int(args.get("k", 10))},
            "status": "ok",
            "backend_status": backend_status,
            "neighbors": neighbors,
            "errors": None,
        }
    if name == "crystal.agent":
        return {
            "schema_version": "agent.v1",
            "run_id": "agent-run",
            "answer": "stub answer",
            "cited_structure_ids": ["mp-1"],
            "evidence": {"summary": "stub", "cited_structure_ids": ["mp-1"], "top_neighbors": []},
            "errors": None,
        }
    if name == "crystal.novelty_check":
        return {
            "schema_version": "novelty_check.v1",
            "candidate": {"source": "cif", "structure_id": "candidate"},
            "comparators": [],
            "novelty": {
                "is_novel": True,
                "thresholds": {"text_sim_threshold": 0.8, "fp_sim_threshold": 0.95},
                "max_text_similarity": 0.0,
                "max_fp_similarity": 0.0,
                "reason_codes": [],
            },
            "run_id": "novelty-run",
            "errors": None,
        }
    if name == "crystal.csp_pack":
        if not backend_ready:
            return {
                "schema_version": "csp_pack.v1",
                "run_id": "crystal-run",
                "status": "backend_not_ready",
                "backend_status": backend_status,
                "query": {"mode": "query", "value": args.get("query") or args.get("structure_id")},
                "neighbors": [],
                "hints": {
                    "family_candidates": [],
                    "connectivity_keywords": [],
                    "chemistry_tokens": [],
                    "symmetry_tokens": [],
                    "quantitative_clues": [],
                    "confidence": 0.0,
                    "rationale": ["stub backend not ready"],
                },
                "exports": {
                    "out_dir": str(Path(args["out_dir"]).resolve()),
                    "manifest_json": str((Path(args["out_dir"]).resolve() / "manifest.json")),
                    "results_json": str((Path(args["out_dir"]).resolve() / "results.json")),
                    "cifs_dir": str((Path(args["out_dir"]).resolve() / "cifs")),
                },
                "errors": backend_error,
            }
        query = args.get("query")
        structure_id = args.get("structure_id")
        if bool(query) == bool(structure_id):
            return {
                "schema_version": "error.v1",
                "status": "error",
                "backend_status": backend_status,
                "errors": {
                    "code": "invalid_input",
                    "message": "Exactly one of query or structure_id must be provided.",
                    "details": {},
                },
            }
        if os.environ.get("FAKE_CRYSTALDB_QUERY_TOOL_MISMATCH") == "1":
            return {
                "schema_version": "csp_pack.v1",
                "run_id": "crystal-run",
                "status": "error",
                "backend_status": backend_status,
                "query": {"mode": "query", "value": query or structure_id},
                "neighbors": [],
                "hints": {
                    "family_candidates": [],
                    "connectivity_keywords": [],
                    "chemistry_tokens": [],
                    "symmetry_tokens": [],
                    "quantitative_clues": [],
                    "confidence": 0.0,
                    "rationale": ["query mismatch"],
                },
                "exports": {
                    "out_dir": str(Path(args["out_dir"]).resolve()),
                    "manifest_json": str((Path(args["out_dir"]).resolve() / "manifest.json")),
                    "results_json": str((Path(args["out_dir"]).resolve() / "results.json")),
                    "cifs_dir": str((Path(args["out_dir"]).resolve() / "cifs")),
                },
                "errors": {"code": "query_tool_mismatch", "message": "stub pack query mismatch"},
            }
        out_dir = Path(args["out_dir"]).resolve()
        cifs_dir = out_dir / "cifs"
        cifs_dir.mkdir(parents=True, exist_ok=True)
        allow_export = int(os.environ.get("FAKE_CRYSTAL_ALLOW_EXPORT", "0"))
        policy_mode = os.environ.get("CRYSTALDB_POLICY_MODE", "safe")
        demo_export = bool(args.get("demo_export", False))
        export_top = int(args.get("export_top", 0))
        neighbor_count = max(1, min(10, export_top if export_top > 0 else 1))
        export_pattern_raw = os.environ.get("FAKE_CRYSTAL_EXPORT_PATTERN", "").strip()
        export_pattern = [item.strip().lower() for item in export_pattern_raw.split(",") if item.strip()] if export_pattern_raw else []
        exported = False
        if allow_export == 1:
            exported = True
        elif demo_export and policy_mode == "demo":
            exported = True
        cif_export = {"status": "blocked", "error": "policy_blocked"}
        if export_pattern:
            for idx in range(1, neighbor_count + 1):
                if export_pattern[min(idx - 1, len(export_pattern) - 1)] != "exported":
                    continue
                cif_path = cifs_dir / f"neighbor_{idx}.cif"
                cif_path.write_text(f"data_stub_{idx}\n", encoding="utf-8")
        elif exported and export_top > 0:
            for idx in range(1, neighbor_count + 1):
                cif_path = cifs_dir / f"neighbor_{idx}.cif"
                cif_path.write_text(f"data_stub_{idx}\n", encoding="utf-8")
            cif_export = {"status": "exported", "path": str(cifs_dir / "neighbor_1.cif")}
        _write_json(out_dir / "manifest.json", {"ok": True})
        _write_json(out_dir / "results.json", {"neighbors": neighbor_count})
        collapsed = os.environ.get("FAKE_CRYSTALDB_COLLAPSED") == "1"
        base_structure_id = _query_to_structure_id(query or structure_id, collapsed=collapsed)
        neighbors = []
        if not empty_retrieval:
            for idx in range(1, neighbor_count + 1):
                if export_pattern:
                    status = export_pattern[min(idx - 1, len(export_pattern) - 1)]
                    if status == "exported":
                        neighbor_export = {"status": "exported", "path": str(cifs_dir / f"neighbor_{idx}.cif")}
                    else:
                        neighbor_export = {"status": "blocked", "error": "policy_blocked"}
                else:
                    neighbor_export = cif_export
                neighbors.append(
                    {
                        "rank": idx,
                        "structure_id": f"{base_structure_id}-{idx}",
                        "score": round(1.0 - (0.03 * (idx - 1)), 6),
                        "property_metadata": {
                            "property_x": round(0.5 + (0.04 * idx), 6),
                            "band_gap_ev": round(2.6 + (0.07 * idx), 6),
                        },
                        "provenance": {"allow_export": allow_export},
                        "cif_export": neighbor_export,
                    }
                )
        return {
            "schema_version": "csp_pack.v1",
            "run_id": "crystal-run",
            "status": "ok",
            "backend_status": backend_status,
            "query": {"mode": "query", "value": query or structure_id},
            "neighbors": neighbors,
            "hints": {
                "family_candidates": ["rutile"],
                "connectivity_keywords": ["octahedral"],
                "chemistry_tokens": ["Ti", "O"],
                "symmetry_tokens": ["P42/mnm"],
                "quantitative_clues": [],
                "confidence": 0.8,
                "rationale": ["stub"],
            },
            "exports": {
                "out_dir": str(out_dir),
                "manifest_json": str(out_dir / "manifest.json"),
                "results_json": str(out_dir / "results.json"),
                "cifs_dir": str(cifs_dir),
            },
            "errors": None,
        }
    if name == "crystal.bench_retrieval":
        out_dir = Path(args["out_dir"]).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        return {
            "schema_version": "bench_retrieval.v1",
            "run_id": "bench-run",
            "config": {},
            "summary": {"total_cases": 0, "failure_rate": 0.0},
            "per_case": [],
            "exports": {
                "summary_json": str(out_dir / "summary.json"),
                "cases_scored_jsonl": str(out_dir / "cases.jsonl"),
                "summary_csv": str(out_dir / "summary.csv"),
            },
            "errors": None,
        }
    return {"schema_version": "error.v1", "errors": {"code": "unknown_tool", "message": name, "details": {}}}


if __name__ == "__main__":
    serve(TOOLS, on_call)
