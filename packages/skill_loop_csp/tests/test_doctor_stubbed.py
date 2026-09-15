from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_doctor_stubbed(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
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
            "stub",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    report_path = Path(proc.stdout.strip().splitlines()[-1])
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["ok"] is True
