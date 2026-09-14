import json

from crystal_db.__main__ import main
from crystal_db.calibrate import run_retrieval_calibration
from crystal_db.db import connect, init_db


def _seed_retrieval_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    rows = [
        ("cal-a", "layered perovskite corner-sharing octahedra", [1.0, 0.0, 0.0]),
        ("cal-b", "spinel oxide edge-sharing octahedra", [0.8, 0.2, 0.0]),
        ("cal-c", "laves boride framework", [0.2, 0.8, 0.0]),
    ]
    for sid, text, vector in rows:
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
            (doc_id, "lmstudio", "text-embedding-bge-m3", "lmstudio_v1", 3, json.dumps(vector), "OK", None, None, ts, ts),
        )
        conn.execute(
            "INSERT INTO text_embeddings "
            "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, "hash", "hash-embed", "v1", 3, json.dumps(vector), "OK", None, None, ts, ts),
        )
    conn.commit()
    conn.close()


def _write_cases(path):
    cases = [
        {"case_id": "c1", "query": "layered oxide", "expected": {"must_contain_any": ["layered"]}},
        {"case_id": "c2", "query": "layered oxide", "expected": {"must_contain_any": ["layered"]}},
        {"case_id": "c3", "query": "spinel framework", "expected": {"must_contain_any": ["spinel"]}},
        {"case_id": "c4", "query": "spinel framework", "expected": {"must_contain_any": ["spinel"]}},
        {"case_id": "c5", "query": "laves phase", "expected": {"must_contain_any": ["laves"]}},
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case) + "\n")


def _write_labeled_cases(path):
    cases = [
        {"case_id": "c1", "query": "layered perovskite corner-sharing octahedra", "expected_structure_ids": ["cal-a"]},
        {"case_id": "c2", "query": "spinel oxide edge-sharing octahedra", "expected_structure_ids": ["cal-b"]},
        {"case_id": "c3", "query": "laves boride framework", "expected_structure_ids": ["cal-c"]},
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case) + "\n")


