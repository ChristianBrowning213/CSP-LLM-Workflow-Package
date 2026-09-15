from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_guided_variant_sweep_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    case_file = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "experiment",
            "guided-sweep",
            "--mode",
            "stub",
            "--cases",
            str(case_file),
            "--repeats",
            "1",
            "--variants",
            "baseline_control,guided_hybrid_balanced,guided_property_push",
            "--metric-view",
            "property_aware",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    results_path = Path(lines[-2])
    report_path = Path(lines[-1])
    assert results_path.exists()
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "guided_variant_sweep.report.v1"
    assert report["rows"]
    assert report["per_variant_table"]
