import json

from crystal_db.csp_pack import run_csp_pack
from crystal_db.db import connect, init_db


def _seed(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    for sid, allow_export, vector in [
        ("synthetic-alpha", 1, [1.0, 0.0]),
        ("synthetic-beta", 1, [0.8, 0.2]),
        ("synthetic-restricted", 0, [0.0, 1.0]),
    ]:
        conn.execute(
            "INSERT INTO structures VALUES (?, ?, ?, ?, ?, ?)",
            (sid, f"data_{sid}\n_cell_length_a 4.0\n", "TiO2", 3, 64.0, int(not allow_export)),
        )
        conn.execute(
            "INSERT INTO metadata VALUES (?, ?, ?, ?, ?)",
            (sid, "TiO2", ",O,Ti,", "P1", 1.0),
        )
        conn.execute(
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export, allow_derivatives) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "synthetic-test", sid, "2026-01-01", allow_export, 1),
        )
        doc_id = conn.execute(
            "INSERT INTO text_docs (structure_id, engine, text_view, engine_version, text, text_sha256, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "caption", "caption", "v1", "oxide evidence", sid, "OK", "2026-01-01", "2026-01-01"),
        ).lastrowid
        conn.execute(
            "INSERT INTO text_embeddings (text_doc_id, embed_engine, model, model_version, dim, vector, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, "hash", "hash-embed", "v1", 2, json.dumps(vector), "OK", "2026-01-01", "2026-01-01"),
        )
    conn.commit()
    conn.close()


def test_csp_pack_writes_schema_evidence_and_allowed_cifs(tmp_path, monkeypatch):
    db_path = tmp_path / "synthetic.db"
    out_dir = tmp_path / "pack"
    _seed(db_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])
    result = run_csp_pack(
        db_path=str(db_path), query_text="corner-sharing oxide", structure_id=None, k=3,
        embed_engine="hash", model_name="hash-embed", model_version="v1",
        text_engine="caption", text_view="caption", hybrid=False,
        out_dir=str(out_dir), export_top=3, redacted=True, demo_export=False,
    )
    assert result["status"] == "ok"
    assert result["neighbors"][0]["provenance"]["source"] == "synthetic-test"
    assert (out_dir / "manifest.json").exists()
    written = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert written["run_id"] == result["run_id"]
    exported = {item["structure_id"]: item["export_status"] for item in result["export"]["items"]}
    assert exported["synthetic-alpha"] == "exported"
    assert exported["synthetic-restricted"] == "blocked"
