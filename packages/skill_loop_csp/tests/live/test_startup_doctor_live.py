from __future__ import annotations

import json
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
        "CRYSTALDB_MCP_CMD",
        "SPP_MCP_CMD",
        "QLIP_MCP_CMD",
    ]
    for key in required:
        if not os.environ.get(key):
            pytest.skip(f"Missing {key} for live startup doctor test.")


def test_startup_doctor_live() -> None:
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
            "doctor",
            "startup",
            "--mode",
            "live",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    report_path = Path(proc.stdout.strip().splitlines()[-1])
    assert report_path.exists(), proc.stdout + "\n" + proc.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "startup.report.v1"
    assert isinstance(report.get("startup_ok"), bool)
    if not report["startup_ok"]:
        assert isinstance(report.get("blocked_by"), str)
