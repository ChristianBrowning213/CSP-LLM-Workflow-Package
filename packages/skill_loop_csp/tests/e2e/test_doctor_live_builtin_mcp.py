from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

import pytest


pytestmark = pytest.mark.live_e2e


def _has_local_llm() -> bool:
    try:
        with urlopen("http://localhost:1234/v1/models", timeout=2):  # noqa: S310
            return True
    except Exception:  # noqa: BLE001
        return False


def test_doctor_live_builtin_mcp(workdir: Path) -> None:
    if not _has_local_llm():
        pytest.skip("Local LLM at localhost:1234 is required for doctor live integration test.")
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "doctor",
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
    assert report["mode"] == "live"
    assert isinstance(report.get("ok"), bool)
    if proc.returncode == 0:
        assert report["ok"] is True
        return
    assert report["ok"] is False
    checks = report.get("checks", [])
    assert isinstance(checks, list) and checks
    llm_check = next((item for item in checks if item.get("name") == "llm_config"), None)
    startup_check = next((item for item in checks if item.get("name") == "startup_validation"), None)
    assert llm_check is not None
    assert startup_check is not None
    assert isinstance(llm_check.get("error"), str) or bool(llm_check.get("ok")) is True
    assert isinstance(startup_check.get("blocked_by"), str) or bool(startup_check.get("ok")) is True
