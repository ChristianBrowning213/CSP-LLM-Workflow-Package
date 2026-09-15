from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_repeated_structural_runs_stub(workdir: Path) -> None:
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
            "--repeats",
            "2",
            "--action-profile",
            "live_structural",
            "--analysis-metric-view",
            "property_x",
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
    assert summary["schema_version"] == "first_crystal.repeated.summary.v1"
    assert int(summary["aggregate"]["total_runs"]) == 2
    assert "guidance_activation_rate" in summary["aggregate"]
    assert summary["per_case_table"]

    regen_proc = subprocess.run(
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
    assert regen_proc.returncode == 0, regen_proc.stdout + "\n" + regen_proc.stderr
    regen_path = Path(regen_proc.stdout.strip().splitlines()[-1])
    assert regen_path.exists()
