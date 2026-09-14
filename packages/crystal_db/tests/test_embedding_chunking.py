import json

import pytest

from crystal_db.db import connect, init_db
from crystal_db.embeddings import EmbeddingDocumentError, chunk_text_for_embedding, embed_document_text
from crystal_db.ingest import ingest_sample
from crystal_db.text_index import embed_text_docs, generate_text_docs


def _vector_for_text(text: str):
    return [float(len(text)), float(sum(ord(ch) for ch in text) % 997), float(len(set(text)))]


def test_chunking_triggers_and_pools_weighted_mean(monkeypatch):
    long_text = ("Layered van der Waals system with corner-sharing octahedra. " * 240).strip()
    monkeypatch.setenv("CRYSTALDB_EMBED_MAX_CTX_TOKENS", "256")
    monkeypatch.setenv("CRYSTALDB_EMBED_CHUNK_OVERLAP_TOKENS", "16")
    monkeypatch.setenv("CRYSTALDB_EMBED_CHUNKING", "true")

    def fake_embed_texts(texts, model_name=None, model_version=None, dim=64, embed_engine=None):  # noqa: ARG001
        return [_vector_for_text(text) for text in texts]

    monkeypatch.setattr("crystal_db.embeddings.embed_texts", fake_embed_texts)

    chunks = chunk_text_for_embedding(long_text, max_ctx_tokens=256, overlap_tokens=16)
    vector, meta = embed_document_text(long_text, model_name="hash-embed", model_version="v1", embed_engine="hash")
    assert len(chunks) > 1
    assert meta["chunk_count"] == len(chunks)
    weights = [int(chunk["weight_tokens"]) for chunk in chunks]
    vectors = [_vector_for_text(chunk["text"]) for chunk in chunks]
    denom = float(sum(weights))
    expected = [
        sum(v[idx] * float(w) for v, w in zip(vectors, weights)) / denom
        for idx in range(len(vectors[0]))
    ]
    assert vector == expected


def test_short_text_no_chunking(monkeypatch):
    short_text = "Short crystal summary."
    monkeypatch.setenv("CRYSTALDB_EMBED_MAX_CTX_TOKENS", "4096")
    monkeypatch.setenv("CRYSTALDB_EMBED_CHUNKING", "true")

    def fake_embed_texts(texts, model_name=None, model_version=None, dim=64, embed_engine=None):  # noqa: ARG001
        return [_vector_for_text(text) for text in texts]

    monkeypatch.setattr("crystal_db.embeddings.embed_texts", fake_embed_texts)
    vector, meta = embed_document_text(short_text, model_name="hash-embed", model_version="v1", embed_engine="hash")
    assert meta["chunk_count"] == 1
    assert vector == _vector_for_text(short_text)


def test_strict_mode_failure_for_long_text(monkeypatch):
    long_text = "A" * 8000
    monkeypatch.setenv("CRYSTALDB_EMBED_MAX_CTX_TOKENS", "512")
    monkeypatch.setenv("CRYSTALDB_EMBED_CHUNKING", "false")
    with pytest.raises(EmbeddingDocumentError) as exc:
        embed_document_text(long_text, model_name="hash-embed", model_version="v1", embed_engine="hash")
    payload = exc.value.to_payload()
    assert payload["code"] == "text_too_long_for_context"
    assert payload["diagnostics"]["max_ctx_tokens"] == 512
    assert payload["diagnostics"]["estimated_tokens"] > 512


