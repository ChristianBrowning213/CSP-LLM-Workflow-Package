import json
import sqlite3
import sys

import pytest

from crystal_db.db import connect, init_db
from crystal_db.ingest import ingest_sample
from crystal_db.phase2 import run_phase2_agent
from crystal_db.reporting import report_run
from crystal_db.retrieval import text_search
from crystal_db.text_index import embed_text_docs, generate_text_docs
from crystal_db.textgen import _build_caption_from_text, generate_text


def _seed_text_fixture(db_path, *, text_engine: str, text_view: str) -> None:
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    rows = [
        ("mat-layered-1", "layered van der Waals sheet material", [0.99, 0.01], [1.0, 0.0]),
        ("mat-layered-2", "2D layered corner-sharing octahedra", [0.96, 0.04], [0.95, 0.05]),
        ("mat-laves-1", "Laves-phase boride intermetallic", [0.90, 0.10], [0.0, 1.0]),
        ("mat-boride-1", "dense boride framework", [0.80, 0.20], [0.2, 0.8]),
        ("mat-random-1", "random compact 3D network", [0.70, 0.30], [0.1, 0.9]),
    ]
    for sid, text, text_vec, fp_vec in rows:
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
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export, allow_derivatives) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "test", f"{sid}.cif", ts, 1, 1),
        )
        doc_id = conn.execute(
            "INSERT INTO text_docs "
            "(structure_id, engine, text_view, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, text_engine, text_view, "v1", text, f"h-{sid}", "OK", None, None, ts, ts),
        ).lastrowid
        conn.execute(
            "INSERT INTO text_embeddings "
            "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, "hash", "hash-embed", "v1", 2, json.dumps(text_vec), "OK", None, None, ts, ts),
        )
        conn.execute(
            "INSERT INTO structure_fingerprints "
            "(structure_id, fingerprint_method, fingerprint_version, vector_json, feature_names_json, input_hash, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, "fp.simple.v1", "v1", json.dumps(fp_vec), json.dumps(["f1", "f2"]), f"fp-{sid}", ts),
        )
    conn.commit()
    conn.close()


