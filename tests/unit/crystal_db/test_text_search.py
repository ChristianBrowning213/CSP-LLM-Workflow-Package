import json
import urllib.error

from crystal_db.api import retrieve_text
from crystal_db.db import connect, init_db, resolve_db_path
from crystal_db.retrieval import text_search


def _seed(db_path, *, engine="hash", model="hash-embed", version="v1"):
    conn = connect(str(db_path))
    init_db(conn)
    rows = [
        ("synthetic-alpha", 1, "ABO3 corner-sharing perovskite", [1.0, 0.0]),
        ("synthetic-beta", 1, "ABO3 distorted oxide analogue", [0.8, 0.2]),
        ("synthetic-restricted", 0, "restricted oxide reference", [0.0, 1.0]),
    ]
    for sid, allow_export, text, vector in rows:
        cif = "\n".join([
            f"data_{sid}", "_cell_length_a 4.0", "_cell_length_b 4.0",
            "_cell_length_c 4.0", "_cell_angle_alpha 90",
            "_cell_angle_beta 90", "_cell_angle_gamma 90",
        ])
        conn.execute(
            "INSERT INTO structures VALUES (?, ?, ?, ?, ?, ?)",
            (sid, cif, "ABO3", 5, 64.0, int(not allow_export)),
        )
        conn.execute(
            "INSERT INTO metadata VALUES (?, ?, ?, ?, ?)",
            (sid, "ABO3", ",A,B,O,", "Pm-3m", 1.0),
        )
        conn.execute(
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export, allow_derivatives) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "synthetic-test", sid, "2026-01-01T00:00:00Z", allow_export, 1),
        )
        doc_id = conn.execute(
            "INSERT INTO text_docs (structure_id, engine, text_view, engine_version, text, text_sha256, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "caption", "caption", "v1", text, f"hash-{sid}", "OK", "2026-01-01", "2026-01-01"),
        ).lastrowid
        conn.execute(
            "INSERT INTO text_embeddings (text_doc_id, embed_engine, model, model_version, dim, vector, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, engine, model, version, 2, json.dumps(vector), "OK", "2026-01-01", "2026-01-01"),
        )
    conn.commit()
    conn.close()


def test_database_root_contract(tmp_path, monkeypatch):
    root = tmp_path / "external-data"
    monkeypatch.setenv("CRYSTAL_DB_DATA_ROOT", str(root))
    monkeypatch.delenv("CRYSTAL_DB_PATH", raising=False)
    monkeypatch.delenv("CRYSTALDB_PATH", raising=False)
    assert resolve_db_path() == str((root / "crystal_phase0.db").resolve())
    assert resolve_db_path("indexes/demo.db") == str((root / "indexes/demo.db").resolve())


def test_ranking_schema_and_policy_gated_cif_export(tmp_path, monkeypatch):
    db_path = tmp_path / "synthetic.db"
    export_dir = tmp_path / "exports"
    _seed(db_path)
    result = text_search(
        query_text="synthetic perovskite", db_path=str(db_path), k=3,
        embed_engine="hash", model_name="hash-embed", model_version="v1",
        text_engine="caption", text_view="caption", query_vector=[1.0, 0.0],
        export_dir=str(export_dir), export_top=3, redacted=True,
    )
    assert result["status"] == "ok"
    assert [item["structure_id"] for item in result["neighbors"][:2]] == [
        "synthetic-alpha", "synthetic-beta"
    ]
    scores = [item["score"] for item in result["neighbors"]]
    assert scores == sorted(scores, reverse=True)
    first = result["neighbors"][0]
    assert first["provenance"]["source"] == "synthetic-test"
    assert first["provenance"]["source_id"] == "synthetic-alpha"
    conn = connect(str(db_path))
    record = conn.execute(
        "SELECT m.formula, p.source, p.source_id FROM metadata m "
        "JOIN provenance p ON p.structure_id = m.structure_id WHERE m.structure_id = ?",
        ("synthetic-alpha",),
    ).fetchone()
    conn.close()
    assert dict(record) == {
        "formula": "ABO3", "source": "synthetic-test", "source_id": "synthetic-alpha"
    }
    blocked = next(item for item in result["neighbors"] if item["structure_id"] == "synthetic-restricted")
    assert blocked["cif_export"]["status"] == "blocked"
    assert (export_dir / "synthetic-alpha.cif").exists()
    assert not (export_dir / "synthetic-restricted.cif").exists()

    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])
    api_payload = retrieve_text(
        str(db_path), "synthetic perovskite", k=2, embed_engine="hash",
        model="hash-embed", model_version="v1", text_engine="caption",
        text_view="caption",
    )
    assert api_payload["status"] == "ok"
    assert api_payload["schema_version"] == "text_search.v1"


def test_mocked_embedding_request_drives_ranked_text_retrieval(tmp_path, monkeypatch):
    db_path = tmp_path / "mocked-lmstudio.db"
    _seed(db_path, engine="lmstudio", model="text-embedding-bge-m3", version="lmstudio_v1")
    seen = {}

    def fake_urlopen(request, timeout=0):
        seen["url"] = request.full_url
        seen["payload"] = json.loads(request.data.decode("utf-8"))

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"data": [{"index": 0, "embedding": [1.0, 0.0]}]}).encode()

        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = text_search(
        query_text="corner-sharing oxide", db_path=str(db_path), k=2,
        embed_engine="lmstudio", model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1", text_engine="caption", text_view="caption",
    )
    assert seen["url"].endswith("/v1/embeddings")
    assert seen["payload"] == {
        "model": "text-embedding-bge-m3", "input": ["corner-sharing oxide"]
    }
    assert result["neighbors"][0]["structure_id"] == "synthetic-alpha"


def test_lmstudio_failure_is_deferred_until_retrieval(tmp_path, monkeypatch):
    db_path = tmp_path / "lmstudio.db"
    _seed(db_path, engine="lmstudio", model="text-embedding-bge-m3", version="lmstudio_v1")

    def unavailable(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    result = text_search(
        query_text="probe", db_path=str(db_path), k=2, embed_engine="lmstudio",
        model_name="text-embedding-bge-m3", model_version="lmstudio_v1",
        text_engine="caption", text_view="caption",
    )
    assert result["status"] == "error"
    assert result["errors"]["code"] == "query_embedding_failed"
    assert "CRYSTALDB_EMBED_BASE_URL" in result["errors"]["remediation"]["env_vars"]


def test_embedding_dimension_mismatch_stops_before_similarity(tmp_path, monkeypatch):
    db_path = tmp_path / "dimension-mismatch.db"
    _seed(db_path)
    monkeypatch.setattr(
        "crystal_db.retrieval._cosine_similarity",
        lambda *args: (_ for _ in ()).throw(AssertionError("similarity must not run")),
    )

    result = text_search(
        query_text="probe",
        db_path=str(db_path),
        k=2,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        query_vector=[1.0, 0.0, 0.0],
    )

    assert result["status"] == "error"
    assert result["errors"]["code"] == "candidate_vectors_unusable"
    assert result["errors"]["diagnostics"]["dim_mismatch"] == 3
