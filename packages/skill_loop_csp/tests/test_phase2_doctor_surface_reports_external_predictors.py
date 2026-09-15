from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_phase2_doctor_surface_reports_external_predictors() -> None:
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "sok_llm_orchestrator.cli", "doctor", "phase2-external-predictors"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "phase2.external_predictor_library.v1"
    assert payload["phase1_native_objective_registry"] == "separate"
    ids = {row["id"] for row in payload["all_entries"]}
    assert "phase2.external.pymatgen_composition_descriptor" in ids
    assert "phase2.external.matminer_formation_energy_rf" in ids
