import hashlib
import json
import urllib.error

from crystal_db.__main__ import main
from crystal_db.db import connect, init_db
from crystal_db.novelty_check import run_novelty_check
from crystal_db.reporting import report_run
from crystal_db.runlog import RunLogger


def _seed_phase2_db(db_path, *, with_text_embeddings=True, with_fingerprints=True):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    rows = [
        ("crystal-a", 1, [1.0, 0.0], [1.0, 0.0]),
        ("crystal-b", 1, [0.99, 0.01], [0.99, 0.01]),
        ("crystal-c", 1, [0.2, 0.8], [0.2, 0.8]),
    ]
    for sid, allow_export, text_vec, fp_vec in rows:
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
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, "test", f"{sid}.cif", ts, allow_export),
        )
        doc_id = conn.execute(
            "INSERT INTO text_docs "
            "(structure_id, engine, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "robocrys", "v1", f"text-{sid}", f"h-{sid}", "OK", None, None, ts, ts),
        ).lastrowid
        if with_text_embeddings:
            conn.execute(
                "INSERT INTO text_embeddings "
                "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc_id,
                    "lmstudio",
                    "text-embedding-bge-m3",
                    "lmstudio_v1",
                    2,
                    json.dumps(text_vec),
                    "OK",
                    None,
                    None,
                    ts,
                    ts,
                ),
            )
        if with_fingerprints:
            conn.execute(
                "INSERT INTO structure_fingerprints "
                "(structure_id, fingerprint_method, fingerprint_version, vector_json, feature_names_json, input_hash, generated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sid, "fp.simple.v1", "v1", json.dumps(fp_vec), json.dumps(["f1", "f2"]), f"fp-{sid}", ts),
            )
    conn.commit()
    conn.close()


def _mock_lmstudio(monkeypatch, vector):
    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        payload = json.loads(req.data.decode("utf-8"))
        items = payload.get("input", [])
        body = json.dumps({"data": [{"index": idx, "embedding": vector} for idx, _ in enumerate(items)]}).encode(
            "utf-8"
        )

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                return False

            def read(self):
                return body

        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def test_runlogger_hash_stability(tmp_path):
    db_path = tmp_path / "crystal.db"
    logger = RunLogger(str(db_path))
    run_id = logger.start_run("agent", {"query": "abc"})
    inp = {"a": 2, "b": 1}
    out = {"x": [1, 2, 3]}
    logger.log_step("tool", inp, out, "ok")
    logger.add_evidence("answer", {"ok": True})
    logger.add_explored("crystal-a", "retrieved_neighbor")
    logger.add_proposal(source="user", structure_id="crystal-a")
    logger.finalize_run(status="ok")

    conn = connect(str(db_path))
    init_db(conn)
    row = conn.execute(
        "SELECT input_hash, output_hash FROM run_steps WHERE run_id = ? ORDER BY step_id LIMIT 1",
        (run_id,),
    ).fetchone()
    conn.close()

    expected_in = hashlib.sha256(json.dumps(inp, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    expected_out = hashlib.sha256(json.dumps(out, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert row["input_hash"] == expected_in
    assert row["output_hash"] == expected_out


def test_agent_command_success_and_report(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "crystal.db"
    _seed_phase2_db(db_path, with_text_embeddings=True, with_fingerprints=True)
    _mock_lmstudio(monkeypatch, [1.0, 0.0])

    code = main(
        [
            "agent",
            "--db",
            str(db_path),
            "--query",
            "crystal like a",
            "--k",
            "3",
            "--engine",
            "lmstudio",
            "--model",
            "text-embedding-bge-m3",
            "--model-version",
            "lmstudio_v1",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert code == 0
    assert payload["run_id"]
    assert payload["cited_structure_ids"]

    report = report_run(run_id=payload["run_id"], db_path=str(db_path))
    assert report["run"]["command"] == "agent"
    kinds = [item["kind"] for item in report["evidence_bundles"]]
    assert "retrieval" in kinds
    assert "answer" in kinds


def test_agent_command_empty_candidates_errors(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "crystal.db"
    _seed_phase2_db(db_path, with_text_embeddings=False, with_fingerprints=True)
    _mock_lmstudio(monkeypatch, [1.0, 0.0])

    code = main(
        [
            "agent",
            "--db",
            str(db_path),
            "--query",
            "crystal like a",
            "--engine",
            "lmstudio",
            "--model",
            "text-embedding-bge-m3",
            "--model-version",
            "lmstudio_v1",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip())
    assert code == 1
    assert payload["errors"]["code"] == "missing_embedding_space"


def test_novelty_check_id_uses_existing_and_threshold_flips(tmp_path, monkeypatch):
    db_path = tmp_path / "crystal.db"
    _seed_phase2_db(db_path, with_text_embeddings=True, with_fingerprints=True)

    def should_not_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("unexpected recompute")

    monkeypatch.setattr("crystal_db.novelty_check.generate_text", should_not_run)
    monkeypatch.setattr("crystal_db.novelty_check.fingerprint_structure", should_not_run)

    loose = run_novelty_check(
        db_path=str(db_path),
        structure_id="crystal-a",
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        text_sim_threshold=0.99999,
        fp_sim_threshold=0.99999,
    )
    strict = run_novelty_check(
        db_path=str(db_path),
        structure_id="crystal-a",
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
        text_sim_threshold=0.9,
        fp_sim_threshold=0.9,
    )
    assert loose["errors"] is None
    assert strict["errors"] is None
    assert loose["novelty"]["is_novel"] is True
    assert strict["novelty"]["is_novel"] is False


def test_novelty_check_cif_generates_text_and_embed(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "crystal.db"
    _seed_phase2_db(db_path, with_text_embeddings=True, with_fingerprints=True)
    cif_path = tmp_path / "candidate.cif"
    cif_path.write_text("data_candidate\n_cell_length_a 1\n", encoding="utf-8")

    def fake_generate_text(*, structure_id=None, cif_text=None, engine="baseline", db_path=None):  # noqa: ARG001
        return {"engine": engine, "version": "v1", "text": "candidate text", "input_hash": "h"}

    monkeypatch.setattr("crystal_db.novelty_check.generate_text", fake_generate_text)
    _mock_lmstudio(monkeypatch, [1.0, 0.0])

    code = main(
        [
            "novelty-check",
            "--db",
            str(db_path),
            "--cif",
            str(cif_path),
            "--engine",
            "lmstudio",
            "--model",
            "text-embedding-bge-m3",
            "--model-version",
            "lmstudio_v1",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert code == 0
    assert payload["run_id"]
    assert payload["novelty"]["thresholds"]["text_sim_threshold"] == 0.8


def test_phase2_commands_do_not_bypass_export_policy(tmp_path, monkeypatch):
    db_path = tmp_path / "crystal.db"
    _seed_phase2_db(db_path, with_text_embeddings=True, with_fingerprints=True)
    conn = connect(str(db_path))
    init_db(conn)
    conn.execute("UPDATE provenance SET allow_export = 0 WHERE structure_id = ?", ("crystal-b",))
    conn.commit()
    conn.close()
    _mock_lmstudio(monkeypatch, [1.0, 0.0])

    result = run_novelty_check(
        db_path=str(db_path),
        structure_id="crystal-a",
        k=3,
        embed_engine="lmstudio",
        model_name="text-embedding-bge-m3",
        model_version="lmstudio_v1",
    )
    assert result["errors"] is None
    assert result["comparators"]
