import json

from crystal_db.__main__ import main
from crystal_db.db import connect, init_db


def _seed_bench_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    rows = [
        ("cfg-a", "layered perovskite corner-sharing octahedra", [1.0, 0.0], [1.0, 0.0]),
        ("cfg-b", "spinel oxide edge-sharing octahedra", [0.8, 0.2], [0.8, 0.2]),
        ("cfg-c", "laves boride framework", [0.2, 0.8], [0.2, 0.8]),
    ]
    for sid, text, vec, fp in rows:
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
            (sid, "caption", "caption", "v1", text, f"h-{sid}", "OK", None, None, ts, ts),
        ).lastrowid
        conn.execute(
            "INSERT INTO text_embeddings "
            "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, "hash", "hash-embed", "v1", 2, json.dumps(vec), "OK", None, None, ts, ts),
        )
        conn.execute(
            "INSERT INTO structure_fingerprints "
            "(structure_id, fingerprint_method, fingerprint_version, vector_json, feature_names_json, input_hash, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, "fp.simple.v1", "v1", json.dumps(fp), json.dumps(["f1", "f2"]), f"fp-{sid}", ts),
        )
    conn.commit()
    conn.close()


def _write_cases(path):
    case = {
        "case_id": "cfg_case",
        "query": "layered material",
        "expected": {"must_contain_any": ["layered"]},
    }
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(case) + "\n")


def test_bench_config_defaults_and_cli_override(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "cfg.db"
    cases_path = tmp_path / "cases.jsonl"
    cfg_path = tmp_path / "retrieval_defaults.json"
    _seed_bench_db(db_path)
    _write_cases(cases_path)
    cfg_payload = {
        "k": 2,
        "engine": "hash",
        "model": "hash-embed",
        "model_version": "v1",
        "text_engine": "caption",
        "text_view": "caption",
        "hybrid": False,
        "w_text": 1.0,
        "w_fp": 0.0,
        "redacted": True,
    }
    with open(cfg_path, "w", encoding="utf-8") as handle:
        json.dump(cfg_payload, handle, indent=2)

    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])
    code = main(
        [
            "bench-retrieval",
            "--db",
            str(db_path),
            "--cases",
            str(cases_path),
            "--config",
            str(cfg_path),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert payload["config"]["k"] == 2
    assert payload["config"]["engine"] == "hash"

    code_override = main(
        [
            "bench-retrieval",
            "--db",
            str(db_path),
            "--cases",
            str(cases_path),
            "--config",
            str(cfg_path),
            "--k",
            "3",
        ]
    )
    captured_override = capsys.readouterr()
    payload_override = json.loads(captured_override.out)
    assert code_override == 0
    assert payload_override["config"]["k"] == 3


def test_csp_pack_config_defaults(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "cfg_pack.db"
    cfg_path = tmp_path / "retrieval_defaults.json"
    _seed_bench_db(db_path)
    cfg_payload = {
        "k": 2,
        "engine": "hash",
        "model": "hash-embed",
        "model_version": "v1",
        "text_engine": "caption",
        "text_view": "caption",
        "hybrid": True,
        "w_text": 0.6,
        "w_fp": 0.4,
        "redacted": True,
    }
    with open(cfg_path, "w", encoding="utf-8") as handle:
        json.dump(cfg_payload, handle, indent=2)

    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])
    code_pack = main(
        [
            "csp-pack",
            "--db",
            str(db_path),
            "--query",
            "layered material",
            "--config",
            str(cfg_path),
        ]
    )
    payload_pack = json.loads(capsys.readouterr().out)
    assert code_pack == 0
    assert payload_pack["query"]["k"] == 2
    assert payload_pack["query"]["w_text"] == 0.6
