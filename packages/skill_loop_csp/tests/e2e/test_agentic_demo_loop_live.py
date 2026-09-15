from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from sok_llm_orchestrator.agentic.demo_bundle import write_demo_showcase_bundle
from sok_llm_orchestrator.agentic.demo_loop import run_demo_execution_loop
from sok_llm_orchestrator.agentic.llm_runtime import AgentLLMRuntime
from sok_llm_orchestrator.agentic.tool_execution_adapters import get_default_tool_execution_adapters
from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.llm.client import LLMClient


pytestmark = [pytest.mark.live_e2e, pytest.mark.live_llm]


def _require_live_settings() -> Settings:
    if os.environ.get("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to run live LLM tests.")
    if os.environ.get("RUN_LIVE_E2E_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_E2E_TESTS=1 to run live execution tests.")
    settings = Settings.from_sources(None)
    if settings.llm_api_key is None or settings.llm_model is None:
        pytest.skip("Live LLM settings are not configured.")
    return settings


def _fake_live_settings(workdir: Path) -> Settings:
    root = Path(__file__).resolve().parents[2]
    return Settings(
        workspace_root=workdir,
        crystaldb_mcp_cmd=[sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_crystaldb_server.py")],
        spp_mcp_cmd=[sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_spp_server.py")],
        qlip_mcp_cmd=[sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_qlip_server.py")],
        crystaldb_mcp_cwd=str(root),
        spp_mcp_cwd=str(root),
        qlip_mcp_cwd=str(root),
        crystaldb_policy_mode="demo",
        max_runtime_seconds=30,
    )


def test_live_demo_execution_loop_writes_visual_report() -> None:
    settings = _require_live_settings()
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model or "",
        timeout_s=settings.llm_timeout_s,
        max_retries=1,
    )
    runtime = AgentLLMRuntime(client=client, max_attempts=2)

    root = Path.cwd() / "test_workdir" / "agentic_demo_loop_live"
    root.mkdir(parents=True, exist_ok=True)
    case_dir = root / f"case_{uuid4().hex}"
    case_dir.mkdir()

    result = run_demo_execution_loop(
        out_dir=case_dir,
        llm_runtime=runtime,
        planner_input={
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "run_goal": (
                "propose and execute a future csp workflow sequence from retrieval through novelty review "
                "with crystal.csp_pack, spp, qlip, and novelty steps"
            ),
            "stage": "wide_exploration",
        },
        allow_real_execution=True,
        allowed_tools=[
            "crystal.csp_pack",
            "crystal.novelty_check",
            "spp.run_pipeline",
            "spp.package_for_qlip",
            "qlip.validate_request",
            "qlip.solve",
        ],
        adapters=get_default_tool_execution_adapters(_fake_live_settings(case_dir)),
    )
    bundle = write_demo_showcase_bundle(result, case_dir / "showcase", zip_bundle=False)

    report_md = Path(result["report_markdown_path"])
    report_json = Path(result["artifact_paths"]["execution_loop_report_json"])
    execution_run_json = Path(result["execution_run_path"])
    step_log_jsonl = Path(result["step_log_path"])
    bundle_root = Path(bundle["bundle_root"])
    bundle_readme = Path(bundle["readme_path"])
    bundle_manifest = Path(bundle["manifest_path"])

    print(f"AGENTIC_DEMO_BUNDLE_ROOT={bundle_root}")
    print(f"AGENTIC_DEMO_REPORT_MD={bundle['report_markdown_path']}")
    print(f"AGENTIC_DEMO_ZIP={bundle['zip_path'] or 'NONE'}")

    assert report_md.exists()
    assert report_json.exists()
    assert execution_run_json.exists()
    assert step_log_jsonl.exists()
    assert bundle_readme.exists()
    assert bundle_manifest.exists()

    markdown = report_md.read_text(encoding="utf-8")
    assert "## Sequence Diagram" in markdown
    assert "```mermaid" in markdown
    assert "## Final Outputs" in markdown
    assert "## LLM Plan" in markdown
    assert "crystal.csp_pack" in markdown
    assert "No old hardcoded pipeline shortcut was used." in markdown

    report_payload = json.loads(report_json.read_text(encoding="utf-8"))
    execution_payload = json.loads(execution_run_json.read_text(encoding="utf-8"))
    assert report_payload["tool_execution_log"]
    assert report_payload["sequence_diagram_markdown"].startswith("```mermaid")
    assert execution_payload["executed_tool_sequence"] or execution_payload["blocked_tool_sequence"]
