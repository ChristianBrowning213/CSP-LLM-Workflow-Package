import json
import os
import platform
import random
import time
from typing import Any, Dict, List, Optional

from .db import connect, init_db
from .fingerprint import fingerprint_structure
from .novelty import clear_fingerprint_cache, preload_fingerprint_index, run_novelty
from .query import get_structure, query_structures
from .similarity import similar_structures


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _collect_structure_ids(db_path: Optional[str]) -> List[str]:
    conn = connect(db_path)
    init_db(conn)
    rows = conn.execute("SELECT structure_id FROM structures ORDER BY structure_id").fetchall()
    conn.close()
    return [row["structure_id"] for row in rows]


def run_bench(
    db_path: Optional[str],
    iters: int,
    k: int,
    include_novelty: bool = False,
    novelty_iters: int = 3,
    warm_cache: bool = True,
    timeout_budget_ms: Optional[int] = None,
    profile: bool = False,
) -> Dict[str, Any]:
    structure_ids = _collect_structure_ids(db_path)
    if not structure_ids:
        return {"error": "no_structures"}

    rng = random.Random(7)
    sample_ids = [structure_ids[i % len(structure_ids)] for i in range(iters)]

    # Ensure fingerprints once
    for sid in structure_ids:
        fingerprint_structure(structure_id=sid, db_path=db_path, store=True)

    timings: Dict[str, List[float]] = {
        "query_ms": [],
        "get_with_cif_ms": [],
        "get_no_cif_ms": [],
        "similar_ms": [],
        "novelty_ms": [],
    }

    stopped_early = False
    stop_reason = None
    start_total = _now_ms()

    def _check_budget(stage: str) -> bool:
        nonlocal stopped_early, stop_reason
        if timeout_budget_ms is None:
            return False
        elapsed = _now_ms() - start_total
        if elapsed >= timeout_budget_ms:
            stopped_early = True
            stop_reason = f"timeout_budget_ms exceeded during {stage}"
            return True
        return False

    for _ in range(iters):
        if _check_budget("query"):
            break
        start = _now_ms()
        query_structures({"limit": 5}, db_path=db_path)
        timings["query_ms"].append(_now_ms() - start)

    for sid in sample_ids:
        if _check_budget("get"):
            break
        start = _now_ms()
        get_structure(sid, db_path=db_path, include_cif=True)
        timings["get_with_cif_ms"].append(_now_ms() - start)

        if _check_budget("get"):
            break
        start = _now_ms()
        get_structure(sid, db_path=db_path, include_cif=False)
        timings["get_no_cif_ms"].append(_now_ms() - start)

        if _check_budget("similar"):
            break
        start = _now_ms()
        similar_structures(structure_id=sid, db_path=db_path, k=k)
        timings["similar_ms"].append(_now_ms() - start)

    if include_novelty and not stopped_early:
        if not warm_cache:
            clear_fingerprint_cache()
        else:
            preload_fingerprint_index(db_path, force_reload=True)
        novelty_ids = [structure_ids[i % len(structure_ids)] for i in range(novelty_iters)]
        for sid in novelty_ids:
            if _check_budget("novelty"):
                break
            structure = get_structure(sid, db_path=db_path, include_cif=True)
            cif_text = structure.get("cif_text")
            if not cif_text:
                continue
            start = _now_ms()
            run_novelty(
                cif_text=cif_text,
                db_path=db_path,
                threshold=25.0,
                k=k,
                force_reload=not warm_cache,
            )
            timings["novelty_ms"].append(_now_ms() - start)

    def summarize(values: List[float]) -> Dict[str, float]:
        if not values:
            return {"avg": 0.0, "min": 0.0, "max": 0.0}
        return {
            "avg": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
        }

    report = {
        "env": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "dataset": {
            "structure_count": len(structure_ids),
            "iters": iters,
            "k": k,
            "novelty_iters": novelty_iters if include_novelty else 0,
            "warm_cache": warm_cache,
        },
        "timings_ms": {name: summarize(vals) for name, vals in timings.items()},
        "stopped_early": stopped_early,
        "stop_reason": stop_reason,
        "elapsed_ms": _now_ms() - start_total,
    }

    if profile:
        report["timings_ms_raw"] = timings

    return report
