"""Calibration JSON explainability for negative-score scenarios."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_module_cli(*args: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_path) if not existing else f"{src_path}{os.pathsep}{existing}"
    return subprocess.run(
        [sys.executable, "-m", "spp_maker.cli", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=repo_root,
    )


def test_calibrate_json_explains_lambda_sign_and_clipping(tmp_path: Path) -> None:
    spp_root = tmp_path / "spp_out"
    fit_result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(spp_root),
        "--fit_method",
        "supercell_gr",
    )
    assert fit_result.returncode == 0, fit_result.stderr

    out_json = tmp_path / "calibration.json"
    result = _run_module_cli(
        "calibrate",
        "--spp_root",
        str(spp_root),
        "--cif_dir",
        "tests/fixtures/cifs",
        "--mode",
        "structure_median",
        "--score_method",
        "supercell_gr",
        "--target",
        "10.0",
        "--out_json",
        str(out_json),
    )
    assert result.returncode == 0, result.stderr

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    for key in (
        "lambda_raw",
        "lambda_abs",
        "lambda_clipped",
        "min_lambda",
        "max_lambda",
        "lambda_used",
        "convention",
        "score_method",
        "bandpass_enabled",
    ):
        assert key in payload

    median = float(payload["stats"]["summary"]["structure_scores"]["median"])
    assert median < 0.0
    assert payload["convention"] == "reward"
    assert payload["score_method"] == "supercell_gr"
    assert payload["lambda_used"] == payload["recommended_lambda"]
    assert float(payload["lambda_abs"]) == abs(float(payload["lambda_raw"]))
    assert float(payload["lambda_used"]) != 1.0
