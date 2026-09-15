from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.live_e2e


def _require_live_env() -> None:
    if os.environ.get("RUN_LIVE_E2E_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_E2E_TESTS=1 to run live e2e tests.")
    required = [
        "LLM_BASE_URL",
        "LLM_MODEL",
        "CRYSTALDB_MCP_CMD",
        "SPP_MCP_CMD",
        "QLIP_MCP_CMD",
    ]
    for key in required:
        if not os.environ.get(key):
            pytest.skip(f"Missing {key} for live e2e tests.")
    if not os.environ.get("LLM_API_KEY") and "localhost" not in os.environ.get("LLM_BASE_URL", ""):
        pytest.skip("Missing LLM_API_KEY for non-local LLM base URL.")


def test_live_pipeline_e2e() -> None:
    _require_live_env()
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    workspace = root / ".sokllm_workspace_live"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workspace),
            "eval",
            "e2e",
            "--mode",
            "live",
            "--query",
            os.environ.get("LIVE_E2E_QUERY", "TiO2 rutile-like"),
            "--cases",
            str(root / "docs" / "branch" / "benchmarks" / "internal_rediscovery_cases.json"),
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
