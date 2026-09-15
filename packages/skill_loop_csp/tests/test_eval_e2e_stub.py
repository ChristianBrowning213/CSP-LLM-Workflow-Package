from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_eval_e2e_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["FAKE_CRYSTAL_ALLOW_EXPORT"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "eval",
            "e2e",
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
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    names = [step["name"] for step in report["steps"]]
    assert names == ["doctor", "pipeline_guided", "paired_run", "benchmark_run"]
