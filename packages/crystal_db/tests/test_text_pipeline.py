import json
import hashlib
import urllib.error
from pathlib import Path

from crystal_db.__main__ import main
from crystal_db.db import connect, init_db
from crystal_db.ingest import ingest_sample
from crystal_db.text_index import embed_text_docs, generate_text_docs
from crystal_db.textgen import generate_robocrys


def test_generate_robocrys_persists_condensed_and_prose_once(tmp_path, monkeypatch):
    db_path = tmp_path / "robocrys.db"
    structure_id = ingest_sample(db_path=str(db_path), count=1)[0]
    fixture_path = Path(__file__).resolve().parents[1] / "demo_cifs" / "mp-0a7fd0c9.cif"
    cif_text = fixture_path.read_text(encoding="utf-8")
    conn = connect(str(db_path))
    conn.execute(
        "UPDATE structures SET cif_text = ? WHERE structure_id = ?",
        (cif_text, structure_id),
    )
    conn.commit()
    conn.close()

    from robocrys import StructureCondenser

    original = StructureCondenser.condense_structure
    calls = {"count": 0}

    def counted_condense(self, structure):
        calls["count"] += 1
        return original(self, structure)

    monkeypatch.setattr(StructureCondenser, "condense_structure", counted_condense)

    result = generate_robocrys(structure_id=structure_id, db_path=str(db_path))

    assert "error" not in result
    assert calls["count"] == 1
    assert result["text"]
    assert isinstance(result["condensed"], dict)
    conn = connect(str(db_path))
    row = conn.execute(
        "SELECT condensed_json, condensed_sha256, description_sha256 "
        "FROM robocrys_condensed WHERE structure_id = ?",
        (structure_id,),
    ).fetchone()
    text_row = conn.execute(
        "SELECT text, text_sha256, status FROM text_docs "
        "WHERE structure_id = ? AND engine = 'robocrys' AND text_view = 'robocrys'",
        (structure_id,),
    ).fetchone()
    conn.close()
    assert json.loads(row["condensed_json"]) == result["condensed"]
    assert row["condensed_sha256"] == result["condensed_sha256"]
    assert row["description_sha256"] == result["description_sha256"]
    assert text_row["text"] == result["text"]
    assert text_row["text_sha256"] == result["description_sha256"]
    assert text_row["status"] == "OK"


def test_generate_text_docs_resume_and_retry_failed(monkeypatch, tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=4)

    attempts = {"crystal-0002": 0}

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="baseline", db_path=None):  # noqa: ARG001
        if structure_id == "crystal-0002":
            attempts["crystal-0002"] += 1
            raise RuntimeError("2D components don't all have the same orientation")
        return {"engine": engine, "version": "v1", "text": f"text for {structure_id}", "input_hash": "h"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)

    first = generate_text_docs(
        db_path=str(db_path),
        engine="robocrys",
        batch=2,
        progress_every=100,
    )
    assert first["selected"] == 4
    assert first["ok"] == 3
    assert first["failed"] == 1
    assert attempts["crystal-0002"] == 1

    conn = connect(str(db_path))
    init_db(conn)
    failed = conn.execute(
        "SELECT status, error_type FROM text_docs WHERE structure_id = ? AND engine = ? AND engine_version = ?",
        ("crystal-0002", "robocrys", "v1"),
    ).fetchone()
    conn.close()
    assert failed["status"] == "FAILED"
    assert failed["error_type"] == "ROBOCRYS_VDW_ORIENTATION"

    second = generate_text_docs(
        db_path=str(db_path),
        engine="robocrys",
        batch=2,
        progress_every=100,
    )
    assert second["selected"] == 0
    assert attempts["crystal-0002"] == 1

    def fake_generate_text_retry(*, structure_id=None, cif_text=None, engine="baseline", db_path=None):  # noqa: ARG001
        return {"engine": engine, "version": "v1", "text": f"text for {structure_id}", "input_hash": "h2"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text_retry)
    third = generate_text_docs(
        db_path=str(db_path),
        engine="robocrys",
        retry_failed=True,
        batch=2,
        progress_every=100,
    )
    assert third["selected"] == 1
    assert third["ok"] == 1
    assert third["failed"] == 0

    conn = connect(str(db_path))
    init_db(conn)
    recovered = conn.execute(
        "SELECT status, text FROM text_docs WHERE structure_id = ? AND engine = ? AND engine_version = ?",
        ("crystal-0002", "robocrys", "v1"),
    ).fetchone()
    conn.close()
    assert recovered["status"] == "OK"
    assert recovered["text"] == "text for crystal-0002"


