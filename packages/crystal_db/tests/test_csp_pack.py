import json
import os

from crystal_db.__main__ import main
from crystal_db.csp_pack import run_csp_pack
from crystal_db.db import connect, init_db
from crystal_db.reporting import report_run


def _seed_csp_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    rows = [
        (
            "s-layer-1",
            1,
            "Li2O layered van der Waals perovskite with corner-sharing octahedra, bond length 2.10 angstrom, tilt angle 12.0",
            [0.99, 0.01],
            [1.0, 0.0],
            "P4/mmm",
        ),
        (
            "s-layer-2",
            1,
            "NaCl layered 2D spinel with edge-sharing octahedra and bond length 1.95 angstrom",
            [0.96, 0.04],
            [0.95, 0.05],
            "R-3m",
        ),
        (
            "s-laves-1",
            1,
            "AB2 laves boride tetrahedra cubic phase",
            [0.55, 0.45],
            [0.2, 0.8],
            "Fd-3m",
        ),
        (
            "s-redacted-1",
            0,
            "SECRETMARKER perovskite corner-sharing octahedra",
            [0.94, 0.06],
            [0.9, 0.1],
            "Pm-3m",
        ),
        (
            "s-other-1",
            1,
            "disordered framework network",
            [0.40, 0.60],
            [0.1, 0.9],
            "P1",
        ),
    ]
    for sid, allow_export, text, emb, fp, spg in rows:
        conn.execute(
            "INSERT INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, f"data_{sid}\n_cell_length_a 1\n", "X", 1, 1.0, 0),
        )
        conn.execute(
            "INSERT INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, "Li2O", ",Li,O,", spg, 0.1),
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
            (text_doc_id, "hash", "hash-embed", "v1", 2, json.dumps(emb), "OK", None, None, ts, ts),
        )
        conn.execute(
            "INSERT INTO structure_fingerprints "
            "(structure_id, fingerprint_method, fingerprint_version, vector_json, feature_names_json, input_hash, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, "fp.simple.v1", "v1", json.dumps(fp), json.dumps(["f1", "f2"]), f"fp-{sid}", ts),
        )
    conn.commit()
    conn.close()


def test_csp_pack_success_writes_bundle(tmp_path, monkeypatch):
    db_path = tmp_path / "csp.db"
    out_dir = tmp_path / "out"
    _seed_csp_db(db_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    code = main(
        [
            "csp-pack",
            "--db",
            str(db_path),
            "--query",
            "layered van der Waals 2D material",
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
            "--out",
            str(out_dir),
            "--export-top",
            "4",
            "--redacted",
            "true",
            "--demo-export",
            "false",
        ]
    )
    assert code == 0
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "results.json").exists()
    assert (out_dir / "cifs").exists()
    payload = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert payload["errors"] is None
    assert payload["run_id"]
    assert len(payload["neighbors"]) >= 3


def test_csp_pack_hints_are_deterministic(tmp_path, monkeypatch):
    db_path = tmp_path / "csp.db"
    _seed_csp_db(db_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    first = run_csp_pack(
        db_path=str(db_path),
        query_text="layered material",
        structure_id=None,
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        out_dir=str(tmp_path / "first"),
        export_top=3,
        redacted=True,
        demo_export=False,
    )
    second = run_csp_pack(
        db_path=str(db_path),
        query_text="layered material",
        structure_id=None,
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        out_dir=str(tmp_path / "second"),
        export_top=3,
        redacted=True,
        demo_export=False,
    )
    assert first["errors"] is None
    assert second["errors"] is None
    assert first["hints"] == second["hints"]


def test_csp_pack_redaction_respected_in_hints(tmp_path, monkeypatch):
    db_path = tmp_path / "csp.db"
    _seed_csp_db(db_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])
    result = run_csp_pack(
        db_path=str(db_path),
        query_text="layered material",
        structure_id=None,
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        out_dir=str(tmp_path / "redacted"),
        export_top=5,
        redacted=True,
        demo_export=False,
    )
    assert result["errors"] is None
    serialized = json.dumps(result["hints"]).lower()
    assert "secretmarker" not in serialized


def test_csp_pack_export_gating(tmp_path, monkeypatch):
    db_path = tmp_path / "csp.db"
    _seed_csp_db(db_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    blocked = run_csp_pack(
        db_path=str(db_path),
        query_text="layered material",
        structure_id=None,
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        out_dir=str(tmp_path / "blocked"),
        export_top=5,
        redacted=True,
        demo_export=False,
    )
    allowed = run_csp_pack(
        db_path=str(db_path),
        query_text="layered material",
        structure_id=None,
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        out_dir=str(tmp_path / "allowed"),
        export_top=5,
        redacted=True,
        demo_export=True,
    )
    blocked_item = [item for item in blocked["export"]["items"] if item["structure_id"] == "s-redacted-1"][0]
    allowed_item = [item for item in allowed["export"]["items"] if item["structure_id"] == "s-redacted-1"][0]
    assert blocked_item["export_status"] == "blocked"
    assert "policy_blocked" in blocked_item["error"]
    assert allowed_item["export_status"] == "exported"
    assert os.path.exists(allowed_item["cif_path"])


def test_csp_pack_run_logging_steps_and_evidence(tmp_path, monkeypatch):
    db_path = tmp_path / "csp.db"
    _seed_csp_db(db_path)
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])
    result = run_csp_pack(
        db_path=str(db_path),
        query_text=None,
        structure_id="s-layer-1",
        k=4,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        w_text=0.6,
        w_fp=0.4,
        out_dir=str(tmp_path / "id_mode"),
        export_top=3,
        redacted=True,
        demo_export=False,
    )
    assert result["errors"] is None
    report = report_run(run_id=result["run_id"], db_path=str(db_path))
    assert report["run"]["command"] == "csp-pack"
    assert len(report["run_steps"]) == 3
    assert len(report["evidence_bundles"]) == 3
    tools = [step["tool_name"] for step in report["run_steps"]]
    assert tools == ["csp_pack_retrieval", "csp_pack_hints", "csp_pack_export"]
