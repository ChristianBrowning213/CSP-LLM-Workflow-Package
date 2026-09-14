import json

from crystal_db.__main__ import main
from crystal_db.ingest import ingest_sample
from crystal_db.retrieval import similar_text
from crystal_db.text_index import embed_text_docs, generate_text_docs


def _prepare_text_docs(db_path, monkeypatch):
    def fake_generate_text(*, structure_id=None, cif_text=None, engine="baseline", db_path=None):  # noqa: ARG001
        sid = structure_id or "unknown"
        return {"engine": engine, "version": "v1", "text": f"text-{sid}", "input_hash": f"h-{sid}"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)
    generate_text_docs(
        db_path=str(db_path),
        engine="baseline",
        batch=8,
        progress_every=1000,
    )


def _embed_hash_space(db_path, *, structure_ids=None, model_version="v1"):
    return embed_text_docs(
        db_path=str(db_path),
        text_engine="baseline",
        embed_engine="hash",
        model_name="hash-embed",
        model_version=model_version,
        structure_ids=structure_ids,
        batch=8,
        progress_every=1000,
    )


def test_similar_text_returns_neighbors_for_existing_space(tmp_path, monkeypatch):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=5)
    _prepare_text_docs(db_path, monkeypatch)
    result = _embed_hash_space(db_path, model_version="v1")
    assert result["ok"] >= 3

    response = similar_text(
        structure_id="crystal-0001",
        db_path=str(db_path),
        k=3,
        engine="hash",
        model_name="hash-embed",
        model_version="v1",
    )
    assert "error" not in response
    assert response["query"]["model_version"] == "v1"
    assert response["query"]["embed_engine"] == "hash"
    assert len(response["neighbors"]) > 0


def test_similar_text_missing_query_embedding_exits_nonzero(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=4)
    _prepare_text_docs(db_path, monkeypatch)
    _embed_hash_space(
        db_path,
        structure_ids=["crystal-0002", "crystal-0003", "crystal-0004"],
        model_version="v1",
    )

    exit_code = main(
        [
            "similar-text",
            "--db",
            str(db_path),
            "--id",
            "crystal-0001",
            "--engine",
            "hash",
            "--model",
            "hash-embed",
            "--model-version",
            "v1",
        ]
    )
    captured = capsys.readouterr()
    error_payload = json.loads(captured.err.strip())

    assert exit_code == 1
    assert error_payload["error"] == "query_embedding_missing"
    assert error_payload["diagnostics"]["query_embedding_found"] is False
    assert error_payload["diagnostics"]["table_used"] == "text_embeddings"
    assert error_payload["diagnostics"]["candidate_count"] > 0
    assert "embed-text" in error_payload["remediation"]["commands"][1]


def test_similar_text_empty_candidate_set_exits_nonzero(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=1)
    _prepare_text_docs(db_path, monkeypatch)
    _embed_hash_space(db_path, model_version="v1")

    exit_code = main(
        [
            "similar-text",
            "--db",
            str(db_path),
            "--id",
            "crystal-0001",
            "--engine",
            "hash",
            "--model",
            "hash-embed",
            "--model-version",
            "v1",
        ]
    )
    captured = capsys.readouterr()
    error_payload = json.loads(captured.err.strip())

    assert exit_code == 1
    assert error_payload["error"] == "candidate_set_empty"
    assert error_payload["diagnostics"]["query_embedding_found"] is True
    assert error_payload["diagnostics"]["candidate_count"] == 0
    assert error_payload["diagnostics"]["table_used"] == "text_embeddings"


def test_similar_text_model_version_filters_embedding_space(tmp_path, monkeypatch):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=5)
    _prepare_text_docs(db_path, monkeypatch)
    _embed_hash_space(db_path, model_version="v1")
    _embed_hash_space(db_path, structure_ids=["crystal-0001", "crystal-0002"], model_version="v2")

    v2_response = similar_text(
        structure_id="crystal-0001",
        db_path=str(db_path),
        k=10,
        engine="hash",
        model_name="hash-embed",
        model_version="v2",
    )
    assert "error" not in v2_response
    v2_neighbors = [item["structure_id"] for item in v2_response["neighbors"]]
    assert v2_neighbors == ["crystal-0002"]

    v1_response = similar_text(
        structure_id="crystal-0001",
        db_path=str(db_path),
        k=10,
        engine="hash",
        model_name="hash-embed",
        model_version="v1",
    )
    assert "error" not in v1_response
    v1_neighbors = [item["structure_id"] for item in v1_response["neighbors"]]
    assert "crystal-0003" in v1_neighbors
