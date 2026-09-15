from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from sok_llm_orchestrator.agentic.demo_bundle import write_demo_showcase_bundle
from sok_llm_orchestrator.agentic.demo_loop import (
    SHOWCASE_DEFAULT_GOAL,
    build_demo_mcp_settings,
    build_showcase_six_tool_run_plan,
    run_demo_execution_loop,
)
from sok_llm_orchestrator.agentic.tool_execution_adapters import get_default_tool_execution_adapters


pytestmark = pytest.mark.live_e2e


def _require_real_mcp_demo() -> None:
    if os.environ.get("RUN_LIVE_E2E_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_E2E_TESTS=1 to run live execution tests.")
    if not (Path.cwd() / "my_live_config.yaml").exists():
        pytest.skip("my_live_config.yaml is required for configured real MCP demo test.")


def test_demo_loop_showcase_with_configured_real_mcp_logs_truthfully() -> None:
    _require_real_mcp_demo()

    root = Path.cwd() / "test_workdir" / "agentic_demo_loop_real_mcp_live"
    root.mkdir(parents=True, exist_ok=True)
    case_dir = root / f"case_{uuid4().hex}"
    case_dir.mkdir()

    settings = build_demo_mcp_settings(case_dir / "_raw_run", "configured")
    run_plan = build_showcase_six_tool_run_plan(
        goal=SHOWCASE_DEFAULT_GOAL,
        run_id="showcase_run_001",
        material_system="CoAs2",
    )
    planner_compile_run = {
        "schema_version": "agentic_csp.planner_compile_run.v1",
        "run_id": "showcase_run_001",
        "run_plan": run_plan,
        "plan_source": "deterministic_showcase",
        "material_system": "CoAs2",
        "mcp_backend": "configured",
        "live_llm_used": False,
    }

    result = run_demo_execution_loop(
        out_dir=case_dir / "_raw_run",
        planner_compile_run=planner_compile_run,
        allow_real_execution=True,
        allowed_tools=[
            "crystal.csp_pack",
            "crystal.novelty_check",
            "spp.run_pipeline",
            "spp.package_for_qlip",
            "qlip.validate_request",
            "qlip.solve",
        ],
        adapters=get_default_tool_execution_adapters(settings),
        plan_source="deterministic_showcase",
        mcp_backend="configured",
        material_system="CoAs2",
    )
    bundle = write_demo_showcase_bundle(result, case_dir / "showcase", zip_bundle=False)

    report_md = Path(bundle["report_markdown_path"])
    execution_run_json = Path(result["execution_run_path"])
    step_log_jsonl = Path(result["step_log_path"])

    print(f"AGENTIC_DEMO_BUNDLE_ROOT={bundle['bundle_root']}")
    print(f"AGENTIC_DEMO_REPORT_MD={bundle['report_markdown_path']}")
    print(f"AGENTIC_DEMO_ZIP={bundle['zip_path'] or 'NONE'}")

    assert report_md.exists()
    assert execution_run_json.exists()
    assert step_log_jsonl.exists()

    markdown = report_md.read_text(encoding="utf-8")
    assert "backend: configured" in markdown
    assert "plan_source: deterministic_showcase" in markdown
    assert "Fake MCP backend is in use for this demo run." not in markdown

    execution_run = json.loads(execution_run_json.read_text(encoding="utf-8"))
    step_results = execution_run.get("step_results", [])
    assert isinstance(step_results, list) and step_results
    assert step_results[0].get("tool_name") == "crystal.csp_pack"
    assert step_results[0].get("status") in {"succeeded", "failed", "blocked"}
    assert all(
        step.get("status") in {"succeeded", "failed", "blocked"}
        and isinstance(step.get("tool_name"), str)
        for step in step_results
    )
    assert execution_run.get("executed_tool_sequence") or execution_run.get("blocked_tool_sequence")
