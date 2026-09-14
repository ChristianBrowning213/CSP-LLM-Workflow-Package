import json

from crystal_db.db import connect, init_db
from mcp_server import server as mcp_server


def _seed_ready_status_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-04-09T00:00:00Z"
    for sid, vector, fp in [
        ("ready-a", [1.0, 0.0], [1.0, 0.0]),
        ("ready-b", [0.0, 1.0], [0.0, 1.0]),
    ]:
        conn.execute(
            "INSERT INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, f"data_{sid}\n_cell_length_a 1\n", sid, 1, 1.0, 0),
        )
        conn.execute(
            "INSERT INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, sid, ",Ti,O,", "P1", 0.1),
        )
        conn.execute(
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export, allow_derivatives) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "test", sid, ts, 1, 1),
        )
        text_doc_id = conn.execute(
            "INSERT INTO text_docs "
            "(structure_id, engine, text_view, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "caption", "caption", "v1", f"text for {sid}", f"h-{sid}", "OK", None, None, ts, ts),
        ).lastrowid
        conn.execute(
            "INSERT INTO text_embeddings "
            "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (text_doc_id, "hash", "hash-embed", "v1", 2, json.dumps(vector), "OK", None, None, ts, ts),
        )
        conn.execute(
            "INSERT INTO structure_fingerprints "
            "(structure_id, fingerprint_method, fingerprint_version, vector_json, feature_names_json, input_hash, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, "fp.simple.v1", "v1", json.dumps(fp), json.dumps(["f1", "f2"]), f"fp-{sid}", ts),
        )
    conn.commit()
    conn.close()


def test_status_tool_reports_backend_readiness(tmp_path):
    db_path = tmp_path / "ready.db"
    _seed_ready_status_db(db_path)

    payload = mcp_server._tool_status(
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

    assert payload["ready"] is True
    assert payload["state"] == "backend_ready"
    assert payload["corpus"]["structure_count"] == 2
    assert payload["requested_space"]["embedding_ok_count"] == 2
    assert payload["fingerprint_index"]["present"] is True
