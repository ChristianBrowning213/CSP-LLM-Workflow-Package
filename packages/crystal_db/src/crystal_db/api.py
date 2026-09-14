import json
from typing import Any, Dict, Optional

from .bench_retrieval import run_bench_retrieval
from .csp_pack import run_csp_pack
from .novelty_check import run_novelty_check
from .agent import run_agent
from .readiness import inspect_backend_readiness
from .retrieval import text_search
from .schema_validate import validate


def _validate_or_raise(payload: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
    try:
        validate(payload, schema_name)
    except ValueError as exc:
        detail = {
            "code": "schema_validation_failed",
            "schema": schema_name,
            "error": str(exc),
        }
        raise ValueError(json.dumps(detail)) from exc
    return payload


def retrieve_text(
    db_path: Optional[str],
    query: str,
    *,
    k: int,
    embed_engine: str,
    model: Optional[str],
    model_version: Optional[str],
    text_engine: str = "robocrys",
    text_view: str = "robocrys",
    hybrid: bool = False,
    w_text: float = 1.0,
    w_fp: float = 0.0,
    redacted: bool = True,
    show_text_top: int = 0,
    demo_export: bool = False,
) -> Dict[str, Any]:
    result = text_search(
        query_text=query,
        db_path=db_path,
        k=k,
        embed_engine=embed_engine,
        model_name=model,
        model_version=model_version,
        text_engine=text_engine,
        text_view=text_view,
        hybrid=hybrid,
        w_text=w_text,
        w_fp=w_fp,
        show_text_top=show_text_top,
        export_dir=None,
        export_top=0,
        redacted=redacted,
        demo_export=demo_export,
    )
    payload = dict(result)
    payload["schema_version"] = "text_search.v1"
    return _validate_or_raise(payload, "text_search.v1")


def make_csp_pack(
    db_path: Optional[str],
    *,
    query: Optional[str] = None,
    structure_id: Optional[str] = None,
    out_dir: Optional[str] = None,
    export_top: int = 0,
    redacted: bool = True,
    demo_export: bool = False,
    k: int = 10,
    embed_engine: str = "auto",
    model: Optional[str] = None,
    model_version: Optional[str] = None,
    text_engine: str = "caption",
    text_view: str = "caption",
    hybrid: bool = True,
    w_text: float = 0.7,
    w_fp: float = 0.3,
    material_system: Optional[str] = None,
    formula: Optional[str] = None,
    semantic_min_threshold: Optional[float] = None,
    spp_corpus_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = run_csp_pack(
        db_path=db_path,
        query_text=query,
        structure_id=structure_id,
        k=k,
        embed_engine=embed_engine,
        model_name=model,
        model_version=model_version,
        text_engine=text_engine,
        text_view=text_view,
        hybrid=hybrid,
        w_text=w_text,
        w_fp=w_fp,
        out_dir=out_dir,
        export_top=export_top,
        redacted=redacted,
        demo_export=demo_export,
        material_system=material_system,
        formula=formula,
        semantic_min_threshold=semantic_min_threshold,
        spp_corpus_config=spp_corpus_config,
    )
    payload = dict(result)
    payload["schema_version"] = "csp_pack.v1"
    return _validate_or_raise(payload, "csp_pack.v1")


def backend_status(
    db_path: Optional[str],
    *,
    surface: str = "text_search",
    query_mode: str = "query",
    structure_id: Optional[str] = None,
    embed_engine: str = "auto",
    model: Optional[str] = None,
    model_version: Optional[str] = None,
    text_engine: str = "robocrys",
    text_view: str = "robocrys",
    hybrid: bool = False,
) -> Dict[str, Any]:
    payload = inspect_backend_readiness(
        db_path=db_path or "",
        surface=surface,
        query_mode=query_mode,
        text_engine=text_engine,
        text_view=text_view,
        embed_engine=embed_engine,
        model_name=model or "hash-embed",
        model_version=model_version or "v1",
        require_fingerprint_index=bool(hybrid and surface == "csp_pack"),
        query_structure_id=structure_id,
    )
    payload["schema_version"] = "backend_status.v1"
    return _validate_or_raise(payload, "backend_status.v1")


def novelty_check(
    db_path: Optional[str],
    *,
    structure_id: Optional[str] = None,
    cif_path: Optional[str] = None,
    k: int,
    embed_engine: str,
    model: Optional[str],
    model_version: Optional[str],
    text_sim_threshold: float = 0.80,
    fp_sim_threshold: float = 0.95,
    force: bool = False,
) -> Dict[str, Any]:
    result = run_novelty_check(
        db_path=db_path,
        structure_id=structure_id,
        cif_path=cif_path,
        k=k,
        embed_engine=embed_engine,
        model_name=model,
        model_version=model_version,
        text_sim_threshold=text_sim_threshold,
        fp_sim_threshold=fp_sim_threshold,
        force=force,
    )
    payload = dict(result)
    payload["schema_version"] = "novelty_check.v1"
    return _validate_or_raise(payload, "novelty_check.v1")


def bench_retrieval(
    db_path: Optional[str],
    cases_path: str,
    *,
    k: int,
    embed_engine: str,
    model: Optional[str],
    model_version: Optional[str],
    text_engine: str,
    text_view: str,
    hybrid: bool,
    w_text: float,
    w_fp: float,
    redacted: bool,
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    result = run_bench_retrieval(
        db_path=db_path,
        cases_path=cases_path,
        k=k,
        embed_engine=embed_engine,
        model_name=model,
        model_version=model_version,
        text_engine=text_engine,
        text_view=text_view,
        hybrid=hybrid,
        w_text=w_text,
        w_fp=w_fp,
        redacted=redacted,
        out_dir=out_dir,
    )
    payload = dict(result)
    payload["schema_version"] = "bench_retrieval.v1"
    return _validate_or_raise(payload, "bench_retrieval.v1")


def agent(
    db_path: Optional[str],
    *,
    question: str,
    llm: str = "off",
    run_name: Optional[str] = None,
) -> Dict[str, Any]:
    question_value = (question or "").strip()
    if not question_value:
        payload = {
            "run_id": None,
            "answer": "",
            "evidence": {"structures": []},
            "errors": {
                "code": "invalid_input",
                "message": "question is empty",
            },
        }
        payload["schema_version"] = "agent.v1"
        return _validate_or_raise(payload, "agent.v1")

    result = run_agent(
        question=question_value,
        db_path=db_path,
        llm=llm,
        run_name=run_name,
    )
    payload = dict(result)
    payload.setdefault("evidence", {"structures": []})
    payload["errors"] = None
    payload["schema_version"] = "agent.v1"
    return _validate_or_raise(payload, "agent.v1")
