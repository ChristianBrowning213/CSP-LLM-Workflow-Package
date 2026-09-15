from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_cli_optimize_help() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "sok_llm_orchestrator.cli", "optimize", "--help"],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "start" in proc.stdout
    assert "show-best" in proc.stdout

