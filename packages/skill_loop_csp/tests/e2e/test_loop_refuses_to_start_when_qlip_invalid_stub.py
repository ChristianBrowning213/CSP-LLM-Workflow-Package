from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_loop_refuses_to_start_when_qlip_invalid_stub(workdir) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["FAKE_QLIP_PLACEHOLDER_SOLUTION"] = "1"
    proc = subprocess.run(
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
            "TiO2 startup gate probe",
            "--no-run",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "QLIP_PLACEHOLDER_SOLUTION" in (proc.stdout + proc.stderr)
    report_path = workdir / "startup" / "startup_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["startup_ok"] is False
    assert report["blocked_by"] == "QLIP_PLACEHOLDER_SOLUTION"