def test_embed_text_docs_skips_existing_and_retries_failed(monkeypatch, tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=3)

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="baseline", db_path=None):  # noqa: ARG001
        return {"engine": engine, "version": "v1", "text": f"text-{structure_id}", "input_hash": "h"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)
    generate_text_docs(db_path=str(db_path), engine="baseline", batch=2, progress_every=100)

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        payload = json.loads(req.data.decode("utf-8"))
        inputs = payload.get("input", [])
        data = []
        for idx, text in enumerate(inputs):
            data.append({"index": idx, "embedding": [float(idx), float(len(text) % 17)]})
        body = json.dumps({"data": data}).encode("utf-8")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, D401
                return False

            def read(self):
                return body

        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    first = embed_text_docs(
        db_path=str(db_path),
        text_engine="baseline",
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version=None,
        batch=2,
        progress_every=100,
    )
    assert first["selected"] == 3
    assert first["ok"] == 3
    assert first["failed"] == 0

    second = embed_text_docs(
        db_path=str(db_path),
        text_engine="baseline",
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version=None,
        batch=2,
        progress_every=100,
    )
    assert second["selected"] == 0

    conn = connect(str(db_path))
    init_db(conn)
    row = conn.execute(
        "SELECT text_doc_id FROM text_embeddings WHERE status = 'OK' ORDER BY text_doc_id LIMIT 1",
    ).fetchone()
    conn.execute(
        "UPDATE text_embeddings SET status = 'FAILED', error_type = 'TEST', error_message = 'forced failure' WHERE text_doc_id = ?",
        (row["text_doc_id"],),
    )
    conn.commit()
    conn.close()

    third = embed_text_docs(
        db_path=str(db_path),
        text_engine="baseline",
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version=None,
        batch=2,
        progress_every=100,
    )
    assert third["selected"] == 0

    retry = embed_text_docs(
        db_path=str(db_path),
        text_engine="baseline",
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version=None,
        retry_failed=True,
        batch=2,
        progress_every=100,
    )
    assert retry["selected"] == 1
    assert retry["ok"] == 1
    assert retry["failed"] == 0


def test_embed_text_docs_failure_does_not_abort_batch(monkeypatch, tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=3)

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="baseline", db_path=None):  # noqa: ARG001
        if structure_id == "crystal-0002":
            return {"engine": engine, "version": "v1", "text": "bad-text", "input_hash": "b"}
        return {"engine": engine, "version": "v1", "text": f"ok-{structure_id}", "input_hash": "a"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)
    generate_text_docs(db_path=str(db_path), engine="baseline", batch=3, progress_every=100)

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        payload = json.loads(req.data.decode("utf-8"))
        inputs = payload.get("input", [])
        if len(inputs) > 1:
            raise urllib.error.URLError("batch failure")
        if inputs and inputs[0] == "bad-text":
            raise urllib.error.URLError("single failure")
        body = json.dumps({"data": [{"index": 0, "embedding": [1.0, 2.0]}]}).encode("utf-8")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                return False

            def read(self):
                return body

        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = embed_text_docs(
        db_path=str(db_path),
        text_engine="baseline",
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version=None,
        batch=3,
        progress_every=100,
    )
    assert result["selected"] == 3
    assert result["ok"] == 2
    assert result["failed"] == 1

    conn = connect(str(db_path))
    init_db(conn)
    ok_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM text_embeddings WHERE status = 'OK'",
    ).fetchone()["cnt"]
    failed_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM text_embeddings WHERE status = 'FAILED'",
    ).fetchone()["cnt"]
    conn.close()
    assert ok_count == 2
    assert failed_count == 1


def test_text_pipeline_sharding_is_deterministic(monkeypatch, tmp_path):
    db_path = tmp_path / "shard.db"
    ingest_sample(db_path=str(db_path), count=8)

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="baseline", db_path=None):  # noqa: ARG001
        return {"engine": engine, "version": "v1", "text": f"text-{structure_id}", "input_hash": "h"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)

    first = generate_text_docs(
        db_path=str(db_path),
        engine="baseline",
        shard_count=2,
        shard_index=0,
        batch=4,
        progress_every=100,
    )
    second = generate_text_docs(
        db_path=str(db_path),
        engine="baseline",
        shard_count=2,
        shard_index=1,
        batch=4,
        progress_every=100,
    )

    conn = connect(str(db_path))
    init_db(conn)
    rows = conn.execute(
        "SELECT structure_id FROM text_docs WHERE engine = 'baseline' AND text_view = 'robocrys' ORDER BY structure_id",
    ).fetchall()
    conn.close()

    expected_shard0 = 0
    expected_shard1 = 0
    for idx in range(1, 9):
        sid = f"crystal-{idx:04d}"
        shard = int(hashlib.sha256(sid.encode("utf-8")).hexdigest(), 16) % 2
        if shard == 0:
            expected_shard0 += 1
        else:
            expected_shard1 += 1

    assert first["selected"] == expected_shard0
    assert second["selected"] == expected_shard1
    assert len(rows) == 8


