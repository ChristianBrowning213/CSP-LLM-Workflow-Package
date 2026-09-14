import json

from crystal_db.__main__ import main
from crystal_db.db import connect, init_db
from crystal_db.gate import run_gate_retrieval
from crystal_db.schema_validate import validate


def _seed_gate_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    conn.close()


def _write_cases(path):
    case = {
        "case_id": "g1",
        "query": "layered material",
        "expected": {"must_contain_any": ["layered"]},
    }
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(case) + "\n")


def test_gate_retrieval_passes_thresholds(monkeypatch, tmp_path):
    db_path = tmp_path / "gate.db"
    cases_path = tmp_path / "cases.jsonl"
    _seed_gate_db(db_path)
    _write_cases(cases_path)

    def fake_bench(**kwargs):  # noqa: ARG001
        return {
            "run_id": "bench-ok",
            "summary": {
                "hit_at_k": 0.9,
                "mrr": 0.8,
                "ndcg_at_k": 0.85,
                "coverage": 1.0,
                "avg_score": 0.7,
                "failure_breakdown": {},
                "total_cases": 5,
            },
            "errors": None,
        }

    monkeypatch.setattr("crystal_db.gate.run_bench_retrieval", fake_bench)
    result = run_gate_retrieval(
        db_path=str(db_path),
        cases_path=str(cases_path),
        min_hit_at_k=0.5,
        min_mrr=0.5,
        min_ndcg_at_k=0.5,
        min_coverage=0.9,
        max_failure_rate=0.2,
    )
    assert result["ok"] is True
    assert result["error_code"] is None
    validate(result, "gate_retrieval.v1")


def test_gate_retrieval_cli_fails_with_exit_2(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "gate.db"
    cases_path = tmp_path / "cases.jsonl"
    _seed_gate_db(db_path)
    _write_cases(cases_path)

    def fake_bench(**kwargs):  # noqa: ARG001
        return {
            "run_id": "bench-low",
            "summary": {
                "hit_at_k": 0.01,
                "mrr": 0.01,
                "ndcg_at_k": 0.01,
                "coverage": 0.2,
                "avg_score": 0.1,
                "failure_breakdown": {"candidate_set_empty": 4},
                "total_cases": 5,
            },
            "errors": None,
        }

    monkeypatch.setattr("crystal_db.gate.run_bench_retrieval", fake_bench)
    code = main(
        [
            "gate-retrieval",
            "--db",
            str(db_path),
            "--cases",
            str(cases_path),
            "--min-hit-at-k",
            "0.10",
            "--min-ndcg-at-k",
            "0.05",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert code == 2
    assert payload["error_code"] == "RETRIEVAL_REGRESSION"
    assert "current" in payload
    assert "thresholds" in payload


def test_gate_retrieval_baseline_delta(monkeypatch, tmp_path):
    db_path = tmp_path / "gate.db"
    cases_path = tmp_path / "cases.jsonl"
    baseline_path = tmp_path / "baseline.json"
    _seed_gate_db(db_path)
    _write_cases(cases_path)
    with open(baseline_path, "w", encoding="utf-8") as handle:
        json.dump({"summary": {"hit_at_k": 0.9, "mrr": 0.9, "ndcg_at_k": 0.9, "coverage": 0.9}}, handle)

    def fake_bench(**kwargs):  # noqa: ARG001
        return {
            "run_id": "bench-low",
            "summary": {
                "hit_at_k": 0.7,
                "mrr": 0.7,
                "ndcg_at_k": 0.7,
                "coverage": 0.7,
                "avg_score": 0.7,
                "failure_breakdown": {},
                "total_cases": 5,
            },
            "errors": None,
        }

    monkeypatch.setattr("crystal_db.gate.run_bench_retrieval", fake_bench)
    result = run_gate_retrieval(
        db_path=str(db_path),
        cases_path=str(cases_path),
        baseline_summary_path=str(baseline_path),
        baseline_delta=0.05,
    )
    assert result["ok"] is False
    assert any(reason.startswith("baseline_") for reason in result["reasons"])
