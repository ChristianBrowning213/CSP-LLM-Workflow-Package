import json
import os
import time

from crystal_db.audit_log import fetch_audit_bundle
from crystal_db.export_run import export_run
from crystal_db.ingest_folder import ingest_folder
from crystal_db.query import get_structure
from crystal_db.agent import run_agent
from crystal_db.bench import run_bench
from crystal_db.fingerprint import fingerprint_structure
from crystal_db import novelty as novelty_module
from crystal_db.db import connect, init_db
from crystal_db.ingest import ingest_sample


def _make_cif(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "data_test\n"
            "_symmetry_space_group_name_H-M 'P1'\n"
            "_cell_length_a 5.0\n"
            "_cell_length_b 5.0\n"
            "_cell_length_c 5.0\n"
            "_cell_angle_alpha 90\n"
            "_cell_angle_beta 90\n"
            "_cell_angle_gamma 90\n"
            "_chemical_formula_sum 'Li2O'\n"
        )


def test_restricted_cif_never_exposed(tmp_path):
    db_path = str(tmp_path / "crystal.db")
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    cif_path = cif_dir / "sample.cif"
    _make_cif(str(cif_path))

    ingest_folder(
        db_path=db_path,
        folder_path=str(cif_dir),
        source="local_cif",
        policy_name="restricted",
        cache_dir=None,
    )

    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT structure_id FROM provenance WHERE source = ? AND source_id = ?",
        ("local_cif", "sample.cif"),
    ).fetchone()
    conn.close()

    structure_id = row["structure_id"]
    result = get_structure(structure_id, db_path=db_path)
    assert result["cif_text"] is None

    agent_result = run_agent(question=f"Show CIF for {structure_id}", db_path=db_path, llm="off")
    bundle = fetch_audit_bundle(agent_result["run_id"], db_path)

    tool_payloads = json.dumps(bundle)
    assert "data_test" not in tool_payloads

    export_path = os.path.join(str(tmp_path), "run.json")
    export_run(db_path=db_path, run_id=agent_result["run_id"], out_path=export_path)
    exported = open(export_path, "r", encoding="utf-8").read()
    assert "data_test" not in exported


def test_ingest_folder_idempotent(tmp_path):
    db_path = str(tmp_path / "crystal.db")
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    cif_path = cif_dir / "sample.cif"
    _make_cif(str(cif_path))

    ingest_folder(
        db_path=db_path,
        folder_path=str(cif_dir),
        source="local_cif",
        policy_name="local_cif",
        cache_dir=None,
    )
    ingest_folder(
        db_path=db_path,
        folder_path=str(cif_dir),
        source="local_cif",
        policy_name="local_cif",
        cache_dir=None,
    )

    conn = connect(db_path)
    init_db(conn)
    count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM provenance WHERE source = ?",
        ("local_cif",),
    ).fetchone()["cnt"]
    conn.close()

    assert count == 1


def test_bench_report(tmp_path):
    db_path = str(tmp_path / "crystal.db")
    ingest_sample(db_path=db_path, count=10)

    report = run_bench(db_path, iters=3, k=3, include_novelty=False, timeout_budget_ms=2000)
    assert report.get("timings_ms")


def test_bench_skip_novelty_fast(tmp_path):
    db_path = str(tmp_path / "crystal.db")
    ingest_sample(db_path=db_path, count=10)

    start = time.perf_counter()
    report = run_bench(db_path, iters=2, k=3, include_novelty=False, timeout_budget_ms=2000)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert report["timings_ms"]["novelty_ms"]["avg"] == 0.0
    assert elapsed_ms < 2000.0


def test_novelty_does_not_recompute_db_fingerprints(tmp_path, monkeypatch):
    db_path = str(tmp_path / "crystal.db")
    ingest_sample(db_path=db_path, count=10)

    # Precompute fingerprints for all structures
    for i in range(1, 11):
        fingerprint_structure(structure_id=f"crystal-{i:04d}", db_path=db_path, store=True)

    original_fp = novelty_module.fingerprint_structure

    def wrapped_fingerprint_structure(*args, **kwargs):
        if kwargs.get("structure_id"):
            raise AssertionError("DB fingerprint recomputation detected")
        return original_fp(*args, **kwargs)

    monkeypatch.setattr(novelty_module, "fingerprint_structure", wrapped_fingerprint_structure)

    structure = get_structure("crystal-0001", db_path=db_path)
    assert structure.get("cif_text")

    novelty = novelty_module.run_novelty(cif_text=structure["cif_text"], db_path=db_path, threshold=25.0, k=3)
    assert novelty["best_match_structure_id"]
    assert "load_db_fps_ms" in novelty["timings_ms"]