def _mock_lmstudio_embed_calls(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        calls["count"] += 1
        payload = json.loads(req.data.decode("utf-8"))
        inputs = payload.get("input", [])
        if isinstance(inputs, str):
            inputs = [inputs]
        data = [{"index": idx, "embedding": [1.0, 0.0, 0.0]} for idx, _ in enumerate(inputs)]
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
    return calls


def test_calibrate_preembed_query_cache_hits_once_per_unique_query(tmp_path, monkeypatch):
    db_path = tmp_path / "cal_cache.db"
    cases_path = tmp_path / "cases.jsonl"
    out_dir = tmp_path / "out"
    _seed_retrieval_db(db_path)
    _write_cases(cases_path)
    calls = _mock_lmstudio_embed_calls(monkeypatch)

    result = run_retrieval_calibration(
        db_path=str(db_path),
        cases_path=str(cases_path),
        out_dir=str(out_dir),
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        redacted=True,
        text_sim_min=0.80,
        text_sim_max=0.80,
        text_sim_step=0.05,
        fp_sim_min=0.90,
        fp_sim_max=0.90,
        fp_sim_step=0.02,
        w_text_values=[0.5, 0.6, 0.7],
        preembed_queries=True,
    )
    assert result["errors"] is None
    assert calls["count"] == 3


def test_calibrate_query_cache_persists_to_sqlite_between_runs(tmp_path, monkeypatch):
    db_path = tmp_path / "cal_cache.db"
    cases_path = tmp_path / "cases.jsonl"
    out_dir1 = tmp_path / "out1"
    out_dir2 = tmp_path / "out2"
    _seed_retrieval_db(db_path)
    _write_cases(cases_path)

    first_calls = _mock_lmstudio_embed_calls(monkeypatch)
    first = run_retrieval_calibration(
        db_path=str(db_path),
        cases_path=str(cases_path),
        out_dir=str(out_dir1),
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        redacted=True,
        text_sim_min=0.80,
        text_sim_max=0.80,
        text_sim_step=0.05,
        fp_sim_min=0.90,
        fp_sim_max=0.90,
        fp_sim_step=0.02,
        w_text_values=[0.5, 0.6, 0.7],
        preembed_queries=True,
    )
    assert first["errors"] is None
    assert first_calls["count"] == 3

    conn = connect(str(db_path))
    init_db(conn)
    row = conn.execute("SELECT COUNT(*) AS cnt FROM query_embeddings WHERE status = 'OK'").fetchone()
    conn.close()
    assert int(row["cnt"]) == 3

    second_calls = _mock_lmstudio_embed_calls(monkeypatch)
    second = run_retrieval_calibration(
        db_path=str(db_path),
        cases_path=str(cases_path),
        out_dir=str(out_dir2),
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        redacted=True,
        text_sim_min=0.80,
        text_sim_max=0.80,
        text_sim_step=0.05,
        fp_sim_min=0.90,
        fp_sim_max=0.90,
        fp_sim_step=0.02,
        w_text_values=[0.5, 0.6, 0.7],
        preembed_queries=True,
    )
    assert second["errors"] is None
    assert second_calls["count"] == 0


def test_calibrate_candidate_set_empty_fails_fast_without_query_embedding_calls(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "empty.db"
    cases_path = tmp_path / "cases.jsonl"
    out_dir = tmp_path / "out"
    conn = connect(str(db_path))
    init_db(conn)
    conn.close()
    _write_cases(cases_path)
    calls = _mock_lmstudio_embed_calls(monkeypatch)

    code = main(
        [
            "calibrate-retrieval",
            "--db",
            str(db_path),
            "--cases",
            str(cases_path),
            "--out",
            str(out_dir),
            "--engine",
            "lmstudio",
            "--model",
            "text-embedding-bge-m3",
            "--model-version",
            "lmstudio_v1",
            "--w-text-values",
            "0.5,0.6,0.7",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip())

    assert code == 1
    assert payload["errors"]["code"] == "candidate_set_empty"
    assert calls["count"] == 0


def test_calibrate_stage_a_calls_retrieval_once_per_case(monkeypatch, tmp_path):
    db_path = tmp_path / "stage_a_once.db"
    cases_path = tmp_path / "cases.jsonl"
    out_dir = tmp_path / "out"
    _seed_retrieval_db(db_path)
    _write_cases(cases_path)

    calls = {"count": 0}

    def fake_text_search(**kwargs):  # noqa: ARG001
        calls["count"] += 1
        return {
            "query": {},
            "neighbors": [{"structure_id": "cal-a", "score": 1.0, "text_score": 1.0, "fp_score": 1.0}],
            "errors": None,
        }

    monkeypatch.setattr("crystal_db.calibrate.text_search", fake_text_search)

    result = run_retrieval_calibration(
        db_path=str(db_path),
        cases_path=str(cases_path),
        out_dir=str(out_dir),
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        redacted=True,
        text_sim_min=0.8,
        text_sim_max=0.8,
        text_sim_step=0.05,
        fp_sim_min=0.9,
        fp_sim_max=0.9,
        fp_sim_step=0.02,
        w_text_values=[0.5, 0.6, 0.7],
        preembed_queries=False,
        cache_candidates=True,
        reuse_candidates_cache=False,
    )
    assert result["errors"] is None
    assert calls["count"] == 5


def test_calibrate_reuse_candidate_cache_keeps_results_identical(monkeypatch, tmp_path):
    db_path = tmp_path / "reuse_cache.db"
    cases_path = tmp_path / "cases_labeled.jsonl"
    out_dir1 = tmp_path / "out1"
    out_dir2 = tmp_path / "out2"
    cache_path = tmp_path / "cached_candidates.jsonl"
    _seed_retrieval_db(db_path)
    _write_labeled_cases(cases_path)

    first = run_retrieval_calibration(
        db_path=str(db_path),
        cases_path=str(cases_path),
        out_dir=str(out_dir1),
        k=3,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        redacted=True,
        text_sim_min=0.8,
        text_sim_max=0.8,
        text_sim_step=0.05,
        fp_sim_min=0.9,
        fp_sim_max=0.9,
        fp_sim_step=0.02,
        w_text_values=[0.5, 0.6, 0.7],
        cache_candidates=True,
        reuse_candidates_cache=False,
        candidate_cache_path=str(cache_path),
    )
    assert first["errors"] is None
    assert cache_path.exists()

    def fail_text_search(**kwargs):  # noqa: ARG001
        raise AssertionError("text_search should not be called when candidate cache is reused")

    monkeypatch.setattr("crystal_db.calibrate.text_search", fail_text_search)
    second = run_retrieval_calibration(
        db_path=str(db_path),
        cases_path=str(cases_path),
        out_dir=str(out_dir2),
        k=3,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        redacted=True,
        text_sim_min=0.8,
        text_sim_max=0.8,
        text_sim_step=0.05,
        fp_sim_min=0.9,
        fp_sim_max=0.9,
        fp_sim_step=0.02,
        w_text_values=[0.5, 0.6, 0.7],
        cache_candidates=True,
        reuse_candidates_cache=True,
        candidate_cache_path=str(cache_path),
    )
    assert second["errors"] is None
    assert first["best"] == second["best"]
    assert first["results"] == second["results"]


def test_calibrate_best_deterministic_for_same_inputs(tmp_path):
    db_path = tmp_path / "deterministic.db"
    cases_path = tmp_path / "cases_labeled.jsonl"
    out_dir1 = tmp_path / "det_out1"
    out_dir2 = tmp_path / "det_out2"
    _seed_retrieval_db(db_path)
    _write_labeled_cases(cases_path)

    first = run_retrieval_calibration(
        db_path=str(db_path),
        cases_path=str(cases_path),
        out_dir=str(out_dir1),
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        redacted=True,
        text_sim_min=0.8,
        text_sim_max=0.8,
        text_sim_step=0.05,
        fp_sim_min=0.9,
        fp_sim_max=0.9,
        fp_sim_step=0.02,
        w_text_values=[0.5, 0.6, 0.7],
        cache_candidates=False,
    )
    second = run_retrieval_calibration(
        db_path=str(db_path),
        cases_path=str(cases_path),
        out_dir=str(out_dir2),
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        redacted=True,
        text_sim_min=0.8,
        text_sim_max=0.8,
        text_sim_step=0.05,
        fp_sim_min=0.9,
        fp_sim_max=0.9,
        fp_sim_step=0.02,
        w_text_values=[0.5, 0.6, 0.7],
        cache_candidates=False,
    )
    assert first["errors"] is None
    assert second["errors"] is None
    assert first["best"] == second["best"]
    best1 = json.loads((out_dir1 / "calibration_best.json").read_text(encoding="utf-8"))
    best2 = json.loads((out_dir2 / "calibration_best.json").read_text(encoding="utf-8"))
    assert best1 == best2