def test_text_pipeline_snapshots_written(monkeypatch, tmp_path):
    db_path = tmp_path / "snapshot.db"
    gen_snapshot = tmp_path / "gen_snapshot.json"
    embed_snapshot = tmp_path / "embed_snapshot.json"
    ingest_sample(db_path=str(db_path), count=4)

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="baseline", db_path=None):  # noqa: ARG001
        return {"engine": engine, "version": "v1", "text": f"text-{structure_id}", "input_hash": "h"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)

    gen = generate_text_docs(
        db_path=str(db_path),
        engine="baseline",
        batch=2,
        progress_every=100,
        snapshot_path=str(gen_snapshot),
        snapshot_every=2,
    )
    assert gen["processed"] == 4
    assert gen_snapshot.exists()
    gen_payload = json.loads(gen_snapshot.read_text(encoding="utf-8"))
    assert gen_payload["command"] == "gen-text"
    assert gen_payload["processed"] == 4
    assert gen_payload["last_text_doc_id"] is None

    embed = embed_text_docs(
        db_path=str(db_path),
        text_engine="baseline",
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        batch=2,
        progress_every=100,
        snapshot_path=str(embed_snapshot),
        snapshot_every=2,
    )
    assert embed["processed"] == 4
    assert embed_snapshot.exists()
    embed_payload = json.loads(embed_snapshot.read_text(encoding="utf-8"))
    assert embed_payload["command"] == "embed-text"
    assert embed_payload["processed"] == 4
    assert isinstance(embed_payload["last_text_doc_id"], int)


def test_embed_text_docs_sharding_aligns_by_structure_id(monkeypatch, tmp_path):
    db_path = tmp_path / "embed_shard.db"
    ingest_sample(db_path=str(db_path), count=6)

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="baseline", db_path=None):  # noqa: ARG001
        return {"engine": engine, "version": "v1", "text": f"text-{structure_id}", "input_hash": "h"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)
    generate_text_docs(db_path=str(db_path), engine="baseline", batch=3, progress_every=100)

    shard0 = embed_text_docs(
        db_path=str(db_path),
        text_engine="baseline",
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        shard_count=2,
        shard_index=0,
        batch=3,
        progress_every=100,
    )
    shard1 = embed_text_docs(
        db_path=str(db_path),
        text_engine="baseline",
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        shard_count=2,
        shard_index=1,
        batch=3,
        progress_every=100,
    )

    expected_shard0 = 0
    expected_shard1 = 0
    for idx in range(1, 7):
        sid = f"crystal-{idx:04d}"
        shard = int(hashlib.sha256(sid.encode("utf-8")).hexdigest(), 16) % 2
        if shard == 0:
            expected_shard0 += 1
        else:
            expected_shard1 += 1

    assert shard0["selected"] == expected_shard0
    assert shard1["selected"] == expected_shard1
    assert shard0["ok"] + shard1["ok"] == 6


def test_lmstudio_embed_retries_transient_failures(monkeypatch):
    calls = {"count": 0}

    def flaky_urlopen(req, timeout=0):  # noqa: ARG001
        calls["count"] += 1
        if calls["count"] < 3:
            raise urllib.error.URLError("temporary down")
        body = json.dumps({"data": [{"index": 0, "embedding": [0.5, 0.25]}]}).encode("utf-8")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                return False

            def read(self):
                return body

        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", flaky_urlopen)
    monkeypatch.setenv("CRYSTALDB_EMBED_RETRIES", "3")
    monkeypatch.setenv("CRYSTALDB_EMBED_BACKOFF_S", "0.001")

    from crystal_db.embeddings import embed_texts

    vectors = embed_texts(
        ["hello"],
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        embed_engine="lmstudio",
    )
    assert calls["count"] == 3
    assert vectors == [[0.5, 0.25]]


def test_invalid_shard_args_return_structured_error(tmp_path, capsys):
    db_path = tmp_path / "invalid_shard.db"
    ingest_sample(db_path=str(db_path), count=2)
    code = main(
        [
            "gen-text",
            "--db",
            str(db_path),
            "--engine",
            "baseline",
            "--shard-count",
            "1",
            "--shard-index",
            "1",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.err)
    assert payload["error"] == "invalid_arguments"
    assert payload["command"] == "gen-text"
