from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_chat_to_optimization_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "sok_llm_orchestrator.cli", "--workspace", str(workdir), "chat", "--mode", "stub"],
        cwd=str(root),
        env=env,
        input="optimize optimize high property x\nTiO2 optimize high property x\nexit\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "Session:" in proc.stdout

