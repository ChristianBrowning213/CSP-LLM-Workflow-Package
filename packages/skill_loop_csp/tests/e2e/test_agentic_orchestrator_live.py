from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from sok_llm_orchestrator.agentic.archive import write_agentic_llm_trace_markdown
from sok_llm_orchestrator.agentic.evaluator_runtime import run_live_evaluator
from sok_llm_orchestrator.agentic.llm_runtime import AgentLLMRuntime
from sok_llm_orchestrator.agentic.orchestrator_runtime import run_live_orchestrator
from sok_llm_orchestrator.agentic.planner_runtime import run_live_planner_and_compile
from sok_llm_orchestrator.agentic.run_manager_runtime import run_live_run_manager
from sok_llm_orchestrator.agentic.schemas import ORCHESTRATOR_DECISION_SCHEMA_VERSION
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


def test_live_orchestrator_reviews_full_non_execution_chain_and_writes_trace() -> None:
    settings = _require_live_settings()
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model or "",
        timeout_s=settings.llm_timeout_s,
        max_retries=1,
    )
    runtime = AgentLLMRuntime(client=client, max_attempts=2)

    root = Path.cwd() / "test_workdir" / "agentic_live_orchestrator"
    root.mkdir(parents=True, exist_ok=True)
    planner_trace_dir = root / f"planner_{uuid4().hex}"
    planner_trace_dir.mkdir()
    run_manager_trace_dir = root / f"run_manager_{uuid4().hex}"
    run_manager_trace_dir.mkdir()
    evaluator_trace_dir = root / f"evaluator_{uuid4().hex}"
    evaluator_trace_dir.mkdir()
    orchestrator_trace_dir = root / f"orchestrator_{uuid4().hex}"
    orchestrator_trace_dir.mkdir()

    planner_result = run_live_planner_and_compile(
        runtime,
        {
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
        out_dir=planner_trace_dir,
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
        out_dir=run_manager_trace_dir,
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
        out_dir=evaluator_trace_dir,
        archive_trace=True,
    )
    result = run_live_orchestrator(
        runtime,
        {
            "run_id": "run_001",
            "run_plan": planner_result["run_plan"],
            "compile_result": planner_result["compile_result"],
            "run_manager_log": run_manager_result,
            "run_evaluation": evaluator_result,
            "proposal_count": planner_result["proposal_count"],
            "valid_proposal_count": planner_result["valid_proposal_count"],
            "invalid_proposal_count": planner_result["invalid_proposal_count"],
            "warnings": planner_result["warnings"],
        },
        out_dir=orchestrator_trace_dir,
        archive_trace=True,
    )
    trace_path = orchestrator_trace_dir / "agentic_llm_trace_orchestrator.json"
    trace_json = json.loads(trace_path.read_text(encoding="utf-8"))
    markdown_write = write_agentic_llm_trace_markdown(trace_json, orchestrator_trace_dir, "orchestrator")
    print(f"AGENTIC_TRACE_JSON={trace_path}")
    print(f"AGENTIC_TRACE_MD={markdown_write['markdown_path']}")

    assert result["schema_version"] == ORCHESTRATOR_DECISION_SCHEMA_VERSION
    assert isinstance(result["decision"], str) and result["decision"].strip()
    assert isinstance(result["reason"], str) and result["reason"].strip()
    assert "next_run_goal" in result
    assert "evidence_used" in result
    assert isinstance(result["evidence_used"], list)
    json.loads(json.dumps(result))
    assert trace_path.exists()
    assert trace_json["parsed_output"]["schema_version"] == ORCHESTRATOR_DECISION_SCHEMA_VERSION
    assert "raw_output" in trace_json
