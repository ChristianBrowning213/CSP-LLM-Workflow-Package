from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_startup_doctor_with_realistic_crystaldb_stub(workdir) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env.pop("FAKE_CRYSTALDB_COLLAPSED", None)
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
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    report = json.loads((workdir / "startup" / "startup_report.json").read_text(encoding="utf-8"))
    crystal = report["dependencies"]["crystaldb"]
    probe = crystal["probe"]
    assert crystal["semantic_ok"] is True
    assert probe["candidate_signature_a"] != probe["candidate_signature_b"]

