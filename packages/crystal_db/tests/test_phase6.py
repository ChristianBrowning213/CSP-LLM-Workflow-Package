import json
from pathlib import Path

from crystal_db.db import connect, init_db
from crystal_db.ingest import ingest_sample
from crystal_db.ingest_folder import ingest_folder
from crystal_db.text_index import embed_texts
from crystal_db.sequence_index import encode_sequences, embed_sequences
from crystal_db.retrieval import similar_text, similar_seq, similar_hybrid
from eval_phase6 import run_eval_phase6


def _make_cif(path: Path, formula: str, tag: str) -> None:
    text = (
        f"data_{tag}\n"
        "_symmetry_space_group_name_H-M 'P1'\n"
        "_cell_length_a 5.0\n"
        "_cell_length_b 5.0\n"
        "_cell_length_c 5.0\n"
        "_cell_angle_alpha 90\n"
        "_cell_angle_beta 90\n"
        "_cell_angle_gamma 90\n"
        f"_chemical_formula_sum '{formula}'\n"
    )
    path.write_text(text, encoding="utf-8")


def test_embeddings_and_sequences(tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=6)

    embed_texts(db_path=str(db_path), engine="baseline")
    encode_sequences(db_path=str(db_path), format="cif_canon")
    embed_sequences(db_path=str(db_path), format="cif_canon")

    conn = connect(str(db_path))
    init_db(conn)
    text_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM structure_embeddings WHERE modality = 'text'",
    ).fetchone()["cnt"]
    seq_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM structure_embeddings WHERE modality = 'seq'",
    ).fetchone()["cnt"]
    assert text_count > 0
    assert seq_count > 0

    seq_row = conn.execute(
        "SELECT input_hash FROM structure_sequences ORDER BY structure_id LIMIT 1",
    ).fetchone()
    conn.close()

    encode_sequences(db_path=str(db_path), format="cif_canon")
    conn = connect(str(db_path))
    init_db(conn)
    seq_row_again = conn.execute(
        "SELECT input_hash FROM structure_sequences ORDER BY structure_id LIMIT 1",
    ).fetchone()
    conn.close()

    assert seq_row["input_hash"] == seq_row_again["input_hash"]


def test_similarity_outputs(tmp_path, monkeypatch):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=6)

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="baseline", db_path=None):  # noqa: ARG001
        sid = structure_id or "unknown"
        return {"engine": engine, "version": "v1", "text": f"text-{sid}", "input_hash": f"h-{sid}"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)

    embed_texts(db_path=str(db_path), engine="baseline")
    encode_sequences(db_path=str(db_path), format="cif_canon")
    embed_sequences(db_path=str(db_path), format="cif_canon")

    text_result = similar_text(structure_id="crystal-0001", db_path=str(db_path), k=3)
    seq_result = similar_seq(structure_id="crystal-0001", db_path=str(db_path), k=3)
    hybrid_result = similar_hybrid(structure_id="crystal-0001", db_path=str(db_path), k=3, sources=["text", "seq"]) 

    assert "neighbors" in text_result
    assert "neighbors" in seq_result
    assert "neighbors" in hybrid_result
    if hybrid_result["neighbors"]:
        assert "fused_score" in hybrid_result["neighbors"][0]
        assert "sources" in hybrid_result["neighbors"][0]


def test_policy_blocks_embeddings(tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=3)

    cif_dir = tmp_path / "restricted"
    cif_dir.mkdir()
    _make_cif(cif_dir / "restricted.cif", "Li2O", "restricted")

    ingest_folder(
        db_path=str(db_path),
        folder_path=str(cif_dir),
        source="restricted",
        policy_name="default",
        cache_dir=None,
    )

    embed_texts(db_path=str(db_path), engine="baseline")

    conn = connect(str(db_path))
    init_db(conn)
    row = conn.execute(
        "SELECT structure_id FROM provenance WHERE source = ? AND source_id = ?",
        ("restricted", "restricted.cif"),
    ).fetchone()
    restricted_id = row["structure_id"]

    count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM structure_embeddings WHERE structure_id = ? AND modality = 'text'",
        (restricted_id,),
    ).fetchone()["cnt"]
    conn.close()

    assert count == 0


def test_eval_phase6_runs(tmp_path):
    result = run_eval_phase6(tmp_path / "phase6_eval", fast=True)
    assert result.get("status") == "ok"
