import os

from crystal_db.audit_log import fetch_audit_bundle
from crystal_db.ingest import ingest_sample
from crystal_db.query import get_structure
from crystal_db.novelty import run_novelty
from crystal_db.agent import run_agent


def test_agent_logs_and_evidence(tmp_path):
    db_path = str(tmp_path / "crystal.db")
    ingest_sample(db_path=db_path, count=20)

    result = run_agent(question="Find structures containing Li and O", db_path=db_path, llm="off")
    bundle = fetch_audit_bundle(result["run_id"], db_path)

    assert "error" not in bundle
    assert bundle["tool_calls"]
    assert bundle["evidence"] is not None
    assert "crystal-" in result["answer"]


def test_novelty_check(tmp_path):
    db_path = str(tmp_path / "crystal.db")
    ingest_sample(db_path=db_path, count=20)

    structure = get_structure("crystal-0001", db_path=db_path)
    assert structure.get("cif_text")

    cif_path = os.path.join(str(tmp_path), "sample.cif")
    with open(cif_path, "w", encoding="utf-8") as f:
        f.write(structure["cif_text"])

    novelty = run_novelty(cif_path=cif_path, db_path=db_path, threshold=25.0, k=3)
    assert novelty["is_novel"] is False
    assert novelty["best_match_structure_id"]
