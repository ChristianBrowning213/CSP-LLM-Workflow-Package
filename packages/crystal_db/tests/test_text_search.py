import json
import urllib.error

from crystal_db.__main__ import main
from crystal_db.db import connect, init_db
from crystal_db.retrieval import text_search


def _seed_text_search_db(db_path, *, with_embeddings=True):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    rows = [
        ("crystal-a", 1, [1.0, 0.0, 0.0], "robocrys text A"),
        ("crystal-b", 1, [0.8, 0.2, 0.0], "robocrys text B"),
        ("crystal-c", 0, [0.0, 1.0, 0.0], "robocrys text C"),
    ]
    for sid, allow_export, vector, text in rows:
        conn.execute(
            "INSERT INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, f"data_{sid}\n_cell_length_a 1\n", "X", 1, 1.0, 0),
        )
        conn.execute(
            "INSERT INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, "X", ",X,", "P1", 0.1),
        )
        conn.execute(
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export) VALUES (?, ?, ?, ?, ?)",
            (sid, "test", f"{sid}.cif", ts, allow_export),
        )
        cursor = conn.execute(
            "INSERT INTO text_docs "
            "(structure_id, engine, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "robocrys", "v1", text, f"h-{sid}", "OK", None, None, ts, ts),
        )
        if with_embeddings:
            conn.execute(
                "INSERT INTO text_embeddings "
                "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cursor.lastrowid,
                    "lmstudio",
                    "text-embedding-bge-m3",
                    "lmstudio_v1",
                    3,
                    json.dumps(vector),
                    "OK",
                    None,
                    None,
                    ts,
                    ts,
                ),
            )
    conn.commit()
    conn.close()


def _mock_lmstudio_embed(monkeypatch, vector):
    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        payload = json.loads(req.data.decode("utf-8"))
        inputs = payload.get("input", [])
        data = [{"index": idx, "embedding": vector} for idx, _ in enumerate(inputs)]
        body = json.dumps({"data": data}).encode("utf-8")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                return False

            def read(self):
                return body

        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def test_text_search_returns_neighbors_and_text_and_exports(tmp_path, monkeypatch):
    db_path = tmp_path / "crystal.db"
    export_dir = tmp_path / "exports"
    _seed_text_search_db(db_path)
    _mock_lmstudio_embed(monkeypatch, [1.0, 0.0, 0.0])

    result = text_search(
        query_text="find structures like crystal a",
        db_path=str(db_path),
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        text_engine="robocrys",
        show_text_top=2,
        export_dir=str(export_dir),
        export_top=3,
        redacted=True,
    )

    assert result["errors"] is None
    assert len(result["neighbors"]) == 3
    assert result["neighbors"][0]["score"] >= result["neighbors"][1]["score"]
    assert result["neighbors"][0]["text_doc"]["status"] == "ok"
    assert "text" in result["neighbors"][0]["text_doc"]
    assert result["neighbors"][1]["text_doc"]["status"] == "ok"
    assert "text_doc" not in result["neighbors"][2]

    blocked = [item for item in result["neighbors"] if item["structure_id"] == "crystal-c"][0]
    assert blocked["cif_export"]["status"] == "blocked"
    assert "demo_export=false" in blocked["cif_export"]["error"]
    assert (export_dir / "crystal-a.cif").exists()
    assert not (export_dir / "crystal-c.cif").exists()

    export_dir_demo = tmp_path / "exports_demo"
    result_demo = text_search(
        query_text="find structures like crystal a",
        db_path=str(db_path),
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        text_engine="robocrys",
        show_text_top=0,
        export_dir=str(export_dir_demo),
        export_top=3,
        redacted=False,
        demo_export=True,
    )
    assert result_demo["errors"] is None
    assert (export_dir_demo / "crystal-c.cif").exists()


def test_text_search_empty_candidate_set_exits_nonzero(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "crystal.db"
    _seed_text_search_db(db_path, with_embeddings=False)
    _mock_lmstudio_embed(monkeypatch, [1.0, 0.0, 0.0])

    exit_code = main(
        [
            "text-search",
            "--db",
            str(db_path),
            "--query",
            "query text",
            "--engine",
            "lmstudio",
            "--model",
            "text-embedding-bge-m3",
            "--model-version",
            "lmstudio_v1",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip())

    assert exit_code == 1
    assert payload["errors"]["code"] == "missing_embedding_space"
    assert payload["backend_status"]["state"] == "missing_embedding_space"
    assert payload["backend_status"]["requested_space"]["text_doc_ok_count"] == 3
    assert payload["backend_status"]["requested_space"]["embedding_ok_count"] == 0


def test_text_search_query_embedding_failure_exits_nonzero(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "crystal.db"
    _seed_text_search_db(db_path, with_embeddings=True)

    def failing_urlopen(req, timeout=0):  # noqa: ARG001
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)

    exit_code = main(
        [
            "text-search",
            "--db",
            str(db_path),
            "--query",
            "query text",
            "--engine",
            "lmstudio",
            "--model",
            "text-embedding-bge-m3",
            "--model-version",
            "lmstudio_v1",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip())

    assert exit_code == 1
    assert payload["errors"]["code"] == "query_embedding_failed"
    assert "CRYSTALDB_EMBED_BASE_URL" in payload["errors"]["remediation"]["env_vars"]


def test_text_search_pretty_output_and_open_cifs_with_vesta(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "crystal.db"
    export_dir = tmp_path / "exports"
    _seed_text_search_db(db_path, with_embeddings=True)
    _mock_lmstudio_embed(monkeypatch, [1.0, 0.0, 0.0])

    opened = []

    def fake_run(args, check=False):  # noqa: ARG001
        opened.append(list(args))

        class _Done:
            returncode = 0

        return _Done()

    monkeypatch.setattr("subprocess.run", fake_run)

    exit_code = main(
        [
            "text-search",
            "--db",
            str(db_path),
            "--query",
            "query text",
            "--engine",
            "lmstudio",
            "--model",
            "text-embedding-bge-m3",
            "--model-version",
            "lmstudio_v1",
            "--export-cifs",
            str(export_dir),
            "--export-top",
            "1",
            "--format",
            "pretty",
            "--open-cifs",
            "--vesta",
            "C:\\Tools\\VESTA.exe",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "1. crystal-a" in captured.out
    assert "provenance:" in captured.out
    assert opened
    assert opened[0][0] == "C:\\Tools\\VESTA.exe"
    assert opened[0][1].endswith(".cif")
