from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from sok_llm_orchestrator.agentic.archive import write_agentic_llm_trace_markdown
from sok_llm_orchestrator.agentic.llm_runtime import AgentLLMRuntime
from sok_llm_orchestrator.agentic.plan_compile import PLAN_COMPILE_SCHEMA_VERSION
from sok_llm_orchestrator.agentic.planner_runtime import (
    PLANNER_COMPILE_RUN_SCHEMA_VERSION,
    run_live_planner_and_compile,
)
from sok_llm_orchestrator.agentic.schemas import RUN_PLAN_SCHEMA_VERSION
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


def test_live_planner_helper_returns_valid_run_plan_compiles_proposals_and_writes_trace() -> None:
    settings = _require_live_settings()
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model or "",
        timeout_s=settings.llm_timeout_s,
        max_retries=1,
    )
    runtime = AgentLLMRuntime(client=client, max_attempts=2)

    root = Path.cwd() / "test_workdir" / "agentic_live_planner"
    root.mkdir(parents=True, exist_ok=True)
    trace_dir = root / f"case_{uuid4().hex}"
    trace_dir.mkdir()
    result = run_live_planner_and_compile(
        runtime,
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
        out_dir=trace_dir,
        archive_trace=True,
        require_proposals=True,
    )
    trace_path = trace_dir / "agentic_llm_trace_planner.json"
    trace_json = json.loads(trace_path.read_text(encoding="utf-8"))
    markdown_write = write_agentic_llm_trace_markdown(trace_json, trace_dir, "planner")
    print(f"AGENTIC_TRACE_JSON={trace_path}")
    print(f"AGENTIC_TRACE_MD={markdown_write['markdown_path']}")
    run_plan = result["run_plan"]
    compile_result = result["compile_result"]

    assert result["schema_version"] == PLANNER_COMPILE_RUN_SCHEMA_VERSION
    assert run_plan["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert compile_result["schema_version"] == PLAN_COMPILE_SCHEMA_VERSION
    assert "overall_goal" in run_plan
    assert "run_goal" in run_plan
    assert "stage" in run_plan
    assert isinstance(run_plan["plan_as_text"], str) and run_plan["plan_as_text"].strip()
    json.loads(json.dumps(result))
    assert result["proposal_count"] >= 1
    assert result["valid_proposal_count"] >= 1
    assert compile_result["proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert compile_result["validation_results"][0]["valid"] is True
    assert trace_path.exists()
    assert trace_json["parsed_output"]["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert "raw_output" in trace_json
