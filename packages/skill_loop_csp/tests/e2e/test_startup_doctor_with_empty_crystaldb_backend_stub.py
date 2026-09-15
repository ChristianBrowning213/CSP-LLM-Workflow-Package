from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_startup_doctor_with_empty_crystaldb_backend_stub(workdir) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["FAKE_CRYSTALDB_EMPTY_RETRIEVAL"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "doctor",
            "startup",
            "--mode",
            "stub",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    report = json.loads((workdir / "startup" / "startup_report.json").read_text(encoding="utf-8"))
    assert report["blocked_by"] == "CRYSTALDB_EMPTY_RETRIEVAL"

