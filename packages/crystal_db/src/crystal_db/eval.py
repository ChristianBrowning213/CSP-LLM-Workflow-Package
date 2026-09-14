import os
import tempfile

from .agent import run_agent
from .audit_log import fetch_audit_bundle
from .ingest import ingest_sample
from .fingerprint import fingerprint_structure
from .query import get_structure
from .novelty import run_novelty


def _assert_run_has_tool_calls(db_path: str, run_id: str) -> None:
    bundle = fetch_audit_bundle(run_id, db_path)
    assert "error" not in bundle, f"Audit not found for run {run_id}"
    assert bundle["tool_calls"], "No tool calls logged"
    assert bundle["evidence"] is not None, "Evidence bundle missing"


def run_eval(db_path: str) -> dict:
    ingest_sample(db_path=db_path, count=50)

    # Backfill fingerprints to support similarity/novelty
    for i in range(1, 51):
        fingerprint_structure(structure_id=f"crystal-{i:04d}", db_path=db_path, store=True)

    results = {}

    # Q1: metadata retrieval
    q1 = run_agent(question="Find structures containing Li and O", db_path=db_path, llm="off")
    _assert_run_has_tool_calls(db_path, q1["run_id"])
    assert "crystal-" in q1["answer"], "Answer does not cite structure_id"
    results["q1"] = q1["run_id"]

    # Q2: show CIF
    q2 = run_agent(question="Show CIF for crystal-0001", db_path=db_path, llm="off")
    _assert_run_has_tool_calls(db_path, q2["run_id"])
    assert "crystal-0001" in q2["answer"], "Answer missing structure_id"
    results["q2"] = q2["run_id"]

    # Q3: similarity
    q3 = run_agent(question="Find similar structures to crystal-0001", db_path=db_path, llm="off")
    _assert_run_has_tool_calls(db_path, q3["run_id"])
    assert "crystal-" in q3["answer"], "Answer missing structure_id"
    results["q3"] = q3["run_id"]

    # Q4: novelty check using an existing CIF
    structure = get_structure("crystal-0001", db_path=db_path)
    assert structure.get("cif_text") is not None, "CIF not available for novelty test"

    with tempfile.TemporaryDirectory() as tmpdir:
        cif_path = os.path.join(tmpdir, "sample.cif")
        with open(cif_path, "w", encoding="utf-8") as f:
            f.write(structure["cif_text"])

        novelty = run_novelty(cif_path=cif_path, db_path=db_path, threshold=25.0, k=3, run_name="eval-novelty")
        _assert_run_has_tool_calls(db_path, novelty["run_id"])
        assert novelty["best_match_structure_id"], "Novelty check missing best match"
        assert novelty["is_novel"] is False, "Novelty should be false for identical CIF"
        results["q4"] = novelty["run_id"]

    return results