def test_schema_migration_adds_text_view_and_unique_index(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE structures (structure_id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE text_docs ("
        "id INTEGER PRIMARY KEY, structure_id TEXT NOT NULL, engine TEXT NOT NULL, engine_version TEXT NOT NULL, "
        "text TEXT, text_sha256 TEXT, status TEXT NOT NULL, error_type TEXT, error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO structures (structure_id) VALUES (?)", ("s-1",))
    conn.execute(
        "INSERT INTO text_docs (structure_id, engine, engine_version, text, text_sha256, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("s-1", "robocrys", "v1", "old", "h1", "OK", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO text_docs (structure_id, engine, engine_version, text, text_sha256, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("s-1", "robocrys", "v2", "new", "h2", "OK", "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    conn = connect(str(db_path))
    init_db(conn)
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(text_docs)").fetchall()]
    index_rows = conn.execute("PRAGMA index_list(text_docs)").fetchall()
    unique_index = [row for row in index_rows if row["name"] == "idx_text_docs_view_unique"]
    count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM text_docs WHERE structure_id = ? AND engine = ? AND text_view = ?",
        ("s-1", "robocrys", "robocrys"),
    ).fetchone()["cnt"]
    conn.close()

    assert "text_view" in columns
    assert unique_index
    assert int(unique_index[0]["unique"]) == 1
    assert count == 1


def test_caption_generation_fallback_is_deterministic(monkeypatch, tmp_path):
    db_path = tmp_path / "caption.db"
    ingest_sample(db_path=str(db_path), count=1)

    def fake_build_crystalcard(*, structure_id=None, cif_text=None, db_path=None, engine="baseline", store=False):  # noqa: ARG001
        return {
            "text_summary": "Li2O layered van der Waals framework with corner-sharing octahedra",
            "motifs": [],
        }

    monkeypatch.setattr("crystal_db.textgen.build_crystalcard", fake_build_crystalcard)
    result = generate_text(structure_id="crystal-0001", engine="caption", db_path=str(db_path))
    assert result["engine"] == "caption"
    assert "Key descriptors:" in result["text"]
    assert "layered" in result["text"].lower()
    assert "Chemistry hint: Li2O." in result["text"]


@pytest.mark.parametrize("optional_backend", ["present", "absent"])
def test_caption_fallback_does_not_probe_optional_backend(monkeypatch, tmp_path, optional_backend):
    db_path = tmp_path / f"caption-{optional_backend}.db"
    ingest_sample(db_path=str(db_path), count=1)

    def fake_build_crystalcard(*, structure_id=None, cif_text=None, db_path=None, engine="baseline", store=False):  # noqa: ARG001
        return {
            "text_summary": "Li2O layered van der Waals framework with corner-sharing octahedra",
            "motifs": [],
        }

    monkeypatch.setattr("crystal_db.textgen.build_crystalcard", fake_build_crystalcard)
    if optional_backend == "present":
        from pymatgen.core import Structure

        def unexpected_optional_backend(*args, **kwargs):  # noqa: ARG001
            raise AssertionError("caption fallback probed the optional Robocrys path")

        monkeypatch.setattr(Structure, "from_str", unexpected_optional_backend)
    else:
        monkeypatch.setitem(sys.modules, "robocrys", None)

    first = generate_text(structure_id="crystal-0001", engine="caption", db_path=str(db_path))
    second = generate_text(structure_id="crystal-0001", engine="caption", db_path=str(db_path))
    assert first == second
    assert first["text"] == (
        "Li2O layered van der Waals framework with corner-sharing octahedra "
        "Key descriptors: layered, van der waals, octahedra, corner-sharing. Chemistry hint: Li2O."
    )


def test_caption_fallback_normalizes_windows_newlines():
    source = "Li2O layered van der Waals framework\nwith corner-sharing octahedra"
    assert _build_caption_from_text(source) == _build_caption_from_text(source.replace("\n", "\r\n"))


def test_embed_text_docs_caption_view_resume(monkeypatch, tmp_path):
    db_path = tmp_path / "caption_embed.db"
    ingest_sample(db_path=str(db_path), count=3)

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="caption", db_path=None):  # noqa: ARG001
        return {"engine": engine, "version": "v1", "text": f"caption-{structure_id}", "input_hash": f"h-{structure_id}"}

    monkeypatch.setattr("crystal_db.text_index.generate_text", fake_generate_text)
    gen = generate_text_docs(
        db_path=str(db_path),
        engine="caption",
        text_view="caption",
        batch=2,
        progress_every=1000,
    )
    assert gen["selected"] == 3
    assert gen["ok"] == 3
    assert gen["text_view"] == "caption"

    first = embed_text_docs(
        db_path=str(db_path),
        text_engine="caption",
        text_view="caption",
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        batch=2,
        progress_every=1000,
    )
    second = embed_text_docs(
        db_path=str(db_path),
        text_engine="caption",
        text_view="caption",
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        batch=2,
        progress_every=1000,
    )
    assert first["selected"] == 3
    assert first["ok"] == 3
    assert first["text_view"] == "caption"
    assert second["selected"] == 0

    conn = connect(str(db_path))
    init_db(conn)
    docs = conn.execute(
        "SELECT COUNT(*) AS cnt FROM text_docs WHERE engine = 'caption' AND text_view = 'caption' AND status = 'OK'",
    ).fetchone()["cnt"]
    embs = conn.execute(
        "SELECT COUNT(*) AS cnt FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        "WHERE td.engine = 'caption' AND td.text_view = 'caption' AND te.status = 'OK'",
    ).fetchone()["cnt"]
    conn.close()
    assert docs == 3
    assert embs == 3


def test_text_search_caption_view_returns_neighbors(monkeypatch, tmp_path):
    db_path = tmp_path / "caption_search.db"
    _seed_text_fixture(db_path, text_engine="caption", text_view="caption")

    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])
    result = text_search(
        query_text="layered van der Waals 2D material exfoliable",
        db_path=str(db_path),
        k=3,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        show_text_top=1,
    )
    assert result["errors"] is None
    top_ids = [item["structure_id"] for item in result["neighbors"][:2]]
    assert top_ids == ["mat-layered-1", "mat-layered-2"]


def test_text_search_hybrid_rerank_changes_order(monkeypatch, tmp_path):
    db_path = tmp_path / "hybrid.db"
    _seed_text_fixture(db_path, text_engine="robocrys", text_view="robocrys")

    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])
    pure = text_search(
        query_text="layered material",
        db_path=str(db_path),
        k=3,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="robocrys",
        text_view="robocrys",
        hybrid=False,
    )
    hybrid = text_search(
        query_text="layered material",
        db_path=str(db_path),
        k=3,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="robocrys",
        text_view="robocrys",
        hybrid=True,
        w_text=0.1,
        w_fp=0.9,
    )
    assert pure["errors"] is None
    assert hybrid["errors"] is None
    pure_ids = [item["structure_id"] for item in pure["neighbors"]]
    hybrid_ids = [item["structure_id"] for item in hybrid["neighbors"]]
    assert pure_ids[:3] == ["mat-layered-1", "mat-layered-2", "mat-laves-1"]
    assert "mat-laves-1" not in hybrid_ids[:3]
    assert "text_score" in hybrid["neighbors"][0]
    assert "fp_score" in hybrid["neighbors"][0]
    assert "final_score" in hybrid["neighbors"][0]


def test_agent_logs_text_view_and_hybrid_config(monkeypatch, tmp_path):
    db_path = tmp_path / "agent_phase3.db"
    _seed_text_fixture(db_path, text_engine="robocrys", text_view="robocrys")
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    result = run_phase2_agent(
        query="layered material",
        db_path=str(db_path),
        k=3,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="robocrys",
        text_view="robocrys",
        hybrid=True,
        w_text=0.2,
        w_fp=0.8,
    )
    assert result["errors"] is None
    report = report_run(run_id=result["run_id"], db_path=str(db_path))
    step = [item for item in report["run_steps"] if item["tool_name"] == "text_search"][0]
    assert step["input_json"]["text_view"] == "robocrys"
    assert step["input_json"]["hybrid"] is True
    assert step["input_json"]["w_text"] == 0.2
    assert step["input_json"]["w_fp"] == 0.8
