from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_optimize_cli_commands_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")

    start = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "optimize",
            "start",
            "--mode",
            "stub",
            "--query",
            "TiO2 optimize high property x",
            "--max-iterations",
            "2",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert start.returncode == 0, start.stdout + "\n" + start.stderr
    session_path = Path(start.stdout.strip().splitlines()[-1])
    assert session_path.exists()
    session = json.loads(session_path.read_text(encoding="utf-8"))
    session_id = session["session_id"]

    status = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "optimize",
            "status",
            "--mode",
            "stub",
            "--session-id",
            session_id,
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode == 0
    assert f"Session: {session_id}" in status.stdout

