"""Determinism checks for one-command run orchestrator."""

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


def _run_once(base: Path) -> tuple[str, dict, list[str]]:
    result = _run_module_cli(
        "run",
        "--name",
        "determinism_run",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_dir",
        str(base),
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
    run_root = base / "SPP_Runs" / run_id
    package_payload = json.loads((run_root / "package" / "package.json").read_text(encoding="utf-8"))
    pot_files = sorted(
        path.relative_to(run_root / "calibrate" / "scaled_spp_root").as_posix()
        for path in (run_root / "calibrate" / "scaled_spp_root").rglob("*.POT")
    )
    return run_id, package_payload, pot_files


def test_run_orchestrator_determinism(tmp_path: Path) -> None:
    _, pkg_a, pots_a = _run_once(tmp_path / "out_a")
    _, pkg_b, pots_b = _run_once(tmp_path / "out_b")

    assert pkg_a["content_hash"] == pkg_b["content_hash"]
    assert float(pkg_a["lambda_used"]) == float(pkg_b["lambda_used"])
    assert pots_a == pots_b
