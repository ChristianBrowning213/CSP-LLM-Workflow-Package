from typing import Any, Dict, List, Optional

from .retrieval import text_search
from .runlog import RunLogger
from .utils import now_iso_utc


def _summarize_neighbors(neighbors: List[Dict[str, Any]]) -> str:
    if not neighbors:
        return "No comparable structures were found."
    top = neighbors[:3]
    lines = []
    for item in top:
        structure_id = item.get("structure_id")
        score = float(item.get("score", 0.0))
        provenance = item.get("provenance") or {}
        source = provenance.get("source")
        source_id = provenance.get("source_id")
        lines.append(f"- {structure_id} (score={score:.4f}, source={source}, source_id={source_id})")
    return "Top retrieved structures:\n" + "\n".join(lines)


def run_phase2_agent(
    *,
    query: str,
    db_path: Optional[str],
    k: int = 10,
    embed_engine: str = "auto",
    model_name: Optional[str] = None,
    model_version: Optional[str] = None,
    text_engine: str = "robocrys",
    text_view: str = "robocrys",
    hybrid: bool = False,
    w_text: float = 1.0,
    w_fp: float = 0.0,
    run_name: Optional[str] = None,
) -> Dict[str, Any]:
    args = {
        "query": query,
        "k": k,
        "engine": embed_engine,
        "model": model_name,
        "model_version": model_version,
        "text_engine": text_engine,
        "text_view": text_view,
        "hybrid": hybrid,
        "w_text": w_text,
        "w_fp": w_fp,
        "run_name": run_name,
    }
    logger = RunLogger(db_path)
    try:
        run_id = logger.start_run("agent", args)
    except Exception as exc:  # pylint: disable=broad-except
        return {
            "run_id": None,
            "answer": None,
            "cited_structure_ids": [],
            "evidence": None,
            "errors": {"code": "run_start_failed", "message": str(exc)},
        }

    started = now_iso_utc()
    retrieval = text_search(
        query_text=query,
        db_path=db_path,
        k=k,
        embed_engine=embed_engine,
        model_name=model_name,
        model_version=model_version,
        text_engine=text_engine,
        text_view=text_view,
        hybrid=hybrid,
        w_text=w_text,
        w_fp=w_fp,
        show_text_top=min(3, max(0, k)),
        export_dir=None,
        export_top=0,
        redacted=True,
        demo_export=False,
    )
    ended = now_iso_utc()
    retrieval_errors = retrieval.get("errors")
    logger.log_step(
        "text_search",
        {
            "query": query,
            "k": k,
            "embed_engine": embed_engine,
            "model_name": model_name,
            "model_version": model_version,
            "text_engine": text_engine,
            "text_view": text_view,
            "hybrid": hybrid,
            "w_text": w_text,
            "w_fp": w_fp,
        },
        retrieval,
        "error" if retrieval_errors else "ok",
        error_text=(retrieval_errors or {}).get("message") if isinstance(retrieval_errors, dict) else None,
        started_at=started,
        ended_at=ended,
    )
    logger.add_evidence(
        "retrieval",
        {
            "query": retrieval.get("query"),
            "neighbors": retrieval.get("neighbors", []),
            "errors": retrieval_errors,
        },
    )

    if retrieval_errors:
        logger.finalize_run(status="error", error_text=(retrieval_errors or {}).get("message"))
        return {
            "run_id": run_id,
            "answer": None,
            "cited_structure_ids": [],
            "evidence": None,
            "errors": retrieval_errors,
        }

    neighbors = retrieval.get("neighbors", [])
    if not neighbors:
        err = {
            "code": "no_neighbors",
            "message": "No neighbors returned by retrieval.",
            "diagnostics": {"k": k},
        }
        logger.add_evidence("answer", {"error": err})
        logger.finalize_run(status="error", error_text=err["message"])
        return {
            "run_id": run_id,
            "answer": None,
            "cited_structure_ids": [],
            "evidence": None,
            "errors": err,
        }

    cited_structure_ids: List[str] = []
    for item in neighbors:
        structure_id = item.get("structure_id")
        if not structure_id:
            continue
        cited_structure_ids.append(structure_id)
        logger.add_explored(structure_id, "retrieved_neighbor")

    summary = _summarize_neighbors(neighbors)
    answer_evidence = {
        "summary": summary,
        "cited_structure_ids": cited_structure_ids,
        "top_neighbors": neighbors[: min(5, len(neighbors))],
    }
    logger.add_evidence("answer", answer_evidence)
    logger.finalize_run(status="ok")

    return {
        "run_id": run_id,
        "answer": summary,
        "cited_structure_ids": cited_structure_ids,
        "evidence": answer_evidence,
        "errors": None,
    }
