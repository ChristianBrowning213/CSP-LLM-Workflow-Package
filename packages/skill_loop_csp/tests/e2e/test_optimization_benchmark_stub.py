from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_optimization_benchmark_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    cases = root / "docs" / "branch" / "benchmarks" / "internal_optimization_behavior_cases.json"
    proc = subprocess.run(
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
            "--execution-family",
            "optimization",
            "--max-iterations",
            "3",
            "--cases",
            str(cases),
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    report_path = Path(proc.stdout.strip().splitlines()[-1])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "benchmark.optimization.report.v1"
    assert report["per_case_table"]
    assert report["aggregate_summary"]["total_cases"] >= 1
    classes = {row.get("case_class") for row in report["per_case_table"]}
    assert {"easy-improvement", "flat-stagnant", "misleading-local-optimum", "repeated-infeasible"}.issubset(classes)
