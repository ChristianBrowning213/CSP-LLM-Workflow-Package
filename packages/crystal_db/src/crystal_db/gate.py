import json
import os
from typing import Any, Dict, Optional

from .bench_retrieval import run_bench_retrieval
from .runlog import RunLogger


def _load_baseline(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and "summary" in payload and isinstance(payload["summary"], dict):
        return payload["summary"]
    if isinstance(payload, dict):
        return payload
    return None


def _metric(summary: Dict[str, Any], name: str) -> float:
    try:
        return float(summary.get(name, 0.0))
    except (TypeError, ValueError):
        return 0.0


def run_gate_retrieval(
    *,
    db_path: Optional[str],
    cases_path: str,
    k: int = 10,
    embed_engine: str = "auto",
    model_name: Optional[str] = None,
    model_version: Optional[str] = None,
    text_engine: str = "caption",
    text_view: str = "caption",
    hybrid: bool = True,
    w_text: float = 0.7,
    w_fp: float = 0.3,
    redacted: bool = True,
    out_dir: Optional[str] = None,
    baseline_summary_path: Optional[str] = None,
    min_hit_at_k: Optional[float] = None,
    min_mrr: Optional[float] = None,
    min_ndcg_at_k: Optional[float] = None,
    min_coverage: Optional[float] = None,
    max_failure_rate: Optional[float] = None,
    baseline_delta: float = 0.0,
    run_name: Optional[str] = None,
) -> Dict[str, Any]:
    logger = RunLogger(db_path)
    run_id = logger.start_run(
        "gate-retrieval",
        {
            "cases_path": cases_path,
            "k": k,
            "engine": embed_engine,
            "model": model_name,
            "model_version": model_version,
            "text_engine": text_engine,
            "text_view": text_view,
            "hybrid": hybrid,
            "w_text": w_text,
            "w_fp": w_fp,
            "redacted": redacted,
            "baseline_summary_path": baseline_summary_path,
            "min_hit_at_k": min_hit_at_k,
            "min_mrr": min_mrr,
            "min_ndcg_at_k": min_ndcg_at_k,
            "min_coverage": min_coverage,
            "max_failure_rate": max_failure_rate,
            "baseline_delta": baseline_delta,
            "run_name": run_name,
        },
    )

    bench = run_bench_retrieval(
        db_path=db_path,
        cases_path=cases_path,
        k=k,
        embed_engine=embed_engine,
        model_name=model_name,
        model_version=model_version,
        text_engine=text_engine,
        text_view=text_view,
        hybrid=hybrid,
        w_text=w_text,
        w_fp=w_fp,
        redacted=redacted,
        out_dir=None,
        run_name=run_name,
    )
    if bench.get("errors") is not None:
        logger.log_step("benchmark", {"cases_path": cases_path}, bench, "error", error_text=bench["errors"].get("message"))
        logger.finalize_run(status="error", error_text=bench["errors"].get("message"))
        return {
            "schema_version": "gate_retrieval.v1",
            "run_id": run_id,
            "ok": False,
            "error_code": "BENCHMARK_FAILED",
            "baseline": None,
            "current": None,
            "diff": None,
            "thresholds": None,
            "reasons": ["benchmark_failed"],
            "errors": bench.get("errors"),
        }

    current = bench.get("summary") or {}
    baseline = _load_baseline(baseline_summary_path)
    failure_count = sum(int(value) for value in (current.get("failure_breakdown") or {}).values())
    total_cases = max(1, int(current.get("total_cases", 0)))
    failure_rate = float(failure_count) / float(total_cases)
    current_with_rate = dict(current)
    current_with_rate["failure_rate"] = round(failure_rate, 8)

    thresholds = {
        "min_hit_at_k": min_hit_at_k,
        "min_mrr": min_mrr,
        "min_ndcg_at_k": min_ndcg_at_k,
        "min_coverage": min_coverage,
        "max_failure_rate": max_failure_rate,
        "baseline_delta": baseline_delta,
    }
    reasons = []
    if min_hit_at_k is not None and _metric(current, "hit_at_k") < float(min_hit_at_k):
        reasons.append("min_hit_at_k")
    if min_mrr is not None and _metric(current, "mrr") < float(min_mrr):
        reasons.append("min_mrr")
    if min_ndcg_at_k is not None and _metric(current, "ndcg_at_k") < float(min_ndcg_at_k):
        reasons.append("min_ndcg_at_k")
    if min_coverage is not None and _metric(current, "coverage") < float(min_coverage):
        reasons.append("min_coverage")
    if max_failure_rate is not None and failure_rate > float(max_failure_rate):
        reasons.append("max_failure_rate")

    diff = None
    if baseline is not None:
        diff = {
            "hit_at_k": round(_metric(current, "hit_at_k") - _metric(baseline, "hit_at_k"), 8),
            "mrr": round(_metric(current, "mrr") - _metric(baseline, "mrr"), 8),
            "ndcg_at_k": round(_metric(current, "ndcg_at_k") - _metric(baseline, "ndcg_at_k"), 8),
            "coverage": round(_metric(current, "coverage") - _metric(baseline, "coverage"), 8),
        }
        for key in ("hit_at_k", "mrr", "ndcg_at_k", "coverage"):
            if diff[key] < -float(baseline_delta):
                reasons.append(f"baseline_{key}")

    ok = len(reasons) == 0
    payload = {
        "schema_version": "gate_retrieval.v1",
        "run_id": run_id,
        "ok": ok,
        "error_code": None if ok else "RETRIEVAL_REGRESSION",
        "baseline": baseline,
        "current": current_with_rate,
        "diff": diff,
        "thresholds": thresholds,
        "reasons": reasons,
        "errors": None,
    }
    logger.log_step(
        "evaluate_gate",
        {"thresholds": thresholds, "baseline_summary_path": baseline_summary_path},
        payload,
        "ok" if ok else "error",
        error_text=None if ok else "retrieval_regression",
    )
    logger.add_evidence("gate_report", payload)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        report_path = os.path.join(out_dir, "gate_report.json")
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        payload["report_path"] = report_path
        logger.log_step("export", {"out_dir": out_dir}, {"report_path": report_path}, "ok")

    logger.finalize_run(status="ok" if ok else "error", error_text=None if ok else "retrieval_regression")
    return payload
