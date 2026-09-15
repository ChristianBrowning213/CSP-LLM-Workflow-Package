from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_doctor_phase1_properties_cli() -> None:
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "sok_llm_orchestrator.cli", "doctor", "phase1-properties", "--implemented-only"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "phase1.property_library.v1"
    ids = {row["id"] for row in payload["all_entries"]}
    assert "qlip.objective.energy_proxy" in ids
    assert "qlip.property.property_x_estimate" in ids
