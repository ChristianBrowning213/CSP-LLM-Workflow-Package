from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_branch_benchmark_stub(workdir) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[2]
    cases = root / "docs" / "branch" / "benchmarks" / "internal_rediscovery_cases.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")

    run_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "benchmark",
            "run",
            "--mode",
            "stub",
            "--cases",
            str(cases),
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run_proc.returncode == 0
    report_path = Path(run_proc.stdout.strip().splitlines()[-1])
    assert report_path.exists()

    cmp_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "benchmark",
            "compare",
            "--left",
            str(report_path),
            "--right",
            str(report_path),
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert cmp_proc.returncode == 0
    compare_path = Path(cmp_proc.stdout.strip().splitlines()[-1])
    assert compare_path.exists()
