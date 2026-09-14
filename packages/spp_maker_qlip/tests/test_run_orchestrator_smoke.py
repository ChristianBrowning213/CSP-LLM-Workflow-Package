"""Smoke test for one-command run orchestrator."""

from __future__ import annotations

import os
import re
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


def _extract_run_id(stdout: str) -> str:
    match = re.search(r"run_id:\s+([^\r\n]+)", stdout)
    if not match:
        raise AssertionError(f"Could not parse run_id from output:\n{stdout}")
    return match.group(1).strip()


def test_run_orchestrator_smoke(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = _run_module_cli(
        "run",
        "--name",
        "smoke_run",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_dir",
        str(out_dir),
        "--fit_method",
        "neighbors",
        "--calib_score_method",
        "neighbors",
        "--target",
        "5.0",
        "--max_calib",
        "2",
        "--no_bandpass",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    run_id = _extract_run_id(result.stdout)

    run_root = out_dir / "SPP_Runs" / run_id
    final_root = out_dir / "Final_QLIP_output" / run_id

    assert (run_root / "input_snapshot" / "params.json").is_file()
    assert (run_root / "input_snapshot" / "env.json").is_file()
    assert (run_root / "input_snapshot" / "cif_list.txt").is_file()

    assert (run_root / "fit" / "spp_root").is_dir()
    assert (run_root / "fit" / "manifest.json").is_file()
    assert (run_root / "fit" / "compat_report_fit.txt").is_file()

    assert (run_root / "calibrate" / "calibration.json").is_file()
    assert (run_root / "calibrate" / "scaled_spp_root").is_dir()
    assert (run_root / "calibrate" / "compat_report_scaled.txt").is_file()

    assert (run_root / "package" / "package.json").is_file()
    assert (run_root / "package" / "snippet.py.txt").is_file()

    assert (run_root / "logs" / "run_summary.txt").is_file()
    assert (run_root / "logs" / "timings.json").is_file()

    assert (final_root / "package.json").is_file()
    assert (final_root / "spp_root").is_dir()
    assert (final_root / "guidance" / "calibration.json").is_file()
    assert (final_root / "compat_report.txt").is_file()
    assert (final_root / "README.txt").is_file()
