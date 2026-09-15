from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_first_crystal_cli_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    cases = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"

    run_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "experiment",
            "run",
            "--mode",
            "stub",
            "--cases",
            str(cases),
            "--max-iterations",
            "2",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run_proc.returncode == 0, run_proc.stdout + "\n" + run_proc.stderr
    lines = [line.strip() for line in run_proc.stdout.splitlines() if line.strip()]
    manifest_path = Path(lines[-2])
    summary_path = Path(lines[-1])
    assert manifest_path.exists()
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["rows"]
    assert summary["rows"][0]["best_action_id"] is not None

    sum_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "experiment",
            "summarize",
            "--manifest",
            str(manifest_path),
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert sum_proc.returncode == 0, sum_proc.stdout + "\n" + sum_proc.stderr
    regen_path = Path(sum_proc.stdout.strip().splitlines()[-1])
    assert regen_path.exists()

