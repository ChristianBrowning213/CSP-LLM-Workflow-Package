import json

from crystal_db.calibrate import run_retrieval_calibration
from crystal_db.db import connect, init_db
from crystal_db.schema_validate import validate


def _seed_empty_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    conn.close()


def _write_cases(path):
    case = {
        "case_id": "c1",
        "query": "layered material",
        "expected": {"must_contain_any": ["layered"]},
    }
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(case) + "\n")


def test_run_retrieval_calibration_deterministic_best(monkeypatch, tmp_path):
    db_path = tmp_path / "cal.db"
    cases_path = tmp_path / "cases.jsonl"
    out_dir = tmp_path / "out"
    _seed_empty_db(db_path)
    _write_cases(cases_path)

    def fake_cache_records(**kwargs):  # noqa: ARG001
        return [{"case_id": "c1", "expected_structure_ids": ["s1"], "candidates": [], "error": None}]

    def fake_score_cached_case(
        *,
        record,  # noqa: ARG001
        k,  # noqa: ARG001
        w_text,
        hybrid,  # noqa: ARG001
        text_sim_threshold,
        fp_sim_threshold,
    ):
        text_t = float(text_sim_threshold)
        fp_t = float(fp_sim_threshold)
        score = 1.0 - abs(w_text - 0.7) - abs(text_t - 0.8) - abs(fp_t - 0.9)
        return {
            "status": "ok",
            "errors": None,
            "metrics": {
                "hit": 1 if score > 0 else 0,
                "rr": round(max(0.0, score - 0.05), 8),
                "ndcg": round(max(0.0, score + 0.1), 8),
                "max_relevance": 1 if score > 0 else 0,
                "normalized_relevance": 1.0 if score > 0 else 0.0,
                "hint_fallback_used": False,
            },
            "top_hits": [{"rank": 1, "structure_id": "s1", "score": round(max(0.0, score), 8)}],
        }

    monkeypatch.setattr("crystal_db.calibrate.count_candidate_embeddings", lambda *args, **kwargs: 1)
    monkeypatch.setattr("crystal_db.calibrate._build_candidate_cache_records", fake_cache_records)
    monkeypatch.setattr("crystal_db.calibrate._score_cached_case", fake_score_cached_case)

    result = run_retrieval_calibration(
        db_path=str(db_path),
        cases_path=str(cases_path),
        out_dir=str(out_dir),
        k=5,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=True,
        redacted=True,
        text_sim_min=0.8,
        text_sim_max=0.85,
        text_sim_step=0.05,
        fp_sim_min=0.9,
        fp_sim_max=0.92,
        fp_sim_step=0.02,
        w_text_values=[0.6, 0.7, 0.8],
    )
    assert result["errors"] is None
    assert result["best"]["w_text"] == 0.7
    assert result["best"]["text_sim_threshold"] == 0.8
    assert result["best"]["fp_sim_threshold"] == 0.9
    assert (out_dir / "calibration_summary.json").exists()
    assert (out_dir / "calibration_results.csv").exists()
    assert (out_dir / "calibration_best.json").exists()
    validate(result, "calibration.v1")


def test_run_retrieval_calibration_respects_max_cases_and_progress(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "cal_progress.db"
    cases_path = tmp_path / "cases.jsonl"
    out_dir = tmp_path / "out_progress"
    _seed_empty_db(db_path)
    _write_cases(cases_path)

    cache_calls = {"cases_count": 0}

    def fake_cache_records(*, cases, **kwargs):  # noqa: ARG001
        cache_calls["cases_count"] = len(cases)
        return [
            {
                "case_id": f"case-{idx}",
                "expected_structure_ids": [f"s-{idx}"],
                "candidates": [{"structure_id": f"s-{idx}", "text_score": 1.0, "fp_score": 1.0}],
                "error": None,
            }
            for idx in range(1, len(cases) + 1)
        ]

    monkeypatch.setattr("crystal_db.calibrate.count_candidate_embeddings", lambda *args, **kwargs: 1)
    monkeypatch.setattr("crystal_db.calibrate._build_candidate_cache_records", fake_cache_records)

    result = run_retrieval_calibration(
        db_path=str(db_path),
        cases_path=str(cases_path),
        out_dir=str(out_dir),
        k=5,
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
        w_text_values=[0.6, 0.7],
        preembed_queries=False,
        max_cases=2,
        progress_every=1,
    )
    captured = capsys.readouterr()
    assert result["errors"] is None
    assert (out_dir / "calibration_summary.json").exists()
    assert (out_dir / "calibration_results.csv").exists()
    assert (out_dir / "calibration_best.json").exists()
    assert cache_calls["cases_count"] == 1
    assert "[calibrate] sweep 1/2" in captured.err
    assert "cases 1/1" in captured.err
