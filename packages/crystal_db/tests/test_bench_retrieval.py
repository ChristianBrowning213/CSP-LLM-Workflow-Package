import json
from pathlib import Path

from crystal_db.__main__ import main
from crystal_db.bench_retrieval import run_bench_retrieval
from crystal_db.db import connect, init_db
from crystal_db.reporting import report_run


def _seed_bench_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    rows = [
        ("s-redacted-1", 0, "Li2O", "Pm-3m", "SECRETMARKER perovskite corner-sharing octahedra", [1.0, 0.0]),
        ("s-perov-1", 1, "MgO", "P4/mmm", "layered perovskite corner-sharing octahedra", [0.95, 0.05]),
        ("s-boride-1", 1, "FeB", "Fd-3m", "laves boride tetrahedra network", [0.70, 0.30]),
        ("s-rock-1", 1, "NaCl", "Fm-3m", "rocksalt cubic framework", [0.60, 0.40]),
        ("s-net-1", 1, "SiO2", "P1", "tetrahedra network", [0.20, 0.80]),
    ]
    for sid, allow_export, formula, spg, text, vector in rows:
        conn.execute(
            "INSERT INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, f"data_{sid}\n_cell_length_a 1\n", formula, 1, 1.0, 0),
        )
        conn.execute(
            "INSERT INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, formula, f",{','.join([token for token in ['Li','Mg','Fe','Na','Si','O','Cl','B'] if token in formula])},", spg, 0.1),
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
            (text_doc_id, "hash", "hash-embed", "v1", 2, json.dumps(vector), "OK", None, None, ts, ts),
        )
    conn.commit()
    conn.close()


def _write_cases(path: Path):
    cases = [
        {
            "case_id": "c1_perov",
            "query": "perovskite oxide with corner-sharing octahedra",
            "expected": {"must_contain_any": ["perovskite", "corner-sharing", "octahedra"], "family": "perovskite"},
        },
        {
            "case_id": "c2_laves",
            "query": "laves boride intermetallic",
            "expected": {"family": "laves"},
        },
        {
            "case_id": "c3_structure_id",
            "query": "boride tetrahedra",
            "expected": {"structure_ids_any": ["s-boride-1"]},
        },
        {
            "case_id": "c4_redacted_fallback",
            "query": "secret marker candidate",
            "expected": {"elements_any": ["Li"]},
        },
        {
            "case_id": "c5_no_match",
            "query": "nonexistent motif",
            "expected": {"must_contain_any": ["unobtanium-pattern"]},
        },
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case) + "\n")


