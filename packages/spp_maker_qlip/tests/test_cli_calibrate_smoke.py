"""Smoke tests for `spp-maker calibrate` CLI."""

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


def test_cli_calibrate_smoke_writes_scaled_root(tmp_path: Path) -> None:
    spp_root = tmp_path / "spp_out"
    fit_result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(spp_root),
        "--r_cut",
        "8.0",
    )
    assert fit_result.returncode == 0, fit_result.stderr

    out_json = tmp_path / "calibration.json"
    scaled_root = tmp_path / "spp_scaled"
    result = _run_module_cli(
        "calibrate",
        "--spp_root",
        str(spp_root),
        "--cif_dir",
        "tests/fixtures/cifs",
        "--target",
        "5.0",
        "--max_n",
        "2",
        "--out_json",
        str(out_json),
        "--write_scaled_root",
        str(scaled_root),
    )
    assert result.returncode == 0, result.stderr
    assert "recommended_lambda" in result.stdout
    assert (scaled_root / "manifest.json").is_file()

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert float(payload["recommended_lambda"]) > 0.0


def test_cli_calibrate_publish_guidance_smoke(tmp_path: Path) -> None:
    spp_root = tmp_path / "spp_out_publish"
    fit_result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(spp_root),
        "--r_cut",
        "8.0",
    )
    assert fit_result.returncode == 0, fit_result.stderr

    qlip_outputs = tmp_path / "QLIP_Outputs"
    result = _run_module_cli(
        "calibrate",
        "--spp_root",
        str(spp_root),
        "--cif_dir",
        "tests/fixtures/cifs",
        "--target",
        "5.0",
        "--max_n",
        "2",
        "--publish",
        "--qlip_outputs",
        str(qlip_outputs),
        "--name",
        "calibration_test",
    )
    assert result.returncode == 0, result.stderr
    assert "published_run_id" in result.stdout

    index_path = qlip_outputs / "index.json"
    assert index_path.is_file()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    guidance_runs = index["artifacts"]["guidances"]["runs"]
    assert len(guidance_runs) >= 1
