import json
from pathlib import Path

from crystal_db.api import agent as run_agent_api
from crystal_db.api import bench_retrieval, make_csp_pack, novelty_check, retrieve_text
from crystal_db.db import connect, init_db
from crystal_db.schema_validate import validate


def _seed_api_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    rows = [
        ("s-a", 1, "Li2O", "P4/mmm", "layered perovskite corner-sharing octahedra", [1.0, 0.0], [1.0, 0.0]),
        ("s-b", 1, "NaCl", "Fm-3m", "laves boride tetrahedra", [0.8, 0.2], [0.8, 0.2]),
        ("s-c", 0, "SiO2", "P1", "redacted layered text", [0.6, 0.4], [0.6, 0.4]),
    ]
    for sid, allow_export, formula, spg, text, text_vec, fp_vec in rows:
        conn.execute(
            "INSERT INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, f"data_{sid}\n_cell_length_a 1\n", formula, 1, 1.0, 0),
        )
        elements_csv = "," + ",".join([token for token in ["Li", "Na", "Si", "O", "Cl"] if token in formula]) + ","
        conn.execute(
            "INSERT INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, formula, elements_csv, spg, 0.1),
        )
        conn.execute(
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export, allow_derivatives) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "test", f"{sid}.cif", ts, allow_export, 1),
        )
        text_doc_id = conn.execute(
            "INSERT INTO text_docs "
            "(structure_id, engine, text_view, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "caption", "caption", "v1", text, f"h-{sid}", "OK", None, None, ts, ts),
        ).lastrowid
        conn.execute(
            "INSERT INTO text_embeddings "
            "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (text_doc_id, "hash", "hash-embed", "v1", 2, json.dumps(text_vec), "OK", None, None, ts, ts),
        )
        conn.execute(
            "INSERT INTO structure_fingerprints "
            "(structure_id, fingerprint_method, fingerprint_version, vector_json, feature_names_json, input_hash, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, "fp.simple.v1", "v1", json.dumps(fp_vec), json.dumps(["f1", "f2"]), f"fp-{sid}", ts),
        )
    conn.commit()
    conn.close()


def _write_cases(path: Path):
    cases = [
        {
            "case_id": "c1",
            "query": "perovskite corner-sharing octahedra",
            "expected": {"must_contain_any": ["perovskite"], "family": "perovskite"},
        },
        {
            "case_id": "c2",
            "query": "laves boride",
            "expected": {"family": "laves"},
        },
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for item in cases:
            handle.write(json.dumps(item) + "\n")


def test_api_retrieve_text_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    _seed_api_db(db_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    payload = retrieve_text(
        str(db_path),
        "layered material",
        k=3,
        embed_engine="hash",
        model="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=False,
        w_text=1.0,
        w_fp=0.0,
        redacted=True,
        show_text_top=1,
        demo_export=False,
    )
    assert payload["schema_version"] == "text_search.v1"
    validate(payload, "text_search.v1")


def test_api_csp_pack_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    out_dir = tmp_path / "pack_out"
    _seed_api_db(db_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    payload = make_csp_pack(
        str(db_path),
        query="layered material",
        out_dir=str(out_dir),
        export_top=2,
        redacted=True,
        demo_export=False,
        k=3,
        embed_engine="hash",
        model="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        w_text=0.7,
        w_fp=0.3,
    )
    assert payload["schema_version"] == "csp_pack.v1"
    validate(payload, "csp_pack.v1")


def test_api_novelty_check_contract(tmp_path):
    db_path = tmp_path / "api.db"
    _seed_api_db(db_path)
    payload = novelty_check(
        str(db_path),
        structure_id="s-a",
        k=3,
        embed_engine="hash",
        model="hash-embed",
        model_version="v1",
        text_sim_threshold=0.8,
        fp_sim_threshold=0.95,
        force=False,
    )
    assert payload["schema_version"] == "novelty_check.v1"
    validate(payload, "novelty_check.v1")


def test_api_bench_retrieval_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    cases_path = tmp_path / "cases.jsonl"
    _seed_api_db(db_path)
    _write_cases(cases_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    payload = bench_retrieval(
        str(db_path),
        str(cases_path),
        k=3,
        embed_engine="hash",
        model="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        w_text=0.7,
        w_fp=0.3,
        redacted=True,
        out_dir=str(tmp_path / "bench_out"),
    )
    assert payload["schema_version"] == "bench_retrieval.v1"
    validate(payload, "bench_retrieval.v1")


def test_api_agent_contract(tmp_path):
    db_path = tmp_path / "api.db"
    _seed_api_db(db_path)

    payload = run_agent_api(
        str(db_path),
        question="show structure s-a",
        llm="off",
    )
    assert payload["schema_version"] == "agent.v1"
    validate(payload, "agent.v1")


def test_cli_sample_still_validates_against_text_search_schema():
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "text_search_cli_sample.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    validate(payload, "text_search.v1")
