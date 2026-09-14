from crystal_db.ingest import ingest_sample
from crystal_db.query import get_structure, query_structures


def test_ingest_query_returns_results(tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=25)

    result = query_structures({"limit": 5}, db_path=str(db_path))
    assert result["total_matches"] >= 1
    assert len(result["results"]) >= 1


def test_get_structure_returns_cif(tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=25)

    structure = get_structure("crystal-0001", db_path=str(db_path))
    assert "error" not in structure
    assert structure["restricted"] is False
    assert structure["cif_text"] is not None
