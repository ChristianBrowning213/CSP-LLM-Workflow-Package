from __future__ import annotations

import os
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from sok_llm_orchestrator.agentic.archive import (
    run_agent_and_archive_trace,
    write_agentic_llm_trace_markdown,
)
from sok_llm_orchestrator.agentic.llm_runtime import AgentLLMRuntime
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


def test_agentic_planner_live_llm_returns_valid_run_plan() -> None:
    settings = _require_live_settings()
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model or "",
        timeout_s=settings.llm_timeout_s,
        max_retries=1,
    )
    runtime = AgentLLMRuntime(client=client, max_attempts=2)

    root = Path.cwd() / "test_workdir" / "agentic_live_trace"
    root.mkdir(parents=True, exist_ok=True)
    trace_dir = root / f"case_{uuid4().hex}"
    trace_dir.mkdir()
    archived = run_agent_and_archive_trace(
        runtime,
        "planner",
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
        "run_plan",
        trace_dir,
    )
    parsed_output = archived["parsed_output"]
    assert parsed_output is not None
    trace_json_path = Path(archived["trace_write"]["trace_json_path"])
    trace_json = json.loads(trace_json_path.read_text(encoding="utf-8"))
    markdown_write = write_agentic_llm_trace_markdown(trace_json, trace_dir, "planner")
    print(f"AGENTIC_TRACE_JSON={trace_json_path}")
    print(f"AGENTIC_TRACE_MD={markdown_write['markdown_path']}")

    assert parsed_output["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    for key in ("overall_goal", "run_goal", "stage", "plan_as_text"):
        assert key in parsed_output
    json.loads(json.dumps(parsed_output))
    assert trace_json_path.exists()
    assert trace_json["parsed_output"]["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert "raw_output" in trace_json
