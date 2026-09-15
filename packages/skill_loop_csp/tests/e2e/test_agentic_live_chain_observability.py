from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from sok_llm_orchestrator.agentic.archive import write_agentic_llm_trace_markdown
from sok_llm_orchestrator.agentic.evaluator_runtime import run_live_evaluator
from sok_llm_orchestrator.agentic.llm_runtime import AgentLLMRuntime
from sok_llm_orchestrator.agentic.planner_runtime import run_live_planner_and_compile
from sok_llm_orchestrator.agentic.run_manager_runtime import run_live_run_manager
from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.llm.client import LLMClient


pytestmark = pytest.mark.live_llm


def _require_live_settings() -> Settings:
    if os.environ.get("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to run live LLM tests.")
    settings = Settings.from_sources(None)
    if settings.llm_api_key is None or settings.llm_model is None:
        pytest.skip("Live LLM settings are not configured.")
    return settings


def _write_summary(
    out_dir: Path,
    planner_result: dict[str, object],
    run_manager_result: dict[str, object],
    evaluator_result: dict[str, object],
    planner_json: Path,
    planner_md: Path,
    run_manager_json: Path,
    run_manager_md: Path,
    evaluator_json: Path,
    evaluator_md: Path,
) -> Path:
    summary_path = out_dir / "combined_agentic_live_chain_summary.md"
    run_plan = planner_result["run_plan"]
    compile_result = planner_result["compile_result"]
    lines = [
        "# Agentic Live Chain Summary",
        "",
        f"- Overall Goal: {run_plan['overall_goal']}",
        f"- Run Goal: {run_plan['run_goal']}",
        f"- Planner Schema: {run_plan['schema_version']}",
        f"- Compile Schema: {compile_result['schema_version']}",
        f"- Run Manager Schema: {run_manager_result['schema_version']}",
        f"- Evaluator Schema: {evaluator_result['schema_version']}",
        f"- Proposal Count: {planner_result['proposal_count']}",
        f"- Valid Proposal Count: {planner_result['valid_proposal_count']}",
        f"- Invalid Proposal Count: {planner_result['invalid_proposal_count']}",
        "",
        "## Trace Files",
        "",
        f"- Planner JSON: {planner_json}",
        f"- Planner Markdown: {planner_md}",
        f"- Run Manager JSON: {run_manager_json}",
        f"- Run Manager Markdown: {run_manager_md}",
        f"- Evaluator JSON: {evaluator_json}",
        f"- Evaluator Markdown: {evaluator_md}",
    ]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def test_agentic_live_chain_observability_writes_json_and_markdown_traces() -> None:
    settings = _require_live_settings()
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model or "",
        timeout_s=settings.llm_timeout_s,
        max_retries=1,
    )
    runtime = AgentLLMRuntime(client=client, max_attempts=2)

    root = Path.cwd() / "test_workdir" / "agentic_live_observability"
    root.mkdir(parents=True, exist_ok=True)
    case_dir = root / f"case_{uuid4().hex}"
    case_dir.mkdir()
    planner_dir = case_dir / "planner"
    planner_dir.mkdir()
    run_manager_dir = case_dir / "run_manager"
    run_manager_dir.mkdir()
    evaluator_dir = case_dir / "evaluator"
    evaluator_dir.mkdir()

    planner_result = run_live_planner_and_compile(
        runtime,
        {
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
        out_dir=planner_dir,
        archive_trace=True,
        require_proposals=True,
    )
    run_manager_result = run_live_run_manager(
        runtime,
        {
            "run_id": "run_001",
            "run_plan": planner_result["run_plan"],
            "compile_result": planner_result["compile_result"],
            "proposal_count": planner_result["proposal_count"],
            "valid_proposal_count": planner_result["valid_proposal_count"],
            "invalid_proposal_count": planner_result["invalid_proposal_count"],
            "warnings": planner_result["warnings"],
        },
        out_dir=run_manager_dir,
        archive_trace=True,
    )
    evaluator_result = run_live_evaluator(
        runtime,
        {
            "run_id": "run_001",
            "run_plan": planner_result["run_plan"],
            "compile_result": planner_result["compile_result"],
            "run_manager_log": run_manager_result,
            "proposal_count": planner_result["proposal_count"],
            "valid_proposal_count": planner_result["valid_proposal_count"],
            "invalid_proposal_count": planner_result["invalid_proposal_count"],
            "warnings": planner_result["warnings"],
        },
        out_dir=evaluator_dir,
        archive_trace=True,
    )

    planner_json = planner_dir / "agentic_llm_trace_planner.json"
    planner_md = Path(
        write_agentic_llm_trace_markdown(
            json.loads(planner_json.read_text(encoding="utf-8")),
            planner_dir,
            "planner",
        )["markdown_path"]
    )
    run_manager_json = run_manager_dir / "agentic_llm_trace_run_manager.json"
    run_manager_md = Path(
        write_agentic_llm_trace_markdown(
            json.loads(run_manager_json.read_text(encoding="utf-8")),
            run_manager_dir,
            "run_manager",
        )["markdown_path"]
    )
    evaluator_json = evaluator_dir / "agentic_llm_trace_evaluator.json"
    evaluator_md = Path(
        write_agentic_llm_trace_markdown(
            json.loads(evaluator_json.read_text(encoding="utf-8")),
            evaluator_dir,
            "evaluator",
        )["markdown_path"]
    )
    summary_path = _write_summary(
        case_dir,
        planner_result,
        run_manager_result,
        evaluator_result,
        planner_json,
        planner_md,
        run_manager_json,
        run_manager_md,
        evaluator_json,
        evaluator_md,
    )

    print(f"AGENTIC_TRACE_JSON={planner_json}")
    print(f"AGENTIC_TRACE_MD={planner_md}")
    print(f"AGENTIC_TRACE_JSON={run_manager_json}")
    print(f"AGENTIC_TRACE_MD={run_manager_md}")
    print(f"AGENTIC_TRACE_JSON={evaluator_json}")
    print(f"AGENTIC_TRACE_MD={evaluator_md}")
    print(f"AGENTIC_CHAIN_SUMMARY_MD={summary_path}")

    assert planner_json.exists()
    assert planner_md.exists()
    assert run_manager_json.exists()
    assert run_manager_md.exists()
    assert evaluator_json.exists()
    assert evaluator_md.exists()
    assert summary_path.exists()
    assert planner_result["proposal_count"] >= 1
    assert planner_result["valid_proposal_count"] >= 1
    compile_result = planner_result["compile_result"]
    assert compile_result["proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert compile_result["validation_results"][0]["valid"] is True
