from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_repeated_structural_property_aware_stub(workdir: Path) -> None:
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
            "--selection-view",
            "property_aware",
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
    view_summary = summary["aggregate"]["view_summary"]
    assert "total_objective" in view_summary
    assert "property_aware" in view_summary
    assert int(summary["aggregate"]["total_runs"]) == 2
    assert any(
        str(row.get("selection_metric_view", "")) == "property_aware"
        for row in summary.get("run_case_rows", [])
        if isinstance(row, dict)
    )

