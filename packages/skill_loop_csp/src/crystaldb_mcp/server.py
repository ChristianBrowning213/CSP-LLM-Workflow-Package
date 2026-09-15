from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.mcp.fake_lib import serve

TOOLS = [
    "crystal.text_search",
    "crystal.agent",
    "crystal.novelty_check",
    "crystal.csp_pack",
    "crystal.bench_retrieval",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def on_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "crystal.text_search":
        query = args.get("query") or args.get("text") or ""
        return {
            "schema_version": "text_search.v1",
            "query": {"text": query, "k": int(args.get("k", 10))},
            "neighbors": [
                {
                    "rank": 1,
                    "structure_id": "mp-1",
                    "score": 0.99,
                    "property_metadata": {"property_x": 0.71, "band_gap_ev": 2.95},
                    "provenance": {"allow_export": 0},
                    "redacted": bool(args.get("redacted", True)),
                }
            ],
            "errors": None,
        }
    if name == "crystal.agent":
        return {
            "schema_version": "agent.v1",
            "run_id": "agent-run",
            "answer": "local shim answer",
            "cited_structure_ids": ["mp-1"],
            "evidence": {"summary": "shim", "cited_structure_ids": ["mp-1"], "top_neighbors": []},
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
        query = args.get("query")
        structure_id = args.get("structure_id")
        if bool(query) == bool(structure_id):
            return {
                "schema_version": "error.v1",
                "errors": {
                    "code": "invalid_input",
                    "message": "Exactly one of query or structure_id must be provided.",
                    "details": {},
                },
            }
        out_dir = Path(args["out_dir"]).resolve()
        cifs_dir = out_dir / "cifs"
        cifs_dir.mkdir(parents=True, exist_ok=True)
        allow_export = int(os.environ.get("FAKE_CRYSTAL_ALLOW_EXPORT", "0"))
        policy_mode = os.environ.get("CRYSTALDB_POLICY_MODE", "safe")
        demo_export = bool(args.get("demo_export", False))
        exported = False
        if allow_export == 1:
            exported = True
        elif demo_export and policy_mode == "demo":
            exported = True
        cif_export = {"status": "blocked", "error": "policy_blocked"}
        if exported and int(args.get("export_top", 0)) > 0:
            cif_path = cifs_dir / "neighbor_1.cif"
            cif_path.write_text("data_stub\n", encoding="utf-8")
            cif_export = {"status": "exported", "path": str(cif_path)}
        _write_json(out_dir / "manifest.json", {"ok": True})
        _write_json(out_dir / "results.json", {"neighbors": 1})
        return {
            "schema_version": "csp_pack.v1",
            "run_id": "crystal-run",
            "query": {"mode": "query", "value": query or structure_id},
            "neighbors": [
                {
                    "rank": 1,
                    "structure_id": "mp-1",
                    "score": 0.99,
                    "property_metadata": {"property_x": 0.71, "band_gap_ev": 2.95},
                    "provenance": {"allow_export": allow_export},
                    "cif_export": cif_export,
                }
            ],
            "hints": {
                "family_candidates": ["rutile"],
                "connectivity_keywords": ["octahedral"],
                "chemistry_tokens": ["Ti", "O"],
                "symmetry_tokens": ["P42/mnm"],
                "quantitative_clues": [],
                "confidence": 0.8,
                "rationale": ["shim"],
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
