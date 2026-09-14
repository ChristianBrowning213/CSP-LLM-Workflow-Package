import json

from crystal_db.csp_pack import run_csp_pack
from crystal_db.db import connect, init_db


def _seed_csp_db_without_fingerprints(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-04-09T00:00:00Z"
    for sid, vector, text in [
        ("mat-a", [1.0, 0.0], "TiO2 rutile motif with octahedra"),
        ("mat-b", [0.0, 1.0], "BaTiO3 perovskite motif with corner-sharing octahedra"),
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
            (sid, "caption", "caption", "v1", text, f"h-{sid}", "OK", None, None, ts, ts),
        ).lastrowid
        conn.execute(
            "INSERT INTO text_embeddings "
            "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (text_doc_id, "hash", "hash-embed", "v1", 2, json.dumps(vector), "OK", None, None, ts, ts),
        )
    conn.commit()
    conn.close()


def test_csp_pack_reports_missing_index_truthfully(tmp_path):
    db_path = tmp_path / "missing_index.db"
    _seed_csp_db_without_fingerprints(db_path)

    result = run_csp_pack(
        db_path=str(db_path),
        query_text="BaTiO3 perovskite startup semantic probe",
        structure_id=None,
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        w_text=0.7,
        w_fp=0.3,
    )

    assert result["status"] == "error"
    assert result["errors"]["code"] == "missing_index"
    assert result["backend_status"]["state"] == "missing_index"
    assert result["backend_status"]["fingerprint_index"]["present"] is False