def test_embedding_pipeline_integration_one_row_per_doc(monkeypatch, tmp_path):
    db_path = tmp_path / "chunk_pipeline.db"
    ingest_sample(db_path=str(db_path), count=2)

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="robocrys", db_path=None):  # noqa: ARG001
        if structure_id == "crystal-0001":
            return {"engine": engine, "version": "v1", "text": "short robocrys text", "input_hash": "h1"}
        long_text = ("Long robocrys dump with layered motifs and octahedra connectivity. " * 260).strip()
        return {"engine": engine, "version": "v1", "text": long_text, "input_hash": "h2"}

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        payload = json.loads(req.data.decode("utf-8"))
        inputs = payload.get("input", [])
        data = [{"index": idx, "embedding": _vector_for_text(text)} for idx, text in enumerate(inputs)]
        body = json.dumps({"data": data}).encode("utf-8")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                return False

            def read(self):
                return body

        return _Resp()

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("CRYSTALDB_EMBED_MAX_CTX_TOKENS", "256")
    monkeypatch.setenv("CRYSTALDB_EMBED_CHUNK_OVERLAP_TOKENS", "16")
    monkeypatch.setenv("CRYSTALDB_EMBED_CHUNKING", "true")
    monkeypatch.setenv("CRYSTALDB_EMBED_MAX_ITEMS_PER_REQUEST", "8")
    monkeypatch.setenv("CRYSTALDB_EMBED_MAX_TOTAL_TOKENS_PER_REQUEST", "12000")

    generate_text_docs(
        db_path=str(db_path),
        engine="robocrys",
        text_view="robocrys",
        batch=2,
        progress_every=100,
    )
    result = embed_text_docs(
        db_path=str(db_path),
        text_engine="robocrys",
        text_view="robocrys",
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        batch=2,
        progress_every=100,
    )
    assert result["ok"] == 2
    assert result["failed"] == 0

    conn = connect(str(db_path))
    init_db(conn)
    rows = conn.execute(
        "SELECT td.structure_id, te.status "
        "FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        "WHERE td.engine = 'robocrys' AND td.text_view = 'robocrys' "
        "AND te.embed_engine = 'lmstudio' AND te.model = 'text-embedding-bge-m3' AND te.model_version = 'lmstudio_v1' "
        "ORDER BY td.structure_id",
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert all(row["status"] == "OK" for row in rows)


def test_chunking_determinism(monkeypatch):
    text = ("Deterministic chunking test sentence. " * 220).strip()
    monkeypatch.setenv("CRYSTALDB_EMBED_MAX_CTX_TOKENS", "256")
    monkeypatch.setenv("CRYSTALDB_EMBED_CHUNK_OVERLAP_TOKENS", "16")
    monkeypatch.setenv("CRYSTALDB_EMBED_CHUNKING", "true")
    chunks_a = chunk_text_for_embedding(text, max_ctx_tokens=256, overlap_tokens=16)
    chunks_b = chunk_text_for_embedding(text, max_ctx_tokens=256, overlap_tokens=16)
    assert chunks_a == chunks_b

    vec_a, meta_a = embed_document_text(text, model_name="hash-embed", model_version="v1", embed_engine="hash")
    vec_b, meta_b = embed_document_text(text, model_name="hash-embed", model_version="v1", embed_engine="hash")
    assert meta_a == meta_b
    assert vec_a == vec_b


def test_embed_text_docs_strict_mode_records_structured_error(monkeypatch, tmp_path):
    db_path = tmp_path / "strict_mode.db"
    ingest_sample(db_path=str(db_path), count=1)

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="robocrys", db_path=None):  # noqa: ARG001
        long_text = ("Very long robocrys text with connectivity cues. " * 500).strip()
        return {"engine": engine, "version": "v1", "text": long_text, "input_hash": "hx"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)
    generate_text_docs(
        db_path=str(db_path),
        engine="robocrys",
        text_view="robocrys",
        batch=1,
        progress_every=100,
    )
    monkeypatch.setenv("CRYSTALDB_EMBED_MAX_CTX_TOKENS", "256")
    monkeypatch.setenv("CRYSTALDB_EMBED_CHUNKING", "false")
    result = embed_text_docs(
        db_path=str(db_path),
        text_engine="robocrys",
        text_view="robocrys",
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        batch=1,
        progress_every=100,
    )
    assert result["ok"] == 0
    assert result["failed"] == 1
    conn = connect(str(db_path))
    init_db(conn)
    row = conn.execute(
        "SELECT te.error_message FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        "WHERE td.structure_id = ? AND te.status = 'FAILED'",
        ("crystal-0001",),
    ).fetchone()
    conn.close()
    payload = json.loads(row["error_message"])
    assert payload["code"] == "text_too_long_for_context"
    assert payload["diagnostics"]["structure_id"] == "crystal-0001"
    assert payload["diagnostics"]["text_engine"] == "robocrys"
