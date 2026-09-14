import json

import pytest

from crystal_db.db import connect, init_db
from crystal_db.schema_validate import validate
from mcp_server import server as mcp_server


def _seed_mcp_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    rows = [
        ("s-a", 1, "Li2O", "P4/mmm", "layered perovskite corner-sharing octahedra", [1.0, 0.0], [1.0, 0.0]),
        ("s-b", 1, "NaCl", "Fm-3m", "laves boride tetrahedra", [0.8, 0.2], [0.8, 0.2]),
        ("s-c", 0, "SiO2", "P1", "redacted layered text", [0.6, 0.4], [0.6, 0.4]),
    ]
    for sid, allow_export, formula, spg, text, text_vec, fp_vec in rows:
        conn.execute(
            "INSERT INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, f"data_{sid}\n_cell_length_a 1\n", formula, 1, 1.0, 0),
        )
        elements_csv = "," + ",".join([token for token in ["Li", "Na", "Si", "O", "Cl"] if token in formula]) + ","
        conn.execute(
            "INSERT INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, formula, elements_csv, spg, 0.1),
        )
        conn.execute(
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export, allow_derivatives) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "test", f"{sid}.cif", ts, allow_export, 1),
        )
        text_doc_id = conn.execute(
            "INSERT INTO text_docs "
            "(structure_id, engine, text_view, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "caption", "caption", "v1", text, f"h-{sid}", "OK", None, None, ts, ts),
        ).lastrowid
        conn.execute(
            "INSERT INTO text_embeddings "
            "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (text_doc_id, "hash", "hash-embed", "v1", 2, json.dumps(text_vec), "OK", None, None, ts, ts),
        )
        conn.execute(
            "INSERT INTO structure_fingerprints "
            "(structure_id, fingerprint_method, fingerprint_version, vector_json, feature_names_json, input_hash, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, "fp.simple.v1", "v1", json.dumps(fp_vec), json.dumps(["f1", "f2"]), f"fp-{sid}", ts),
        )
    conn.commit()
    conn.close()


def _write_cases(path):
    cases = [
        {
            "case_id": "mcp-c1",
            "query": "perovskite corner-sharing octahedra",
            "expected": {"must_contain_any": ["perovskite"]},
        }
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for item in cases:
            handle.write(json.dumps(item) + "\n")


def test_mcp_tool_registry_names_stable():
    assert list(mcp_server.TOOL_REGISTRY.keys()) == [
        "crystal.text_search",
        "crystal.agent",
        "crystal.novelty_check",
        "crystal.csp_pack",
        "crystal.status",
        "crystal.bench_retrieval",
    ]
    listed = [item["name"] for item in mcp_server.list_tools()]
    assert listed == list(mcp_server.TOOL_REGISTRY.keys())


def test_mcp_handlers_return_schema_valid_payloads(tmp_path, monkeypatch):
    db_path = tmp_path / "mcp.db"
    cases_path = tmp_path / "cases.jsonl"
    _seed_mcp_db(db_path)
    _write_cases(cases_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    text_payload = mcp_server._tool_text_search(
        {
            "db_path": str(db_path),
            "query": "layered material",
            "k": 3,
            "embed_engine": "hash",
            "model": "hash-embed",
            "model_version": "v1",
            "text_engine": "caption",
            "text_view": "caption",
            "hybrid": False,
            "redacted": True,
            "show_text_top": 1,
        }
    )
    validate(text_payload, "text_search.v1")

    pack_payload = mcp_server._tool_csp_pack(
        {
            "db_path": str(db_path),
            "query": "layered material",
            "k": 3,
            "embed_engine": "hash",
            "model": "hash-embed",
            "model_version": "v1",
            "text_engine": "caption",
            "text_view": "caption",
            "hybrid": True,
            "w_text": 0.7,
            "w_fp": 0.3,
            "redacted": True,
        }
    )
    validate(pack_payload, "csp_pack.v1")

    status_payload = mcp_server._tool_status(
        {
            "surface": "csp_pack",
            "db_path": str(db_path),
            "embed_engine": "hash",
            "model": "hash-embed",
            "model_version": "v1",
            "text_engine": "caption",
            "text_view": "caption",
            "hybrid": True,
        }
    )
    validate(status_payload, "backend_status.v1")

    novelty_payload = mcp_server._tool_novelty_check(
        {
            "db_path": str(db_path),
            "structure_id": "s-a",
            "k": 3,
            "embed_engine": "hash",
            "model": "hash-embed",
            "model_version": "v1",
        }
    )
    validate(novelty_payload, "novelty_check.v1")

    bench_payload = mcp_server._tool_bench_retrieval(
        {
            "db_path": str(db_path),
            "cases_path": str(cases_path),
            "k": 3,
            "embed_engine": "hash",
            "model": "hash-embed",
            "model_version": "v1",
            "text_engine": "caption",
            "text_view": "caption",
            "hybrid": True,
            "w_text": 0.7,
            "w_fp": 0.3,
            "redacted": True,
        }
    )
    validate(bench_payload, "bench_retrieval.v1")

    agent_payload = mcp_server._tool_agent(
        {
            "db_path": str(db_path),
            "question": "show structure s-a",
            "llm": "off",
        }
    )
    validate(agent_payload, "agent.v1")


def test_mcp_policy_mode_controls_demo_export(monkeypatch):
    monkeypatch.setenv("CRYSTALDB_POLICY_MODE", "safe")
    safe_settings = mcp_server._resolve_common_settings({"demo_export": True}, {})
    assert safe_settings["demo_export"] is False

    monkeypatch.setenv("CRYSTALDB_POLICY_MODE", "demo")
    demo_settings = mcp_server._resolve_common_settings({"demo_export": True}, {})
    assert demo_settings["demo_export"] is True


def test_mcp_hard_failure_raises_tool_error_and_rpc_error(tmp_path, monkeypatch):
    db_path = tmp_path / "empty.db"
    conn = connect(str(db_path))
    init_db(conn)
    conn.close()
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    arguments = {
        "db_path": str(db_path),
        "query": "any",
        "k": 3,
        "embed_engine": "hash",
        "model": "hash-embed",
        "model_version": "v1",
        "text_engine": "caption",
        "text_view": "caption",
    }
    with pytest.raises(mcp_server.ToolExecutionError) as exc_info:
        mcp_server.execute_tool("crystal.text_search", arguments)
    assert exc_info.value.code == "empty_corpus"
    assert exc_info.value.payload["errors"]["code"] == "empty_corpus"

    rpc_response = mcp_server._handle_rpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "crystal.text_search", "arguments": arguments},
        }
    )
    assert rpc_response is not None
    assert "error" in rpc_response
    assert rpc_response["error"]["data"]["payload"]["errors"]["code"] == "empty_corpus"
