from crystal_db.db import connect, init_db
from crystal_db.retrieval import text_search


def test_text_search_reports_missing_db_truthfully(tmp_path):
    db_path = tmp_path / "missing.db"

    result = text_search(
        query_text="TiO2 rutile startup semantic probe",
        db_path=str(db_path),
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
    )

    assert result["status"] == "error"
    assert result["errors"]["code"] == "missing_db"
    assert result["backend_status"]["state"] == "missing_db"
    assert result["backend_status"]["db_exists"] is False


def test_text_search_reports_empty_corpus_truthfully(tmp_path):
    db_path = tmp_path / "empty.db"
    conn = connect(str(db_path))
    init_db(conn)
    conn.close()

    result = text_search(
        query_text="BaTiO3 perovskite startup semantic probe",
        db_path=str(db_path),
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
    )

    assert result["status"] == "error"
    assert result["errors"]["code"] == "empty_corpus"
    assert result["backend_status"]["state"] == "empty_corpus"
    assert result["backend_status"]["corpus"]["structure_count"] == 0
