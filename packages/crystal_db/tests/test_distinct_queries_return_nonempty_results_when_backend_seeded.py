import json

from crystal_db.db import connect, init_db
from crystal_db.retrieval import text_search


def _seed_distinct_query_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-04-09T00:00:00Z"
    rows = [
        ("rutile-1", "TiO2", "rutile titanium dioxide exemplar", [1.0, 0.0]),
        ("perovskite-1", "BaTiO3", "perovskite barium titanate exemplar", [0.0, 1.0]),
        ("mixed-1", "SrTiO3", "mixed titanate exemplar", [0.5, 0.5]),
    ]
    for sid, formula, text, vector in rows:
        conn.execute(
            "INSERT INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, f"data_{sid}\n_cell_length_a 1\n", formula, 1, 1.0, 0),
        )
        conn.execute(
            "INSERT INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, formula, ",Ti,O,", "P1", 0.1),
        )
        conn.execute(
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export) VALUES (?, ?, ?, ?, ?)",
            (sid, "test", sid, ts, 1),
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


def test_distinct_queries_return_nonempty_results_when_backend_seeded(tmp_path):
    db_path = tmp_path / "seeded.db"
    _seed_distinct_query_db(db_path)

    rutile = text_search(
        query_text="TiO2 rutile startup semantic probe",
        db_path=str(db_path),
        k=3,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        query_vector=[1.0, 0.0],
    )
    perovskite = text_search(
        query_text="BaTiO3 perovskite startup semantic probe",
        db_path=str(db_path),
        k=3,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        query_vector=[0.0, 1.0],
    )

    assert rutile["status"] == "ok"
    assert perovskite["status"] == "ok"
    assert rutile["neighbors"]
    assert perovskite["neighbors"]
    assert rutile["neighbors"][0]["structure_id"] == "rutile-1"
    assert perovskite["neighbors"][0]["structure_id"] == "perovskite-1"