def test_bench_retrieval_deterministic_summary(tmp_path, monkeypatch):
    db_path = tmp_path / "bench.db"
    cases_path = tmp_path / "cases.jsonl"
    _seed_bench_db(db_path)
    _write_cases(cases_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    first = run_bench_retrieval(
        db_path=str(db_path),
        cases_path=str(cases_path),
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        w_text=0.7,
        w_fp=0.3,
        redacted=True,
        out_dir=str(tmp_path / "out1"),
    )
    second = run_bench_retrieval(
        db_path=str(db_path),
        cases_path=str(cases_path),
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        w_text=0.7,
        w_fp=0.3,
        redacted=True,
        out_dir=str(tmp_path / "out2"),
    )
    assert first["errors"] is None
    assert second["errors"] is None
    assert first["summary"] == second["summary"]
    metrics1 = {item["case_id"]: item["metrics"] for item in first["per_case"]}
    metrics2 = {item["case_id"]: item["metrics"] for item in second["per_case"]}
    assert metrics1 == metrics2


def test_bench_retrieval_redacted_case_uses_hint_fallback(tmp_path, monkeypatch):
    db_path = tmp_path / "bench.db"
    cases_path = tmp_path / "cases.jsonl"
    _seed_bench_db(db_path)
    _write_cases(cases_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    result = run_bench_retrieval(
        db_path=str(db_path),
        cases_path=str(cases_path),
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=False,
        w_text=1.0,
        w_fp=0.0,
        redacted=True,
        out_dir=None,
    )
    assert result["errors"] is None
    redacted_case = [item for item in result["per_case"] if item["case_id"] == "c4_redacted_fallback"][0]
    assert redacted_case["status"] == "ok"
    assert redacted_case["metrics"]["hint_fallback_used"] is True


def test_bench_retrieval_logging_and_exports(tmp_path, monkeypatch):
    db_path = tmp_path / "bench.db"
    cases_path = tmp_path / "cases.jsonl"
    out_dir = tmp_path / "out"
    _seed_bench_db(db_path)
    _write_cases(cases_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    result = run_bench_retrieval(
        db_path=str(db_path),
        cases_path=str(cases_path),
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        w_text=0.7,
        w_fp=0.3,
        redacted=True,
        out_dir=str(out_dir),
    )
    assert result["errors"] is None
    assert (out_dir / "summary.json").exists()
    assert (out_dir / "cases_scored.jsonl").exists()
    assert (out_dir / "summary.csv").exists()

    report = report_run(run_id=result["run_id"], db_path=str(db_path))
    assert report["run"]["command"] == "bench-retrieval"
    tools = [step["tool_name"] for step in report["run_steps"]]
    assert "load_cases" in tools
    assert "scoring" in tools
    assert "export" in tools
    assert tools.count("retrieval_case") == 5
    kinds = [item["kind"] for item in report["evidence_bundles"]]
    assert "cases_loaded" in kinds
    assert "retrieval_results" in kinds
    assert "scoring_table" in kinds
    assert "summary" in kinds


def test_bench_retrieval_cli_success(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "bench.db"
    cases_path = tmp_path / "cases.jsonl"
    _seed_bench_db(db_path)
    _write_cases(cases_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    code = main(
        [
            "bench-retrieval",
            "--db",
            str(db_path),
            "--cases",
            str(cases_path),
            "--k",
            "5",
            "--engine",
            "hash",
            "--model",
            "hash-embed",
            "--model-version",
            "v1",
            "--text-engine",
            "caption",
            "--text-view",
            "caption",
            "--hybrid",
            "true",
            "--w-text",
            "0.7",
            "--w-fp",
            "0.3",
            "--redacted",
            "true",
            "--out",
            str(tmp_path / "cli_out"),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert code == 0
    assert payload["errors"] is None
    assert payload["summary"]["total_cases"] == 5


def test_bench_retrieval_expected_structure_ids_scores_nonzero(tmp_path, monkeypatch):
    db_path = tmp_path / "bench_labeled.db"
    cases_path = tmp_path / "cases_labeled.jsonl"
    _seed_bench_db(db_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    labeled_case = {
        "case_id": "labeled_self_1",
        "query": "perovskite corner-sharing octahedra",
        "expected_structure_ids": ["s-redacted-1"],
    }
    with open(cases_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(labeled_case) + "\n")

    result = run_bench_retrieval(
        db_path=str(db_path),
        cases_path=str(cases_path),
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=False,
        w_text=1.0,
        w_fp=0.0,
        redacted=True,
        out_dir=None,
    )
    assert result["errors"] is None
    assert result["summary"]["hit_at_k"] > 0.0
    assert result["summary"]["mrr"] > 0.0
    assert result["summary"]["ndcg_at_k"] > 0.0


def test_bench_retrieval_cli_max_cases_limits_evaluated_cases(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "bench_max_cases.db"
    cases_path = tmp_path / "cases.jsonl"
    _seed_bench_db(db_path)
    _write_cases(cases_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    code = main(
        [
            "bench-retrieval",
            "--db",
            str(db_path),
            "--cases",
            str(cases_path),
            "--k",
            "5",
            "--engine",
            "hash",
            "--model",
            "hash-embed",
            "--model-version",
            "v1",
            "--text-engine",
            "caption",
            "--text-view",
            "caption",
            "--hybrid",
            "true",
            "--w-text",
            "0.7",
            "--w-fp",
            "0.3",
            "--redacted",
            "true",
            "--max-cases",
            "3",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert code == 0
    assert payload["errors"] is None
    assert payload["summary"]["total_cases"] == 3
