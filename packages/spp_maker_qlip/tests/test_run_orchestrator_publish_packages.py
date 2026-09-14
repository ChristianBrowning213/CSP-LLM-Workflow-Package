"""Publish integration test for run orchestrator (SPP + guidance + package)."""

from __future__ import annotations

import json
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


def test_run_orchestrator_publish_packages(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    qlip_outputs = tmp_path / "QLIP_Outputs"
    result = _run_module_cli(
        "run",
        "--name",
        "publish_run",
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
        "--publish_to",
        str(qlip_outputs),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    run_id = _extract_run_id(result.stdout)

    index = json.loads((qlip_outputs / "index.json").read_text(encoding="utf-8"))
    assert index["artifacts"]["spp"]["runs"]
    assert index["artifacts"]["guidances"]["runs"]
    assert index["artifacts"]["packages"]["runs"]
    assert (qlip_outputs / "SPP" / "latest.txt").is_file()
    assert (qlip_outputs / "GUIDANCES" / "latest.txt").is_file()
    assert (qlip_outputs / "PACKAGES" / "latest.txt").is_file()
    assert "PACKAGES/runs/" in (qlip_outputs / "PACKAGES" / "latest.txt").read_text(encoding="utf-8")

    final_tree = out_dir / "Final_QLIP_output" / run_id / "qlip_outputs_tree"
    assert (final_tree / "index.json").is_file()
    assert (final_tree / "SPP" / "latest.txt").is_file()
    assert (final_tree / "GUIDANCES" / "latest.txt").is_file()
    assert (final_tree / "PACKAGES" / "latest.txt").is_file()
